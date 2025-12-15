import re
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from ...core import config
from ...core.auth import User
from ...core.ratelimit import limiter_content, limiter_processing
from ...core.settings import load_app_settings
from ...schemas.base import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    JobResponse,
    PaginatedJobsResponse,
    ViralMetadataResponse,
)
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.subtitles import generate_viral_metadata
from ...services.video_processing import normalize_and_stub_subtitles
from ..deps import get_current_user, get_history_store, get_job_store

router = APIRouter()

APP_SETTINGS = load_app_settings()
MAX_UPLOAD_BYTES = APP_SETTINGS.max_upload_mb * 1024 * 1024

def _data_roots() -> tuple[Path, Path, Path]:
    """Resolve data directories relative to the configured project root."""
    # Use backend/data for all artifacts (not PROJECT_ROOT.parent)
    data_dir = config.PROJECT_ROOT / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, uploads_dir, artifacts_dir


def _relpath_safe(path: Path, base: Path) -> Path:
    """Return ``path`` relative to ``base`` when possible, otherwise the absolute path."""
    try:
        return path.relative_to(base)
    except ValueError:
        return path

# Initialize directories on import
DATA_DIR, UPLOADS_DIR, ARTIFACTS_DIR = _data_roots()

class ProcessingSettings(BaseModel):
    transcribe_model: str = "medium"
    transcribe_provider: str = "local"
    openai_model: str | None = None
    video_quality: str = "high quality"
    target_width: int | None = None
    target_height: int | None = None
    use_llm: bool = APP_SETTINGS.use_llm_by_default
    context_prompt: str = ""
    llm_model: str = APP_SETTINGS.llm_model
    llm_temperature: float = APP_SETTINGS.llm_temperature
    subtitle_position: int = 16  # 5-35 percentage from bottom
    max_subtitle_lines: int = 2
    subtitle_color: str | None = None
    shadow_strength: int = 4
    highlight_style: str = "karaoke"
    subtitle_size: int = 100  # 50-150 percentage scale
    karaoke_enabled: bool = True


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


