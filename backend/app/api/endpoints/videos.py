import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, UploadFile, File, Form, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from greek_sub_publisher.app_settings import load_app_settings

from ... import config
from ...jobs import JobStore
from ...video_processing import normalize_and_stub_subtitles
from ...auth import User
from ...history import HistoryStore
from ...schemas import JobResponse
from ..deps import get_current_user, get_job_store, get_history_store

router = APIRouter()

APP_SETTINGS = load_app_settings()
MAX_UPLOAD_BYTES = APP_SETTINGS.max_upload_mb * 1024 * 1024

# Ensure data directories exist
DATA_DIR = config.PROJECT_ROOT.parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

class ProcessingSettings(BaseModel):
    transcribe_model: str = "medium"
    video_quality: str = "balanced"
    use_llm: bool = APP_SETTINGS.use_llm_by_default
    context_prompt: str = ""
    llm_model: str = APP_SETTINGS.llm_model
    llm_temperature: float = APP_SETTINGS.llm_temperature


def _save_upload_with_limit(upload: UploadFile, destination: Path) -> None:
    """Write an upload to disk while enforcing the configured size limit."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    upload.file.seek(0)
    with destination.open("wb") as buffer:
        for chunk in iter(lambda: upload.file.read(1024 * 1024), b""):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                buffer.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large; limit is {APP_SETTINGS.max_upload_mb}MB",
                )
            buffer.write(chunk)


def _record_event_safe(
    history_store: HistoryStore | None,
    user: User | None,
    kind: str,
    summary: str,
    data: dict,
) -> None:
    """Best-effort history logger that never raises."""
    if not history_store or not user:
        return
    try:
        history_store.record_event(user, kind, summary, data)
    except Exception:
        return

def run_video_processing(
    job_id: str,
    input_path: Path,
    output_path: Path,
    artifact_dir: Path,
    settings: ProcessingSettings,
    job_store: JobStore,
    history_store: HistoryStore | None = None,
    user: User | None = None,
    original_name: str | None = None,
):
    """Background task to run the heavy video processing."""
    try:
        job_store.update_job(job_id, status="processing", progress=0, message="Starting processing...")
        
        def progress_callback(msg: str, percent: float):
            # Throttle DB updates? For SQLite it's fast enough for coarse updates (5-10%)
            # But let's just write.
            job_store.update_job(job_id, progress=int(percent), message=msg)

        # Map settings to internal params
        # (Simplified logic from original app.py)
        model_size = settings.transcribe_model
        crf_map = {"low size": 28, "balanced": 23, "high quality": 18}
        video_crf = crf_map.get(settings.video_quality.lower(), 23)

        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        result = normalize_and_stub_subtitles(
            input_path=input_path,
            output_path=output_path,
            model_size=model_size,
            generate_social_copy=settings.use_llm,
            use_llm_social_copy=settings.use_llm,
            llm_model=settings.llm_model,
            llm_temperature=settings.llm_temperature,
            artifact_dir=artifact_dir,
            video_crf=video_crf,
            initial_prompt=settings.context_prompt,
            progress_callback=progress_callback
        )
        
        # Result unpacking
        social = None
        final_path = output_path
        if isinstance(result, tuple):
            final_path, social = result
        else:
            final_path = result
            
        result_data = {
            "video_path": str(final_path.relative_to(config.PROJECT_ROOT.parent)), # Relative to backend root for serving
            "artifacts_dir": str(artifact_dir.relative_to(config.PROJECT_ROOT.parent)),
            "public_url": f"/static/{final_path.relative_to(DATA_DIR).as_posix()}",
            "artifact_url": f"/static/{artifact_dir.relative_to(DATA_DIR).as_posix()}",
            "social": social.tiktok.title if social else None, # Just storing title for simple view now
            "original_filename": original_name or input_path.name,
            "video_crf": video_crf,
            "model_size": model_size,
        }
        
        job_store.update_job(job_id, status="completed", progress=100, message="Done!", result_data=result_data)
        _record_event_safe(
            history_store,
            user,
            "process_completed",
            f"Processed {original_name or input_path.name}",
            {
                "job_id": job_id,
                "model_size": model_size,
                "video_crf": video_crf,
                "output": result_data.get("public_url"),
                "artifacts": result_data.get("artifact_url"),
            },
        )

    except Exception as e:
        job_store.update_job(job_id, status="failed", message=str(e))
        _record_event_safe(
            history_store,
            user,
            "process_failed",
            f"Processing failed for {original_name or input_path.name}",
            {"job_id": job_id, "error": str(e)},
        )


@router.post("/process", response_model=JobResponse)
async def process_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    transcribe_model: str = Form("medium"),
    video_quality: str = Form("balanced"),
    use_llm: bool = Form(APP_SETTINGS.use_llm_by_default),
    context_prompt: str = Form(""),
    request: Request,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Upload a video and start processing."""
    job_id = str(uuid.uuid4())
    
    # Save Upload
    file_ext = Path(file.filename).suffix
    if file_ext not in [".mp4", ".mov", ".mkv"]:
        raise HTTPException(400, "Invalid file type")
    
    input_path = UPLOADS_DIR / f"{job_id}_input{file_ext}"
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Request too large; limit is {APP_SETTINGS.max_upload_mb}MB",
                )
        except ValueError:
            pass
    _save_upload_with_limit(file, input_path)
        
    # Prepare Output
    output_path = ARTIFACTS_DIR / job_id / f"processed.mp4"
    artifact_path = ARTIFACTS_DIR / job_id 
    
    # Create Job
    job = job_store.create_job(job_id, current_user.id)
    _record_event_safe(
        history_store,
        current_user,
        "process_started",
        f"Queued {file.filename}",
        {
            "job_id": job_id,
            "model_size": transcribe_model,
            "video_quality": video_quality,
            "use_llm": use_llm,
        },
    )
    
    # Enqueue Task
    settings = ProcessingSettings(
        transcribe_model=transcribe_model,
        video_quality=video_quality,
        use_llm=use_llm,
        context_prompt=context_prompt
    )
    
    background_tasks.add_task(
        run_video_processing,
        job_id,
        input_path,
        output_path,
        artifact_path,
        settings,
        job_store,
        history_store,
        current_user,
        file.filename,
    )
    
    return job

@router.get("/jobs", response_model=List[JobResponse])
def list_jobs(
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    return job_store.list_jobs_for_user(current_user.id)

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")
    return job
