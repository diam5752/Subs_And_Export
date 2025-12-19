"""GCS upload and processing routes."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core import config
from ...core.auth import User
from ...core.errors import sanitize_message
from ...core.gcs import generate_signed_upload_url, get_gcs_settings
from ...core.gcs_uploads import GcsUploadStore
from ...core.ratelimit import limiter_processing
from ...core.settings import load_app_settings
from ...schemas.base import JobResponse
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.points import PointsStore, process_video_cost
from ..deps import get_current_user, get_gcs_upload_store, get_history_store, get_job_store, get_points_store
from .file_utils import MAX_UPLOAD_BYTES, data_roots
from .processing_tasks import ChargeContext, record_event_safe, refund_charge_best_effort, run_gcs_video_processing
from .settings import build_processing_settings
from .validation import ALLOWED_VIDEO_EXTENSIONS, validate_upload_content_type


logger = logging.getLogger(__name__)
router = APIRouter()

APP_SETTINGS = load_app_settings()


class GcsUploadUrlRequest(BaseModel):
    filename: str = Field(..., max_length=255)
    content_type: str = Field(..., max_length=100)
    size_bytes: int = Field(..., ge=1)


class GcsUploadUrlResponse(BaseModel):
    upload_id: str
    object_name: str
    upload_url: str
    expires_at: int
    required_headers: dict[str, str]


@router.post("/gcs/upload-url", response_model=GcsUploadUrlResponse, dependencies=[Depends(limiter_processing)])
def create_gcs_upload_url(
    payload: GcsUploadUrlRequest,
    current_user: User = Depends(get_current_user),
    gcs_upload_store: GcsUploadStore = Depends(get_gcs_upload_store),
    history_store: HistoryStore = Depends(get_history_store),
) -> Any:
    """Create a signed upload URL for direct-to-GCS uploads."""
    gcs_settings = get_gcs_settings()
    if not gcs_settings:
        raise HTTPException(status_code=503, detail="GCS uploads are not configured")

    file_ext = Path(payload.filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if payload.size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large; limit is {APP_SETTINGS.max_upload_mb}MB")

    content_type = validate_upload_content_type(payload.content_type)

    object_name = f"{gcs_settings.uploads_prefix}/{current_user.id}/{uuid.uuid4().hex}{file_ext}"
    session = gcs_upload_store.issue_upload(
        user_id=current_user.id,
        object_name=object_name,
        content_type=content_type,
        original_filename=payload.filename,
        ttl_seconds=gcs_settings.upload_url_ttl_seconds,
    )

    try:
        upload_url = generate_signed_upload_url(
            settings=gcs_settings,
            object_name=object_name,
            content_type=content_type,
            content_length=payload.size_bytes,
        )
    except Exception as exc:
        logger.warning("Failed to generate GCS signed upload URL: %s", exc)
        raise HTTPException(status_code=503, detail="Could not generate signed upload URL")

    record_event_safe(
        history_store, current_user, "gcs_upload_url_issued",
        f"Issued GCS upload URL for {payload.filename}",
        {"object_name": object_name, "content_type": content_type, "size_bytes": payload.size_bytes},
    )

    return {
        "upload_id": session.id,
        "object_name": object_name,
        "upload_url": upload_url,
        "expires_at": session.expires_at,
        "required_headers": {"Content-Type": content_type, "Content-Length": str(payload.size_bytes)},
    }


class GcsProcessRequest(BaseModel):
    upload_id: str = Field(..., max_length=128)
    transcribe_model: str = Field("medium", max_length=50)
    transcribe_provider: str = Field("local", max_length=50)
    openai_model: str = Field("", max_length=50)
    video_quality: str = Field("high quality", max_length=50)
    video_resolution: str = Field("", max_length=50)
    use_llm: bool = APP_SETTINGS.use_llm_by_default
    context_prompt: str = Field("", max_length=5000)
    subtitle_position: int = 16
    max_subtitle_lines: int = 2
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int = 4
    highlight_style: str = Field("karaoke", max_length=20)
    subtitle_size: int = 100
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


@router.post("/gcs/process", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
def process_video_from_gcs(
    payload: GcsProcessRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    gcs_upload_store: GcsUploadStore = Depends(get_gcs_upload_store),
    points_store: PointsStore = Depends(get_points_store),
) -> Any:
    """Start processing for an already-uploaded GCS object."""
    gcs_settings = get_gcs_settings()
    if not gcs_settings:
        raise HTTPException(status_code=503, detail="GCS uploads are not configured")

    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many active jobs. Please wait for your current jobs to finish (max {config.MAX_CONCURRENT_JOBS}).",
        )

    session = gcs_upload_store.consume_upload(upload_id=payload.upload_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload not found or expired")

    settings = build_processing_settings(
        transcribe_model=payload.transcribe_model,
        transcribe_provider=payload.transcribe_provider,
        openai_model=payload.openai_model,
        video_quality=payload.video_quality,
        video_resolution=payload.video_resolution,
        use_llm=payload.use_llm,
        context_prompt=payload.context_prompt,
        subtitle_position=payload.subtitle_position,
        max_subtitle_lines=payload.max_subtitle_lines,
        subtitle_color=payload.subtitle_color,
        shadow_strength=payload.shadow_strength,
        highlight_style=payload.highlight_style,
        subtitle_size=payload.subtitle_size,
        karaoke_enabled=payload.karaoke_enabled,
        watermark_enabled=payload.watermark_enabled,
    )

    job_id = str(uuid.uuid4())
    _, uploads_dir, artifacts_root = data_roots()

    file_ext = Path(session.original_filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid original filename extension")

    input_path = uploads_dir / f"{job_id}_input{file_ext}"
    output_path = artifacts_root / job_id / "processed.mp4"
    artifact_path = artifacts_root / job_id

    cost = process_video_cost(settings.transcribe_model)
    charge = ChargeContext(
        user_id=current_user.id,
        cost=cost,
        reason="process_video",
        meta={"charge_id": job_id, "job_id": job_id, "model": settings.transcribe_model, "source": "gcs"},
    )
    new_balance = points_store.spend(current_user.id, cost, reason=charge.reason, meta=charge.meta)

    try:
        job = job_store.create_job(job_id, current_user.id)
        record_event_safe(
            history_store, current_user, "process_started",
            f"Queued {session.original_filename}",
            {"job_id": job_id, "provider": settings.transcribe_provider, "model_size": settings.transcribe_model, "video_quality": settings.video_quality, "source": "gcs"},
        )

        background_tasks.add_task(
            run_gcs_video_processing,
            job_id=job_id,
            gcs_object_name=session.object_name,
            input_path=input_path,
            output_path=output_path,
            artifact_dir=artifact_path,
            settings=settings,
            job_store=job_store,
            history_store=history_store,
            user=current_user,
            original_name=session.original_filename,
            points_store=points_store,
            charge=charge,
        )

        from ...common.cleanup import cleanup_old_uploads
        background_tasks.add_task(cleanup_old_uploads, uploads_dir, 24)
    except Exception as exc:
        refund_charge_best_effort(points_store, charge, status="failed", error=sanitize_message(str(exc)))
        raise

    return {**job.__dict__, "balance": new_balance}
