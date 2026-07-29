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

import base64
import binascii
import errno
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ...core.auth import User
from ...core.config import settings
from ...core.database import Database
from ...core.errors import sanitize_message
from ...core.gcs import get_gcs_settings
from ...core.ratelimit import limiter_processing
from ...schemas.base import JobResponse
from ...services import pricing
from ...services.charge_plans import reserve_processing_charges
from ...services.ffmpeg_utils import probe_media
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.usage_ledger import UsageLedgerStore
from ..deps import (
    get_current_user,
    get_db,
    get_history_store,
    get_job_store,
    get_usage_ledger_store,
)
from .file_utils import (
    MAX_UPLOAD_BYTES,
    data_roots,
    require_storage_capacity,
    save_request_stream_with_limit,
    save_upload_with_limit,
)
from .processing_tasks import (
    record_event_safe,
    refund_charge_best_effort,
    run_video_processing,
    upload_source_for_active_job,
)
from .settings import ProcessingSettings, build_processing_settings
from .validation import ALLOWED_VIDEO_EXTENSIONS, validate_upload_content_type

router = APIRouter()
logger = logging.getLogger(__name__)

# Include sub-routers
from .engine_routes import router as engine_router
from .export_routes import router as export_router
from .gcs_routes import router as gcs_router
from .intelligence_routes import router as intelligence_router
from .job_routes import router as job_router
from .reprocess_routes import router as reprocess_router

router.include_router(job_router)
router.include_router(engine_router)
router.include_router(gcs_router)
router.include_router(intelligence_router)
router.include_router(export_router)
router.include_router(reprocess_router)


# ==================== Main Processing Route ====================


MAX_STREAM_UPLOAD_METADATA_HEADER_CHARS = 12_000
MAX_STREAM_UPLOAD_METADATA_BYTES = 9_000


