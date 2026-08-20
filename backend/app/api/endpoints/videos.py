"""Video processing API endpoints.

This module provides the main route handlers for video processing.
Helper functions are extracted into separate modules for maintainability:
- validation.py: Input validation functions
- file_utils.py: File and directory utilities
- settings.py: ProcessingSettings model and builder
- processing_tasks.py: Background processing tasks
- job_routes.py: Job CRUD operations
- intelligence_routes.py: Fact-check and social copy
- export_routes.py: Video and SRT exports
- reprocess_routes.py: Reprocess routes
"""

from __future__ import annotations

import base64
import binascii
import errno
import json
import logging
import math
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...core.auth import User
from ...core.config import settings
from ...core.database import Database
from ...core.erasure_journal import TombstoneKind, configured_erasure_journal
from ...core.errors import ProcessingQuoteChangedError, sanitize_message
from ...core.ratelimit import limiter_processing
from ...core.workspace_deletion import (
    UPLOAD_SUFFIXES,
    delete_job_workspace,
    lock_job_workspace,
)
from ...core.workspace_ownership import (
    record_workspace_ownership,
    remove_workspace_ownership_after_verified_cleanup,
)
from ...schemas.base import JobResponse
from ...services import pricing
from ...services.charge_plans import (
    preflight_processing_charges,
    preflight_processing_provider_budget,
    reserve_processing_charges,
)
from ...services.ffmpeg_utils import probe_media
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.usage_ledger import UsageLedgerStore
from ..deps import (
    get_current_user_with_media_lifecycle,
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
)
from .processing_tasks import (
    record_event_safe,
    refund_charge_best_effort,
    run_video_processing,
)
from .settings import ProcessingSettings, build_processing_settings
from .validation import (
    ALLOWED_VIDEO_EXTENSIONS,
    assert_processing_quote_authorized,
    validate_authorized_credits,
    validate_upload_content_type,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Include sub-routers
from .engine_routes import router as engine_router
from .export_routes import router as export_router
from .intelligence_routes import router as intelligence_router
from .job_routes import router as job_router
from .reprocess_routes import router as reprocess_router

router.include_router(job_router)
router.include_router(engine_router)
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
    authorized_credits: int = Field(..., strict=True)
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

    @field_validator("authorized_credits")
    @classmethod
    def authorized_credits_must_be_canonical(cls, value: int) -> int:
        return validate_authorized_credits(value)


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


def _record_and_delete_rejected_upload(
    *,
    job_id: str,
    user_id: str,
    input_path: Path,
    artifacts_root: Path,
    kind: TombstoneKind,
    job_store: JobStore | None = None,
) -> None:
    """Delete rejected media, retaining intent only when cleanup is uncertain."""
    if kind == "workspace":
        try:
            with lock_job_workspace(
                data_dir=artifacts_root.parent,
                job_id=job_id,
            ):
                delete_job_workspace(
                    job_id=job_id,
                    uploads_dir=input_path.parent,
                    artifacts_dir=artifacts_root,
                    expected_user_id=user_id,
                )
                artifact_path = artifacts_root / job_id
                expected_stem = f"{job_id}_input"
                upload_remains = input_path.exists() or input_path.is_symlink()
                if input_path.parent.exists():
                    upload_remains = upload_remains or any(
                        item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES
                        for item in input_path.parent.iterdir()
                    )
                artifact_remains = artifact_path.exists() or artifact_path.is_symlink()
                if upload_remains or artifact_remains:
                    raise RuntimeError("Rejected upload cleanup could not be verified")
                remove_workspace_ownership_after_verified_cleanup(
                    data_dir=artifacts_root.parent,
                    job_id=job_id,
                    expected_user_id=user_id,
                )
        except Exception:
            # The workspace has no database row yet. A durable retry is needed
            # only when exact synchronous deletion failed or was ambiguous.
            configured_erasure_journal().append(
                kind=kind,
                user_id=user_id,
                job_ids=[job_id],
            )
            raise
        return

    # Once a job row may exist, record restore-safe intent before deleting
    # either filesystem or database state.
    with lock_job_workspace(data_dir=artifacts_root.parent, job_id=job_id):
        configured_erasure_journal().append(
            kind=kind,
            user_id=user_id,
            job_ids=[job_id],
        )
        delete_job_workspace(
            job_id=job_id,
            uploads_dir=input_path.parent,
            artifacts_dir=artifacts_root,
            expected_user_id=user_id,
        )
        if kind == "job":
            if job_store is None:
                raise RuntimeError("Job cleanup requires a job store")
            job_store.delete_job(job_id)
        artifact_path = artifacts_root / job_id
        expected_stem = f"{job_id}_input"
        upload_remains = input_path.exists() or input_path.is_symlink()
        if input_path.parent.exists():
            upload_remains = upload_remains or any(
                item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES
                for item in input_path.parent.iterdir()
            )
        artifact_remains = artifact_path.exists() or artifact_path.is_symlink()
        if upload_remains or artifact_remains:
            raise RuntimeError("Rejected upload cleanup could not be verified")
        remove_workspace_ownership_after_verified_cleanup(
            data_dir=artifacts_root.parent,
            job_id=job_id,
            expected_user_id=user_id,
        )


def _queue_saved_upload(
    *,
    background_tasks: BackgroundTasks,
    job_id: str,
    input_path: Path,
    artifacts_root: Path,
    filename: str,
    video_resolution: str,
    authorized_credits: int,
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
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )
        logger.warning("Failed to probe uploaded media; rejecting upload: %s", exc)
        raise HTTPException(status_code=400, detail="Could not validate uploaded media file")

    if (
        probe.duration_s is None
        or not math.isfinite(probe.duration_s)
        or probe.duration_s <= 0
    ):
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )
        raise HTTPException(status_code=400, detail="Could not determine video duration")

    if probe.duration_s > settings.max_video_duration_seconds:
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )
        raise HTTPException(
            status_code=400,
            detail=f"Video too long (max {settings.max_video_duration_seconds / 60:.1f} minutes)",
        )

    try:
        assert_processing_quote_authorized(
            duration_seconds=float(probe.duration_s),
            authorized_credits=authorized_credits,
        )
    except ProcessingQuoteChangedError:
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )
        raise

    try:
        llm_models = pricing.resolve_llm_models(proc_settings.transcribe_tier)
        stt_model = pricing.resolve_requested_transcribe_model(
            tier=proc_settings.transcribe_tier,
            provider=proc_settings.transcribe_provider,
            openai_model=proc_settings.openai_model,
        )
        preflight_processing_charges(
            ledger_store=ledger_store,
            user_id=current_user.id,
            tier=proc_settings.transcribe_tier,
            duration_seconds=float(probe.duration_s),
            use_llm=proc_settings.use_llm,
            llm_model=llm_models.social,
            provider=proc_settings.transcribe_provider,
            stt_model=stt_model,
        )
    except Exception:
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )
        raise

    try:
        job = job_store.create_job(job_id, current_user.id)
    except Exception:
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            # The database transaction may have committed before a connection
            # or session-close error reached this caller. Use the conservative
            # job tombstone and an idempotent exact row delete.
            kind="job",
            job_store=job_store,
        )
        raise

    try:
        charge_plan, new_balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=current_user.id,
            job_id=job_id,
            tier=proc_settings.transcribe_tier,
            duration_seconds=float(probe.duration_s),
            use_llm=proc_settings.use_llm,
            llm_model=llm_models.social,
            provider=proc_settings.transcribe_provider,
            stt_model=stt_model,
        )
    except Exception:
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="job",
            job_store=job_store,
        )
        raise

    output_path = artifacts_root / job_id / "processed.mp4"
    artifact_path = artifacts_root / job_id

    try:
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
        )
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
    except Exception as exc:
        refund_charge_best_effort(
            ledger_store,
            charge_plan,
            status="failed",
            error=sanitize_message(str(exc)),
        )
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="job",
            job_store=job_store,
        )
        raise

    return JobResponse.model_validate(job).model_copy(update={"balance": new_balance})