def _parse_resolution(res_str: str | None) -> tuple[int | None, int | None]:
    """Parse resolution strings like '1080x1920' or '2160×3840'. Returns (None, None) if empty."""
    if not res_str:
        return None, None  # Skip scaling, keep original resolution
    cleaned = res_str.lower().replace("×", "x")
    parts = cleaned.split("x")
    if len(parts) != 2:
        return None, None  # Skip scaling on parse error
    try:
        w = int(parts[0])
        h = int(parts[1])
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return None, None  # Skip scaling on invalid dimensions

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

        last_update_time = 0.0
        last_check_time = 0.0

        def progress_callback(msg: str, percent: float):
            nonlocal last_update_time
            now = time.time()
            # Throttle DB updates to 1 per second to prevent SQLite contention
            if percent <= 0 or percent >= 100 or (now - last_update_time) >= 1.0:
                job_store.update_job(job_id, progress=int(percent), message=msg)
                last_update_time = now

        last_check_time = 0.0

        def check_cancelled():
            """Check if job was cancelled by user."""
            nonlocal last_check_time
            # Throttle DB checks to 2Hz to prevent SQLite contention during tight loops
            now = time.monotonic()
            if now - last_check_time < 0.5:
                return

            current_job = job_store.get_job(job_id)
            last_check_time = now
            if current_job and current_job.status == "cancelled":
                raise InterruptedError("Job cancelled by user")

        data_dir, _, _ = _data_roots()

        # Map settings to internal params
        # (Simplified logic from original app.py)
        model_size = settings.openai_model or settings.transcribe_model
        provider = settings.transcribe_provider or "local"
        crf_map = {"low size": 28, "balanced": 20, "high quality": 12}
        video_crf = crf_map.get(settings.video_quality.lower(), 12) # Default to high quality (12)
        target_width = settings.target_width  # None = keep original resolution
        target_height = settings.target_height  # None = keep original resolution

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
            transcribe_provider=provider,
            progress_callback=progress_callback,
            output_width=target_width,
            output_height=target_height,
            subtitle_position=settings.subtitle_position,
            max_subtitle_lines=settings.max_subtitle_lines,
            subtitle_color=settings.subtitle_color,
            shadow_strength=settings.shadow_strength,
            highlight_style=settings.highlight_style,
            subtitle_size=settings.subtitle_size,
            karaoke_enabled=settings.karaoke_enabled,
            check_cancelled=check_cancelled,
        )
        print(f"DEBUG_VIDEOS: normalize called with max_subtitle_lines={settings.max_subtitle_lines} color={settings.subtitle_color} shadow={settings.shadow_strength} style={settings.highlight_style}")

        # Result unpacking
        social = None
        final_path = output_path
        if isinstance(result, tuple):
            final_path, social = result
        else:
            final_path = result

        public_path = _relpath_safe(final_path, data_dir).as_posix()
        artifact_public = _relpath_safe(artifact_dir, data_dir).as_posix()

        result_data = {
            "video_path": str(final_path.relative_to(config.PROJECT_ROOT.parent)), # Relative to backend root for serving
            "artifacts_dir": str(artifact_dir.relative_to(config.PROJECT_ROOT.parent)),
            "public_url": f"/static/{public_path}",
            "artifact_url": f"/static/{artifact_public}",
            "social": social.tiktok.title if social else None, # Just storing title for simple view now
            "original_filename": original_name or input_path.name,
            "video_crf": video_crf,
            "model_size": model_size,
            "transcribe_provider": provider,
            "output_size": final_path.stat().st_size if final_path.exists() else 0,
            "resolution": f"{target_width}x{target_height}",
            # Persist styling settings for Export/Re-generation
            "max_subtitle_lines": settings.max_subtitle_lines,
            "subtitle_position": settings.subtitle_position,
            "subtitle_color": settings.subtitle_color,
            "shadow_strength": settings.shadow_strength,
            "highlight_style": settings.highlight_style,
            "subtitle_size": settings.subtitle_size,
            "karaoke_enabled": settings.karaoke_enabled,
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
                "provider": provider,
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


@router.post("/process", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
async def process_video(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    transcribe_model: str = Form("medium"),
    transcribe_provider: str = Form("local"),
    openai_model: str = Form(""),
    video_quality: str = Form("high quality"),
    video_resolution: str = Form(""),
    use_llm: bool = Form(APP_SETTINGS.use_llm_by_default),
    context_prompt: str = Form(""),
    subtitle_position: int = Form(16),
    max_subtitle_lines: int = Form(2),
    subtitle_color: str | None = Form(None),
    shadow_strength: int = Form(4),
    highlight_style: str = Form("karaoke"),
    subtitle_size: int = Form(100),
    karaoke_enabled: bool = Form(True),
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Upload a video and start processing."""
    # Security: Validate input lengths to prevent DoS
    if len(context_prompt) > 5000:
        raise HTTPException(400, "Context prompt too long (max 5000 chars)")
    if len(transcribe_model) > 50:
        raise HTTPException(400, "Model name too long")
    if len(video_quality) > 50:
        raise HTTPException(400, "Video quality string too long")
    if subtitle_color:
        if len(subtitle_color) > 20:
            raise HTTPException(400, "Subtitle color too long")
        # Validate ASS color format (&HAABBGGRR)
        if not re.match(r"^&H[0-9A-Fa-f]{8}$", subtitle_color):
            raise HTTPException(400, "Invalid subtitle color format (expected &HAABBGGRR)")

    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_root = _data_roots()

    # Save Upload
    file_ext = Path(file.filename).suffix
    if file_ext not in [".mp4", ".mov", ".mkv"]:
        raise HTTPException(400, "Invalid file type")

    input_path = uploads_dir / f"{job_id}_input{file_ext}"
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
    output_path = artifacts_root / job_id / "processed.mp4"
    artifact_path = artifacts_root / job_id

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
        "provider": transcribe_provider or "local",
        "video_quality": video_quality,
        "video_resolution": video_resolution,
        "use_llm": use_llm,
    },
    )

    # Enqueue Task
    target_width, target_height = _parse_resolution(video_resolution)
    settings = ProcessingSettings(
        transcribe_model=transcribe_model,
        transcribe_provider=transcribe_provider,
        openai_model=openai_model or None,
        video_quality=video_quality,
        target_width=target_width,
        target_height=target_height,
        use_llm=use_llm,
        context_prompt=context_prompt,
        subtitle_position=subtitle_position,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_color=subtitle_color,
        shadow_strength=shadow_strength,
        highlight_style=highlight_style,
        subtitle_size=subtitle_size,
        karaoke_enabled=karaoke_enabled,
    )
    print(f"DEBUG_API: Received process request max_lines={max_subtitle_lines} style={highlight_style}")

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

    # Trigger Cleanup
    from ...common.cleanup import cleanup_old_jobs
    background_tasks.add_task(
        cleanup_old_jobs,
        uploads_dir,
        artifacts_root,
        24 # 24 hours retention
    )

    return job

def _ensure_job_size(job):
    """Helper to backfill output_size for legacy jobs."""
    if job.status == "completed" and job.result_data:
        if not job.result_data.get("output_size"):
             video_path = job.result_data.get("video_path")
             if video_path:
                 try:
                     full_path = config.PROJECT_ROOT.parent / video_path
                     if full_path.exists():
                         # Update in-memory object (and potentially could save back, but for now just serving)
                         job.result_data["output_size"] = full_path.stat().st_size
                 except Exception:
                     pass
    return job

@router.get("/jobs", response_model=List[JobResponse])
def list_jobs(
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    jobs = job_store.list_jobs_for_user(current_user.id)
    return [_ensure_job_size(job) for job in jobs]


@router.get("/jobs/paginated", response_model=PaginatedJobsResponse)
def list_jobs_paginated(
    page: int = 1,
    page_size: int = 5,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    """List jobs with pagination support."""
    # Validate parameters
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if page_size > 100:
        page_size = 100  # Cap at 100 to prevent abuse

    offset = (page - 1) * page_size
    total = job_store.count_jobs_for_user(current_user.id)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    jobs = job_store.list_jobs_for_user_paginated(current_user.id, offset=offset, limit=page_size)
    items = [_ensure_job_size(job) for job in jobs]

    return PaginatedJobsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/jobs/batch-delete", response_model=BatchDeleteResponse)
def batch_delete_jobs(
    request: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Delete multiple jobs at once."""
    import shutil

    if not request.job_ids:
        return BatchDeleteResponse(status="success", deleted_count=0, job_ids=[])

    # Limit batch size to prevent abuse
    if len(request.job_ids) > 50:
        raise HTTPException(400, "Cannot delete more than 50 jobs at once")

    data_dir, uploads_dir, artifacts_root = _data_roots()
    deleted_ids = []

    # First verify ownership and delete files for each job
    for job_id in request.job_ids:
        job = job_store.get_job(job_id)
        if job and job.user_id == current_user.id:
            # Delete artifact directory
            artifact_dir = artifacts_root / job_id
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir, ignore_errors=True)

            # Delete input files
            for ext in [".mp4", ".mov", ".mkv"]:
                input_file = uploads_dir / f"{job_id}_input{ext}"
                if input_file.exists():
                    input_file.unlink(missing_ok=True)

            deleted_ids.append(job_id)

    # Batch delete from database
    deleted_count = job_store.delete_jobs(deleted_ids, current_user.id)

    # Record batch deletion in history
    if deleted_count > 0:
        _record_event_safe(
            history_store,
            current_user,
            "jobs_batch_deleted",
            f"Deleted {deleted_count} jobs",
            {"job_ids": deleted_ids, "count": deleted_count},
        )

    return BatchDeleteResponse(
        status="deleted",
        deleted_count=deleted_count,
        job_ids=deleted_ids
    )

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")
    return _ensure_job_size(job)


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Delete a job and its associated files."""
    import shutil

    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    # Delete associated files
    data_dir, uploads_dir, artifacts_root = _data_roots()

    # Delete artifact directory
    artifact_dir = artifacts_root / job_id
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir, ignore_errors=True)

    # Delete input files
    for ext in [".mp4", ".mov", ".mkv"]:
        input_file = uploads_dir / f"{job_id}_input{ext}"
        if input_file.exists():
            input_file.unlink(missing_ok=True)

    # Delete job from store
    job_store.delete_job(job_id)

    # Record deletion in history
    _record_event_safe(
        history_store,
        current_user,
        "job_deleted",
        f"Deleted job {job_id}",
        {"job_id": job_id},
    )

    return {"status": "deleted", "job_id": job_id}


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Cancel a processing job."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    # Only allow cancelling pending or processing jobs
    if job.status not in ("pending", "processing"):
        raise HTTPException(400, f"Cannot cancel job with status '{job.status}'")

    job_store.update_job(job_id, status="cancelled", message="Cancelled by user")

    _record_event_safe(
        history_store,
        current_user,
        "job_cancelled",
        f"Cancelled job {job_id}",
        {"job_id": job_id},
    )

    updated_job = job_store.get_job(job_id)
    return _ensure_job_size(updated_job)


@router.post("/jobs/{job_id}/viral-metadata", response_model=ViralMetadataResponse, dependencies=[Depends(limiter_content)])
def create_viral_metadata(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
):
    """Generate viral metadata for a completed job."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to generate metadata")

    _, _, artifacts_root = _data_roots()
    artifact_dir = artifacts_root / job_id
    transcript_path = artifact_dir / "transcript.txt"

    if not transcript_path.exists():
        raise HTTPException(404, "Transcript not found for this job")

    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
        metadata = generate_viral_metadata(transcript_text)

        return ViralMetadataResponse(
            hooks=metadata.hooks,
            caption_hook=metadata.caption_hook,
            caption_body=metadata.caption_body,
            cta=metadata.cta,
            hashtags=metadata.hashtags,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to generate metadata: {str(e)}")


class ExportRequest(BaseModel):
    resolution: str


@router.post("/jobs/{job_id}/export", response_model=JobResponse, dependencies=[Depends(limiter_content)])
def export_video(
    job_id: str,
    request: ExportRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
):
    """
    Export a video variant (e.g. 4K) from an existing job.
    """
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to export")

    data_dir, uploads_dir, artifacts_root = _data_roots()
    artifact_dir = artifacts_root / job_id

    # Locate original input
    input_video = None
    for ext in [".mp4", ".mov", ".mkv"]:
        candidate = uploads_dir / f"{job_id}_input{ext}"
        if candidate.exists():
            input_video = candidate
            break

    if not input_video:
        raise HTTPException(404, "Original input video not found")

    from ...services.video_processing import generate_video_variant

    try:
        # Note: This is synchronous/blocking for now as per MVP plan.
        # Ideally this should be a background task that updates job status.
        output_path = generate_video_variant(
            job_id,
            input_video,
            artifact_dir,
            request.resolution,
            job_store,
            current_user.id
        )

        # Update job result data with the new variant info
        # We can store variants in a dict in result_data
        result_data = job.result_data.copy() if job.result_data else {}
        variants = result_data.get("variants", {})

        public_path = _relpath_safe(output_path, data_dir).as_posix()
        variants[request.resolution] = f"/static/{public_path}"
        result_data["variants"] = variants

        # We assume the user might want this to be the 'main' video now?
        # Or just return the link.
        # Let's just update variants.

        job_store.update_job(job_id, result_data=result_data, status="completed", progress=100)

        # Reload job
        updated_job = job_store.get_job(job_id)
        return _ensure_job_size(updated_job)

    except Exception as e:
        raise HTTPException(500, f"Export failed: {str(e)}")


@router.post("/jobs/cleanup")
def run_retention_policy(
    days: int = 30,
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger retention policy: Delete jobs older than {days} days.
    Ideally protected by admin auth or run via CLI/Cron.
    """
    import os
    import shutil
    import time

    # Security: Only allow admins to trigger cleanup
    admin_emails_str = os.getenv("GSP_ADMIN_EMAILS", "")
    admin_emails = [e.strip().lower() for e in admin_emails_str.split(",") if e.strip()]

    if not admin_emails:
        # Secure default: If no admins are configured, disable the endpoint
        raise HTTPException(status_code=403, detail="Admin access not configured")

    if current_user.email.strip().lower() not in admin_emails:
        raise HTTPException(status_code=403, detail="Not authorized")

    cutoff = int(time.time()) - (days * 24 * 3600)
    old_jobs = job_store.list_jobs_created_before(cutoff)

    if not old_jobs:
        return {"status": "success", "deleted_count": 0, "message": "No old jobs found"}

    data_dir, uploads_dir, artifacts_root = _data_roots()
    deleted_ids = []

    for job in old_jobs:
        # Delete artifacts
        artifact_dir = artifacts_root / job.id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)

        # Delete inputs
        for ext in [".mp4", ".mov", ".mkv"]:
            input_file = uploads_dir / f"{job.id}_input{ext}"
            if input_file.exists():
                input_file.unlink(missing_ok=True)

        deleted_ids.append(job.id)

    # Delete from DB
    # Note: Using private method or list comprehension + delete_jobs if needed.
    # delete_jobs takes user_id for safety. Here we are system admin.
    # We'll use delete_job in loop or add delete_jobs_system to store.
    # Using existing delete_job works but it's one-by-one DB calls.
    # For efficiency we could act directly, but loop is fine for now.
    for job_id in deleted_ids:
        job_store.delete_job(job_id)

    return {
        "status": "success",
        "deleted_count": len(deleted_ids),
        "message": f"Deleted {len(deleted_ids)} jobs older than {days} days"
    }
