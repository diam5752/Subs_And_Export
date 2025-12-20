"""Video processing API endpoints.

This module provides the main route handlers for video processing.
Helper functions are extracted into separate modules for maintainability:
- validation.py: Input validation functions
- file_utils.py: File and directory utilities
- settings.py: ProcessingSettings model and builder
- processing_tasks.py: Background processing tasks
- job_routes.py: Job CRUD operations
- gcs_routes.py: GCS upload and processing
- intelligence_routes.py: Fact-check and social copy
- export_routes.py: Video and SRT exports
- reprocess_routes.py: Reprocess and admin routes
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile

from ...core import config
from ...core.auth import User
from ...core.database import Database
from ...core.errors import sanitize_message
from ...core.gcs import get_gcs_settings, upload_object
from ...core.ratelimit import limiter_processing
from ...core.settings import load_app_settings
from ...schemas.base import JobResponse
from ...services import pricing
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.charge_plans import reserve_processing_charges
from ...services.usage_ledger import UsageLedgerStore
from ...services.ffmpeg_utils import probe_media
from ...services.video_processing import generate_video_variant, normalize_and_stub_subtitles
from ..deps import (
    get_current_user,
    get_db,
    get_history_store,
    get_job_store,
    get_usage_ledger_store,
)
from .file_utils import (
    DATA_DIR,
    MAX_UPLOAD_BYTES,
    data_roots,
    link_or_copy_file,
    relpath_safe,
    save_upload_with_limit,
)
from .processing_tasks import (
    record_event_safe,
    refund_charge_best_effort,
    run_gcs_video_processing,
    run_video_processing,
)
from .settings import (
    ProcessingSettings,
    build_processing_settings,
    parse_resolution,
)

# Import from extracted modules
from .validation import (
    ALLOWED_VIDEO_EXTENSIONS,
    validate_highlight_style,
    validate_max_subtitle_lines,
    validate_shadow_strength,
    validate_subtitle_position,
    validate_subtitle_size,
    validate_upload_content_type,
)

# Re-export for backward compatibility
_data_roots = data_roots
_relpath_safe = relpath_safe
_link_or_copy_file = link_or_copy_file
_save_upload_with_limit = save_upload_with_limit
_build_processing_settings = build_processing_settings
_validate_subtitle_position = validate_subtitle_position
_validate_max_subtitle_lines = validate_max_subtitle_lines
_validate_shadow_strength = validate_shadow_strength
_validate_subtitle_size = validate_subtitle_size
_validate_highlight_style = validate_highlight_style
_validate_upload_content_type = validate_upload_content_type
_refund_charge_best_effort = refund_charge_best_effort
_record_event_safe = record_event_safe
_parse_resolution = parse_resolution


router = APIRouter()
logger = logging.getLogger(__name__)

# Include sub-routers
from .job_routes import router as job_router
from .gcs_routes import router as gcs_router
from .intelligence_routes import router as intelligence_router
from .export_routes import router as export_router
from .reprocess_routes import router as reprocess_router

router.include_router(job_router)
router.include_router(gcs_router)
router.include_router(intelligence_router)
router.include_router(export_router)
router.include_router(reprocess_router)

# Re-export models for backward compatibility with tests
from .job_routes import (
    TranscriptionWordRequest,
    TranscriptionCueRequest,
    UpdateTranscriptionRequest,
)
from .gcs_routes import GcsUploadUrlRequest, GcsUploadUrlResponse, GcsProcessRequest
from .export_routes import ExportRequest
from .reprocess_routes import ReprocessRequest

# Re-export GCS functions for backward compatibility with tests
from ...core.gcs import (
    generate_signed_upload_url,
    download_object,
)

# Re-export job-related functions that tests may patch
from .job_routes import (
    get_job,
    delete_job,
)

APP_SETTINGS = load_app_settings()


def _ensure_job_size(job):
    """Helper to backfill output_size for legacy jobs."""
    if job.status == "completed" and job.result_data:
        if not job.result_data.get("output_size"):
            video_path = job.result_data.get("video_path")
            if video_path:
                try:
                    full_path = DATA_DIR / video_path
                    if not full_path.exists():
                        full_path = config.PROJECT_ROOT.parent / video_path
                    if full_path.exists():
                        job.result_data["output_size"] = full_path.stat().st_size
                except Exception as e:
                    logger.warning(f"Failed to ensure job size: {e}")
    return job


# ==================== Main Processing Route ====================


@router.post("/process", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
async def process_video(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    transcribe_model: str = Form(config.DEFAULT_TRANSCRIBE_TIER),
    transcribe_provider: str = Form(config.TRANSCRIBE_TIER_PROVIDER[config.DEFAULT_TRANSCRIBE_TIER]),
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
    watermark_enabled: bool = Form(False),
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
    db: Database = Depends(get_db),
):
    """Upload a video and start processing."""
    settings = build_processing_settings(
        transcribe_model=transcribe_model,
        transcribe_provider=transcribe_provider,
        openai_model=openai_model,
        video_quality=video_quality,
        video_resolution=video_resolution,
        use_llm=use_llm,
        context_prompt=context_prompt,
        subtitle_position=subtitle_position,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_color=subtitle_color,
        shadow_strength=shadow_strength,
        highlight_style=highlight_style,
        subtitle_size=subtitle_size,
        karaoke_enabled=karaoke_enabled,
        watermark_enabled=watermark_enabled,
    )

    # Rate Limiting: Check concurrent jobs
    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many active jobs. Please wait for your current jobs to finish (max {config.MAX_CONCURRENT_JOBS})."
        )

    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_root = data_roots()

    # Save Upload
    filename = file.filename or ""
    file_ext = Path(filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
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
    save_upload_with_limit(file, input_path)

    # Validate Duration
    try:
        probe = probe_media(input_path)
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        logger.warning("Failed to probe uploaded media; rejecting upload: %s", exc)
        raise HTTPException(status_code=400, detail="Could not validate uploaded media file")

    if probe.duration_s is None or probe.duration_s <= 0:
        input_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Could not determine video duration")

    if probe.duration_s > config.MAX_VIDEO_DURATION_SECONDS:
        input_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Video too long (max {config.MAX_VIDEO_DURATION_SECONDS/60:.1f} minutes)",
        )

    job = job_store.create_job(job_id, current_user.id)

    try:
        llm_models = pricing.resolve_llm_models(settings.transcribe_model)
        charge_plan, new_balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=current_user.id,
            job_id=job_id,
            tier=settings.transcribe_model,
            duration_seconds=float(probe.duration_s),
            use_llm=use_llm,
            llm_model=llm_models.social,
            provider=settings.transcribe_provider,
            stt_model=pricing.resolve_transcribe_model(settings.transcribe_model),
        )
    except Exception:
        job_store.delete_job(job_id)
        input_path.unlink(missing_ok=True)
        raise

    # Prepare Output
    output_path = artifacts_root / job_id / "processed.mp4"
    artifact_path = artifacts_root / job_id

    try:
        record_event_safe(
            history_store,
            current_user,
            "process_started",
            f"Queued {file.filename}",
            {
                "job_id": job_id,
                "model_size": settings.transcribe_model,
                "provider": settings.transcribe_provider or config.TRANSCRIBE_TIER_PROVIDER[config.DEFAULT_TRANSCRIBE_TIER],
                "video_quality": settings.video_quality,
                "video_resolution": video_resolution,
                "use_llm": use_llm,
            },
        )

        gcs_settings = get_gcs_settings()
        source_gcs_object_name: str | None = None
        if gcs_settings:
            source_gcs_object_name = f"{gcs_settings.uploads_prefix}/{current_user.id}/{job_id}{file_ext}"

        processing_kwargs: dict[str, Any] = {}
        if source_gcs_object_name:
            processing_kwargs["source_gcs_object_name"] = source_gcs_object_name

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
            ledger_store=ledger_store,
            charge_plan=charge_plan,
            db=db,
            **processing_kwargs,
        )

        if gcs_settings and source_gcs_object_name:
            background_tasks.add_task(
                upload_object,
                settings=gcs_settings,
                object_name=source_gcs_object_name,
                source=input_path,
                content_type=file.content_type or "application/octet-stream",
            )

        from ...core.cleanup import cleanup_old_uploads
        background_tasks.add_task(cleanup_old_uploads, uploads_dir, 24)
    except Exception as exc:
        refund_charge_best_effort(ledger_store, charge_plan, status="failed", error=sanitize_message(str(exc)))
        input_path.unlink(missing_ok=True)
        raise

    return {**job.__dict__, "balance": new_balance}