@router.post(
    "/process-stream",
    response_model=JobResponse,
    dependencies=[Depends(limiter_processing)],
)
async def process_video_stream(
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user_with_media_lifecycle),
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
    validate_upload_content_type(
        request.headers.get("content-type", "").partition(";")[0],
    )

    expected_upload_bytes = _parse_content_length(request)
    llm_models = pricing.resolve_llm_models(proc_settings.transcribe_tier)
    stt_model = pricing.resolve_requested_transcribe_model(
        tier=proc_settings.transcribe_tier,
        provider=proc_settings.transcribe_provider,
        openai_model=proc_settings.openai_model,
    )
    preflight_processing_provider_budget(
        ledger_store=ledger_store,
        tier=proc_settings.transcribe_tier,
        duration_seconds=float(settings.max_video_duration_seconds),
        use_llm=proc_settings.use_llm,
        llm_model=llm_models.social,
        provider=proc_settings.transcribe_provider,
        stt_model=stt_model,
    )
    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_root = data_roots()
    require_storage_capacity(
        data_dir,
        required_bytes=(expected_upload_bytes or MAX_UPLOAD_BYTES) * 2,
        db=db,
    )
    input_path = uploads_dir / f"{job_id}_input{file_ext}"
    try:
        with lock_job_workspace(data_dir=data_dir, job_id=job_id):
            record_workspace_ownership(
                data_dir=data_dir,
                job_id=job_id,
                user_id=current_user.id,
            )
            await save_request_stream_with_limit(
                request,
                input_path,
                expected_size=expected_upload_bytes,
                cleanup_on_error=False,
            )
    except BaseException as exc:
        _record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )
        if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
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
        video_resolution=metadata.video_resolution,
        authorized_credits=metadata.authorized_credits,
        proc_settings=proc_settings,
        current_user=current_user,
        job_store=job_store,
        history_store=history_store,
        ledger_store=ledger_store,
        db=db,
    )
