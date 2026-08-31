"""Video processing API endpoints.

This module provides the main route handlers for video processing.
Helper functions are extracted into separate modules for maintainability:
- validation.py: Input validation functions
- file_utils.py: File and directory utilities
- settings.py: ProcessingSettings model and builder
- processing_tasks.py: Background processing tasks
- job_routes.py: Job CRUD operations
- export_routes.py: Video and SRT exports
- reprocess_routes.py: Reprocess routes
"""

from __future__ import annotations

import errno
import logging
import uuid
from pathlib import Path
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ...core.auth import User
from ...core.config import settings as settings
from ...core.database import Database
from ...core.erasure_journal import TombstoneKind, configured_erasure_journal
from ...core.errors import sanitize_message
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
from ...services.ffmpeg_utils import MediaProbe, probe_media
from ...services.history import HistoryStore
from ...services.jobs import Job, JobStore
from ...services.usage_ledger import ChargePlan, UsageLedgerStore
from ..deps import (
    get_current_user_with_media_lifecycle,
    get_db,
    get_history_store,
    get_job_store,
    get_usage_ledger_store,
    media_job_admission,
)
from .file_utils import (
    MAX_UPLOAD_BYTES,
    UPLOAD_STORAGE_RESERVATION_KEY,
    data_roots,
    require_storage_capacity,
    save_request_stream_with_limit,
    upload_storage_reservation_bytes,
)
from .processing_tasks import (
    record_event_safe,
    refund_charge_best_effort,
    run_video_processing,
)
from .saved_upload_queue import SavedUploadContext as _SavedUploadContext
from .saved_upload_queue import (
    authorize_saved_upload_quote,
    preflight_saved_upload,
    saved_upload_duration_error,
    schedule_saved_upload,
)
from .saved_upload_queue import validate_pre_reserved_state as _validate_pre_reserved_state
from .settings import ProcessingSettings, build_processing_settings
from .stream_upload_contract import authorized_video_quote as _authorized_video_quote
from .stream_upload_contract import (
    check_concurrent_job_capacity as _check_concurrent_job_capacity,
)
from .stream_upload_contract import (
    decode_stream_process_metadata as _decode_stream_process_metadata,
)
from .stream_upload_contract import parse_content_length as _parse_content_length_contract
from .validation import (
    ALLOWED_VIDEO_EXTENSIONS,
    assert_processing_quote_authorized,
    validate_upload_content_type,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Include sub-routers
from .engine_routes import router as engine_router
from .export_routes import router as export_router
from .job_routes import router as job_router
from .reprocess_routes import router as reprocess_router

router.include_router(job_router)
router.include_router(engine_router)
router.include_router(export_router)
router.include_router(reprocess_router)


def _parse_content_length(request: Request) -> int | None:
    """Preserve the endpoint's patchable upload limit contract."""
    return _parse_content_length_contract(
        request,
        max_upload_bytes=MAX_UPLOAD_BYTES,
    )


# ==================== Main Processing Route ====================


def _rejected_workspace_remains(
    *,
    job_id: str,
    input_path: Path,
    artifacts_root: Path,
) -> bool:
    expected_stem = f"{job_id}_input"
    upload_remains = input_path.exists() or input_path.is_symlink()
    if input_path.parent.exists():
        upload_remains = upload_remains or any(
            item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES
            for item in input_path.parent.iterdir()
        )
    artifact_path = artifacts_root / job_id
    return upload_remains or artifact_path.exists() or artifact_path.is_symlink()


def _delete_rejected_workspace_locked(
    *,
    job_id: str,
    user_id: str,
    input_path: Path,
    artifacts_root: Path,
    kind: TombstoneKind,
    job_store: JobStore | None,
) -> None:
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
    if _rejected_workspace_remains(
        job_id=job_id,
        input_path=input_path,
        artifacts_root=artifacts_root,
    ):
        raise RuntimeError("Rejected upload cleanup could not be verified")
    remove_workspace_ownership_after_verified_cleanup(
        data_dir=artifacts_root.parent,
        job_id=job_id,
        expected_user_id=user_id,
    )


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
                _delete_rejected_workspace_locked(
                    job_id=job_id,
                    user_id=user_id,
                    input_path=input_path,
                    artifacts_root=artifacts_root,
                    kind=kind,
                    job_store=job_store,
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
        _delete_rejected_workspace_locked(
            job_id=job_id,
            user_id=user_id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind=kind,
            job_store=job_store,
        )


def _cleanup_saved_upload_failure(
    *,
    job_id: str,
    current_user: User,
    input_path: Path,
    artifacts_root: Path,
    job_store: JobStore,
    ledger_store: UsageLedgerStore,
    charge_plan: ChargePlan | None,
    job_created: bool,
    error: str,
) -> None:
    """Refund a provisional reservation, then remove its exact workspace."""
    if charge_plan is not None:
        refund_charge_best_effort(
            ledger_store,
            charge_plan,
            status="failed",
            error=sanitize_message(error),
        )
    _record_and_delete_rejected_upload(
        job_id=job_id,
        user_id=current_user.id,
        input_path=input_path,
        artifacts_root=artifacts_root,
        kind="job" if job_created else "workspace",
        job_store=job_store if job_created else None,
    )


def _reject_saved_upload(
    context: _SavedUploadContext,
    *,
    charge_plan: ChargePlan | None,
    job_created: bool,
    error: str,
) -> None:
    _cleanup_saved_upload_failure(
        job_id=context.job_id,
        current_user=context.current_user,
        input_path=context.input_path,
        artifacts_root=context.artifacts_root,
        job_store=context.job_store,
        ledger_store=context.ledger_store,
        charge_plan=charge_plan,
        job_created=job_created,
        error=error,
    )


def _probe_saved_upload(
    context: _SavedUploadContext,
    *,
    charge_plan: ChargePlan | None,
    job_created: bool,
) -> MediaProbe:
    probe = _load_saved_upload_probe(context, charge_plan=charge_plan, job_created=job_created)
    detail = saved_upload_duration_error(probe)
    if detail is not None:
        _reject_saved_upload(context, charge_plan=charge_plan, job_created=job_created, error=detail)
        raise HTTPException(status_code=400, detail=detail)
    authorize_saved_upload_quote(
        context,
        probe=probe,
        charge_plan=charge_plan,
        job_created=job_created,
        assert_quote=assert_processing_quote_authorized,
        reject_saved=_reject_saved_upload,
    )
    return probe


def _load_saved_upload_probe(
    context: _SavedUploadContext,
    *,
    charge_plan: ChargePlan | None,
    job_created: bool,
) -> MediaProbe:
    try:
        return probe_media(context.input_path)
    except Exception as exc:
        detail = "Could not validate uploaded media file"
        _reject_saved_upload(context, charge_plan=charge_plan, job_created=job_created, error=detail)
        logger.warning("Failed to probe uploaded media; rejecting upload: %s", exc)
        raise HTTPException(status_code=400, detail=detail)


def _create_and_charge_upload(
    context: _SavedUploadContext,
    *,
    probe: MediaProbe,
    stt_model: str,
) -> tuple[Job, ChargePlan, int]:
    duration = float(cast(float, probe.duration_s))
    preflight_saved_upload(
        context,
        duration=duration,
        stt_model=stt_model,
        preflight_charges=preflight_processing_charges,
        reject_saved=_reject_saved_upload,
    )
    job = _create_saved_upload_job(context)
    charge_plan, new_balance = _reserve_saved_upload_charge(
        context,
        duration=duration,
        stt_model=stt_model,
    )
    return job, charge_plan, new_balance


def _create_saved_upload_job(context: _SavedUploadContext) -> Job:
    try:
        return context.job_store.create_job(
            context.job_id,
            context.current_user.id,
        )
    except Exception:
        _record_and_delete_rejected_upload(
            job_id=context.job_id,
            user_id=context.current_user.id,
            input_path=context.input_path,
            artifacts_root=context.artifacts_root,
            kind="job",
            job_store=context.job_store,
        )
        raise


def _reserve_saved_upload_charge(
    context: _SavedUploadContext,
    *,
    duration: float,
    stt_model: str,
) -> tuple[ChargePlan, int]:
    try:
        return reserve_processing_charges(
            ledger_store=context.ledger_store,
            user_id=context.current_user.id,
            job_id=context.job_id,
            tier=context.proc_settings.transcribe_tier,
            duration_seconds=duration,
            provider=context.proc_settings.transcribe_provider,
            stt_model=stt_model,
        )
    except Exception:
        _record_and_delete_rejected_upload(
            job_id=context.job_id,
            user_id=context.current_user.id,
            input_path=context.input_path,
            artifacts_root=context.artifacts_root,
            kind="job",
            job_store=context.job_store,
        )
        raise


def _resolve_saved_upload_charge(
    context: _SavedUploadContext,
    *,
    probe: MediaProbe,
    pre_created_job: Job | None,
    pre_reserved_charge_plan: ChargePlan | None,
    pre_reserved_balance: int | None,
) -> tuple[Job, ChargePlan, int]:
    _validate_pre_reserved_state(
        pre_created_job,
        pre_reserved_charge_plan,
        pre_reserved_balance,
    )
    stt_model = pricing.resolve_requested_transcribe_model(
        tier=context.proc_settings.transcribe_tier,
        provider=context.proc_settings.transcribe_provider,
        openai_model=context.proc_settings.openai_model,
    )
    if pre_created_job is not None:
        assert pre_reserved_charge_plan is not None
        assert pre_reserved_balance is not None
        return (
            pre_created_job,
            pre_reserved_charge_plan,
            pre_reserved_balance,
        )
    return _create_and_charge_upload(
        context,
        probe=probe,
        stt_model=stt_model,
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
    pre_created_job: Job | None = None,
    pre_reserved_charge_plan: ChargePlan | None = None,
    pre_reserved_balance: int | None = None,
) -> JobResponse:
    """Validate a saved upload and enqueue it with one durable charge."""
    _validate_pre_reserved_state(
        pre_created_job,
        pre_reserved_charge_plan,
        pre_reserved_balance,
    )
    context = _SavedUploadContext(
        background_tasks=background_tasks,
        job_id=job_id,
        input_path=input_path,
        artifacts_root=artifacts_root,
        filename=filename,
        video_resolution=video_resolution,
        authorized_credits=authorized_credits,
        proc_settings=proc_settings,
        current_user=current_user,
        job_store=job_store,
        history_store=history_store,
        ledger_store=ledger_store,
    )
    probe = _probe_saved_upload(
        context,
        charge_plan=pre_reserved_charge_plan,
        job_created=pre_created_job is not None,
    )
    job, charge_plan, new_balance = _resolve_saved_upload_charge(
        context,
        probe=probe,
        pre_created_job=pre_created_job,
        pre_reserved_charge_plan=pre_reserved_charge_plan,
        pre_reserved_balance=pre_reserved_balance,
    )
    schedule_saved_upload(
        context,
        job=job,
        charge_plan=charge_plan,
        probe=probe,
        run_processing=run_video_processing,
        record_event=record_event_safe,
        refund_charge=refund_charge_best_effort,
        cleanup_rejected=_record_and_delete_rejected_upload,
    )
    return JobResponse.model_validate(job).model_copy(update={"balance": new_balance})


def _reserve_stream_upload(
    *,
    job_id: str,
    current_user: User,
    job_store: JobStore,
    ledger_store: UsageLedgerStore,
    db: Database,
    data_dir: Path,
    input_path: Path,
    artifacts_root: Path,
    expected_upload_bytes: int | None,
    proc_settings: ProcessingSettings,
    authorized_quote: pricing.VideoCreditQuote,
    stt_model: str,
) -> tuple[Job, ChargePlan, int]:
    """Create and charge one pending upload under the short admission lock."""
    with media_job_admission(db):
        _check_concurrent_job_capacity(job_store, current_user)
        storage_reservation_bytes = upload_storage_reservation_bytes(
            expected_upload_bytes,
        )
        require_storage_capacity(
            data_dir,
            required_bytes=storage_reservation_bytes,
            db=db,
        )
        with lock_job_workspace(data_dir=data_dir, job_id=job_id):
            record_workspace_ownership(
                data_dir=data_dir,
                job_id=job_id,
                user_id=current_user.id,
            )

        try:
            job = job_store.create_job(
                job_id,
                current_user.id,
                result_data={
                    UPLOAD_STORAGE_RESERVATION_KEY: storage_reservation_bytes,
                },
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

        try:
            charge_plan, reserved_balance = reserve_processing_charges(
                ledger_store=ledger_store,
                user_id=current_user.id,
                job_id=job_id,
                tier=proc_settings.transcribe_tier,
                duration_seconds=float(authorized_quote.max_duration_seconds),
                provider=proc_settings.transcribe_provider,
                stt_model=stt_model,
                allow_downward_adjustment=True,
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

    return job, charge_plan, reserved_balance


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
    """Reserve the confirmed price, then stream the video into its workspace."""
    metadata = _decode_stream_process_metadata(
        request.headers.get("x-gsubs-upload-metadata"),
    )
    proc_settings = build_processing_settings(
        transcribe_tier=metadata.transcribe_tier,
        transcribe_provider=metadata.transcribe_provider,
        openai_model=metadata.openai_model,
        video_quality=metadata.video_quality,
        video_resolution=metadata.video_resolution,
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
    filename = Path(metadata.filename.replace("\\", "/")).name
    file_ext = Path(filename).suffix.lower()
    if not filename or file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")
    validate_upload_content_type(
        request.headers.get("content-type", "").partition(";")[0],
    )

    expected_upload_bytes = _parse_content_length(request)
    authorized_quote = _authorized_video_quote(metadata.authorized_credits)
    stt_model = pricing.resolve_requested_transcribe_model(
        tier=proc_settings.transcribe_tier,
        provider=proc_settings.transcribe_provider,
        openai_model=proc_settings.openai_model,
    )
    preflight_processing_provider_budget(
        ledger_store=ledger_store,
        tier=proc_settings.transcribe_tier,
        duration_seconds=float(authorized_quote.max_duration_seconds),
        provider=proc_settings.transcribe_provider,
        stt_model=stt_model,
    )

    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_root = data_roots()
    input_path = uploads_dir / f"{job_id}_input{file_ext}"
    job, charge_plan, reserved_balance = _reserve_stream_upload(
        job_id=job_id,
        current_user=current_user,
        job_store=job_store,
        ledger_store=ledger_store,
        db=db,
        data_dir=data_dir,
        input_path=input_path,
        artifacts_root=artifacts_root,
        expected_upload_bytes=expected_upload_bytes,
        proc_settings=proc_settings,
        authorized_quote=authorized_quote,
        stt_model=stt_model,
    )

    try:
        with lock_job_workspace(data_dir=data_dir, job_id=job_id):
            await save_request_stream_with_limit(
                request,
                input_path,
                expected_size=expected_upload_bytes,
                cleanup_on_error=False,
            )
            # The complete input is now reflected in real filesystem usage;
            # remove its pre-upload reservation before admitting another job.
            job_store.update_job(job_id, result_data={})
            job.result_data = None
    except BaseException as exc:
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
        pre_created_job=job,
        pre_reserved_charge_plan=charge_plan,
        pre_reserved_balance=reserved_balance,
    )
