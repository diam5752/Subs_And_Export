import shutil
import uuid
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, Depends, UploadFile, File, Form, BackgroundTasks, HTTPException
from pydantic import BaseModel

from ... import config
from ...jobs import JobStore
from ...video_processing import normalize_and_stub_subtitles
from ...auth import User
from ...schemas import JobResponse
from ..deps import get_current_user, get_job_store

router = APIRouter()

# Ensure data directories exist
DATA_DIR = config.PROJECT_ROOT.parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
ARTIFACTS_DIR = DATA_DIR / "artifacts"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

class ProcessingSettings(BaseModel):
    transcribe_model: str = "medium"
    video_quality: str = "balanced"
    use_llm: bool = False
    context_prompt: str = ""

def run_video_processing(
    job_id: str,
    input_path: Path,
    output_path: Path,
    artifact_dir: Path,
    settings: ProcessingSettings,
    job_store: JobStore
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
        
        result = normalize_and_stub_subtitles(
            input_path=input_path,
            output_path=output_path,
            model_size=model_size,
            generate_social_copy=settings.use_llm,
            use_llm_social_copy=settings.use_llm,
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
            "social": social.tiktok.title if social else None # Just storing title for simple view now
        }
        
        job_store.update_job(job_id, status="completed", progress=100, message="Done!", result_data=result_data)

    except Exception as e:
        job_store.update_job(job_id, status="failed", message=str(e))


@router.post("/process", response_model=JobResponse)
async def process_video(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    transcribe_model: str = Form("medium"),
    video_quality: str = Form("balanced"),
    use_llm: bool = Form(False),
    context_prompt: str = Form(""),
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    """Upload a video and start processing."""
    job_id = str(uuid.uuid4())
    
    # Save Upload
    file_ext = Path(file.filename).suffix
    if file_ext not in [".mp4", ".mov", ".mkv"]:
        raise HTTPException(400, "Invalid file type")
    
    input_path = UPLOADS_DIR / f"{job_id}_input{file_ext}"
    with input_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    # Prepare Output
    output_path = ARTIFACTS_DIR / job_id / f"processed.mp4"
    artifact_path = ARTIFACTS_DIR / job_id 
    
    # Create Job
    job = job_store.create_job(job_id, current_user.id)
    
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
        job_store
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