class StreamProcessMetadata(BaseModel):
    """Validated settings sent ahead of a raw streaming video body."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(..., min_length=1, max_length=255)
    transcribe_tier: str = Field(settings.default_transcribe_tier, max_length=50)
    transcribe_provider: str = Field(
        settings.transcribe_tier_provider[settings.default_transcribe_tier],
        max_length=50,
    )
    openai_model: str = Field("", max_length=50)
    video_quality: str = Field("high quality", max_length=50)
    video_resolution: str = Field("", max_length=50)
    use_llm: bool = settings.use_llm_by_default
    context_prompt: str = Field("", max_length=5000)
    subtitle_position: int = 16
    max_subtitle_lines: int = 2
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int = 4
    highlight_style: str = Field("karaoke", max_length=20)
    subtitle_size: int = 100
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


def _decode_stream_process_metadata(encoded: str | None) -> StreamProcessMetadata:
    if not encoded or len(encoded) > MAX_STREAM_UPLOAD_METADATA_HEADER_CHARS:
        raise HTTPException(status_code=400, detail="Invalid upload metadata")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_STREAM_UPLOAD_METADATA_BYTES:
            raise ValueError("metadata too large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("metadata must be an object")
        return StreamProcessMetadata.model_validate(payload)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid upload metadata") from exc


def _check_concurrent_job_capacity(job_store: JobStore, current_user: User) -> None:
    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= settings.max_concurrent_jobs:
        raise HTTPException(
            status_code=429,
            detail=(
                "Too many active jobs. Please wait for your current jobs to finish "
                f"(max {settings.max_concurrent_jobs})."
            ),
        )


def _parse_content_length(request: Request) -> int | None:
    content_length = request.headers.get("content-length")
    if not content_length:
        return None
    try:
        parsed = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
    if parsed <= 0:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header")
    if parsed > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Request too large; limit is {settings.max_upload_mb}MB",
        )
    return parsed


def _queue_saved_upload(
    *,
    background_tasks: BackgroundTasks,
    job_id: str,
    input_path: Path,
    artifacts_root: Path,
    filename: str,
    content_type: str,
    file_ext: str,
    video_resolution: str,
    proc_settings: ProcessingSettings,
    current_user: User,
    job_store: JobStore,
    history_store: HistoryStore,
    ledger_store: UsageLedgerStore,
    db: Database,
) -> JobResponse:
    """Validate a saved upload, reserve its charge, and enqueue processing."""
    try:
        probe = probe_media(input_path)
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        logger.warning("Failed to probe uploaded media; rejecting upload: %s", exc)
        raise HTTPException(status_code=400, detail="Could not validate uploaded media file")

    if probe.duration_s is None or probe.duration_s <= 0:
        input_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Could not determine video duration")

    if probe.duration_s > settings.max_video_duration_seconds:
        input_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Video too long (max {settings.max_video_duration_seconds / 60:.1f} minutes)",
        )

    job = job_store.create_job(job_id, current_user.id)

    try:
        llm_models = pricing.resolve_llm_models(proc_settings.transcribe_tier)
        charge_plan, new_balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=current_user.id,
            job_id=job_id,
            tier=proc_settings.transcribe_tier,
            duration_seconds=float(probe.duration_s),
            use_llm=proc_settings.use_llm,
            llm_model=llm_models.social,
            provider=proc_settings.transcribe_provider,
            stt_model=pricing.resolve_requested_transcribe_model(
                tier=proc_settings.transcribe_tier,
                provider=proc_settings.transcribe_provider,
                openai_model=proc_settings.openai_model,
            ),
        )
    except Exception:
        job_store.delete_job(job_id)
        input_path.unlink(missing_ok=True)
        raise

    output_path = artifacts_root / job_id / "processed.mp4"
    artifact_path = artifacts_root / job_id

    try:
        record_event_safe(
            history_store,
            current_user,
            "process_started",
            f"Queued {filename}",
            {
                "job_id": job_id,
                "transcribe_tier": proc_settings.transcribe_tier,
                "provider": proc_settings.transcribe_provider
                or settings.transcribe_tier_provider[settings.default_transcribe_tier],
                "video_quality": proc_settings.video_quality,
                "video_resolution": video_resolution,
                "use_llm": proc_settings.use_llm,
            },
        )

        gcs_settings = get_gcs_settings()
        source_gcs_object_name: str | None = None
        if gcs_settings:
            source_gcs_object_name = (
                f"{gcs_settings.uploads_prefix}/{current_user.id}/{job_id}{file_ext}"
            )

        processing_kwargs: dict[str, Any] = {}
        if source_gcs_object_name:
            processing_kwargs["source_gcs_object_name"] = source_gcs_object_name

        if gcs_settings and source_gcs_object_name:
            background_tasks.add_task(
                upload_source_for_active_job,
                job_id=job_id,
                job_store=job_store,
                gcs_settings=gcs_settings,
                object_name=source_gcs_object_name,
                source=input_path,
                content_type=content_type,
            )

        background_tasks.add_task(
            run_video_processing,
            job_id,
            input_path,
            output_path,
            artifact_path,
            proc_settings,
            job_store,
            history_store,
            current_user,
            filename,
            ledger_store=ledger_store,
            charge_plan=charge_plan,
            db=db,
            source_probe=probe,
            **processing_kwargs,
        )
    except Exception as exc:
        refund_charge_best_effort(
            ledger_store,
            charge_plan,
            status="failed",
            error=sanitize_message(str(exc)),
        )
        input_path.unlink(missing_ok=True)
        raise

    return JobResponse.model_validate(job).model_copy(update={"balance": new_balance})


@router.post("/process", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
async def process_video(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    transcribe_tier: str = Form(settings.default_transcribe_tier),
    transcribe_provider: str = Form(settings.transcribe_tier_provider[settings.default_transcribe_tier]),
    openai_model: str = Form(""),
    video_quality: str = Form("high quality"),
    video_resolution: str = Form(""),
    use_llm: bool = Form(settings.use_llm_by_default),
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
) -> JobResponse:
    """Upload a video and start processing."""
    proc_settings = build_processing_settings(
        transcribe_tier=transcribe_tier,
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
    _check_concurrent_job_capacity(job_store, current_user)

    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_root = data_roots()

    filename = file.filename or ""
    file_ext = Path(filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(400, "Invalid file type")

    input_path = uploads_dir / f"{job_id}_input{file_ext}"
    expected_upload_bytes = _parse_content_length(request) or MAX_UPLOAD_BYTES
    require_storage_capacity(
        data_dir,
        required_bytes=expected_upload_bytes * 2,
        db=db,
    )
    try:
        save_upload_with_limit(file, input_path)
    except OSError as exc:
        input_path.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise HTTPException(
                status_code=507,
                detail="Storage became temporarily unavailable. Please try again in a few minutes.",
            ) from exc
        raise

    return _queue_saved_upload(
        background_tasks=background_tasks,
        job_id=job_id,
        input_path=input_path,
        artifacts_root=artifacts_root,
        filename=filename,
        content_type=file.content_type or "application/octet-stream",
        file_ext=file_ext,
        video_resolution=video_resolution,
        proc_settings=proc_settings,
        current_user=current_user,
        job_store=job_store,
        history_store=history_store,
        ledger_store=ledger_store,
        db=db,
    )


@router.post(
    "/process-stream",
    response_model=JobResponse,
    dependencies=[Depends(limiter_processing)],
)
async def process_video_stream(
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
    db: Database = Depends(get_db),
) -> JobResponse:
    """Stream a raw video body directly into the processing workspace."""
    metadata = _decode_stream_process_metadata(
        request.headers.get("x-gsubs-upload-metadata"),
    )
    proc_settings = build_processing_settings(
        transcribe_tier=metadata.transcribe_tier,
        transcribe_provider=metadata.transcribe_provider,
        openai_model=metadata.openai_model,
        video_quality=metadata.video_quality,
        video_resolution=metadata.video_resolution,
        use_llm=metadata.use_llm,
        context_prompt=metadata.context_prompt,
        subtitle_position=metadata.subtitle_position,
        max_subtitle_lines=metadata.max_subtitle_lines,
        subtitle_color=metadata.subtitle_color,
        shadow_strength=metadata.shadow_strength,
        highlight_style=metadata.highlight_style,
        subtitle_size=metadata.subtitle_size,
        karaoke_enabled=metadata.karaoke_enabled,
        watermark_enabled=metadata.watermark_enabled,
    )
    _check_concurrent_job_capacity(job_store, current_user)

    filename = Path(metadata.filename.replace("\\", "/")).name
    file_ext = Path(filename).suffix.lower()
    if not filename or file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")
    content_type = validate_upload_content_type(
        request.headers.get("content-type", "").partition(";")[0],
    )

    expected_upload_bytes = _parse_content_length(request)
    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_root = data_roots()
    require_storage_capacity(
        data_dir,
        required_bytes=(expected_upload_bytes or MAX_UPLOAD_BYTES) * 2,
        db=db,
    )
    input_path = uploads_dir / f"{job_id}_input{file_ext}"
    try:
        await save_request_stream_with_limit(
            request,
            input_path,
            expected_size=expected_upload_bytes,
        )
    except OSError as exc:
        input_path.unlink(missing_ok=True)
        if exc.errno == errno.ENOSPC:
            raise HTTPException(
                status_code=507,
                detail="Storage became temporarily unavailable. Please try again in a few minutes.",
            ) from exc
        raise

    return _queue_saved_upload(
        background_tasks=background_tasks,
        job_id=job_id,
        input_path=input_path,
        artifacts_root=artifacts_root,
        filename=filename,
        content_type=content_type,
        file_ext=file_ext,
        video_resolution=metadata.video_resolution,
        proc_settings=proc_settings,
        current_user=current_user,
        job_store=job_store,
        history_store=history_store,
        ledger_store=ledger_store,
        db=db,
    )
