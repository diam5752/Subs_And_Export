"""Authenticated resumable uploads using the existing job/credit lifecycle."""

from __future__ import annotations

import errno
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request

from ...core.auth import User
from ...core.config import settings
from ...core.database import Database
from ...core.ratelimit import limiter_processing
from ...core.upload_session import UPLOAD_SESSION_KEY
from ...core.workspace_deletion import JobWorkspaceLockTimeoutError, lock_job_workspace
from ...schemas.base import JobResponse
from ...services import pricing
from ...services.charge_plans import preflight_processing_provider_budget
from ...services.history import HistoryStore
from ...services.jobs import Job, JobStore
from ...services.usage_ledger import ChargePlan, ChargeReservation, UsageLedgerStore
from ..deps import (
    get_current_user_with_media_lifecycle,
    get_db,
    get_history_store,
    get_job_store,
    get_usage_ledger_store,
)
from . import videos
from .file_utils import data_roots
from .resumable_upload_io import (
    UploadSessionRequest,
    UploadSessionResponse,
    append_chunk,
    chunk_headers,
    owned_upload,
    read_chunk,
    session_response,
    upload_input_path,
    upload_state,
    writable_upload_state,
)
from .settings import ProcessingSettings, build_processing_settings
from .stream_upload_contract import StreamProcessMetadata, authorized_video_quote
from .validation import ALLOWED_VIDEO_EXTENSIONS, validate_upload_content_type

router = APIRouter()


@dataclass(frozen=True)
class UploadContext:
    user: User
    jobs: JobStore
    history: HistoryStore
    ledger: UsageLedgerStore
    db: Database


def upload_context(
    user: User = Depends(get_current_user_with_media_lifecycle),
    jobs: JobStore = Depends(get_job_store),
    history: HistoryStore = Depends(get_history_store),
    ledger: UsageLedgerStore = Depends(get_usage_ledger_store),
    db: Database = Depends(get_db),
) -> UploadContext:
    return UploadContext(user, jobs, history, ledger, db)


def _processing_settings(metadata: StreamProcessMetadata) -> ProcessingSettings:
    return build_processing_settings(**metadata.model_dump(exclude={"filename", "authorized_credits"}))


def _charge_plan(job: Job) -> ChargePlan:
    raw = upload_state(job)["charge"]
    reservation = ChargeReservation(**raw) if raw is not None else None
    return ChargePlan(transcription=reservation)


def _cleanup_upload(ctx: UploadContext, job: Job, error: str) -> None:
    _, uploads_dir, artifacts_dir = data_roots()
    videos._cleanup_saved_upload_failure(
        job_id=job.id,
        current_user=ctx.user,
        input_path=upload_input_path(job, uploads_dir),
        artifacts_root=artifacts_dir,
        job_store=ctx.jobs,
        ledger_store=ctx.ledger,
        charge_plan=_charge_plan(job),
        job_created=True,
        error=error,
    )


def _reserve_session(payload: UploadSessionRequest, ctx: UploadContext) -> tuple[Job, ChargePlan, int]:
    metadata = payload.metadata
    filename = Path(metadata.filename.replace("\\", "/")).name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(400, "Invalid file type")
    validate_upload_content_type(payload.content_type)
    proc_settings = _processing_settings(metadata)
    quote = authorized_video_quote(metadata.authorized_credits)
    stt_model = pricing.resolve_requested_transcribe_model(
        tier=proc_settings.transcribe_tier,
        provider=proc_settings.transcribe_provider,
        openai_model=proc_settings.openai_model,
    )
    preflight_processing_provider_budget(
        ledger_store=ctx.ledger,
        tier=proc_settings.transcribe_tier,
        duration_seconds=float(quote.max_duration_seconds),
        provider=proc_settings.transcribe_provider,
        stt_model=stt_model,
    )
    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_dir = data_roots()
    return videos._reserve_stream_upload(
        job_id=job_id,
        current_user=ctx.user,
        job_store=ctx.jobs,
        ledger_store=ctx.ledger,
        db=ctx.db,
        data_dir=data_dir,
        input_path=uploads_dir / f"{job_id}_input{suffix}",
        artifacts_root=artifacts_dir,
        expected_upload_bytes=payload.size,
        proc_settings=proc_settings,
        authorized_quote=quote,
        stt_model=stt_model,
    )


@router.post("/uploads", response_model=UploadSessionResponse, dependencies=[Depends(limiter_processing)])
def create_upload(payload: UploadSessionRequest, ctx: UploadContext = Depends(upload_context)) -> UploadSessionResponse:
    """Reserve credits, an admission slot, and disk space before any media."""
    job, charge, balance = _reserve_session(payload, ctx)
    result = dict(job.result_data or {})
    result[UPLOAD_SESSION_KEY] = {
        "metadata": payload.metadata.model_dump(),
        "size": payload.size,
        "offset": 0,
        "expires_at": int(time.time() + settings.upload_total_timeout_seconds),
        "phase": "uploading",
        "charge": asdict(charge.transcription) if charge.transcription is not None else None,
        "balance": balance,
    }
    job.result_data = result
    try:
        ctx.jobs.update_job(job.id, result_data=result)
    except BaseException:
        _cleanup_upload(ctx, job, "Upload session could not be saved")
        raise
    return session_response(job)


@router.get("/uploads/{upload_id}", response_model=UploadSessionResponse)
def get_upload(upload_id: uuid.UUID, ctx: UploadContext = Depends(upload_context)) -> UploadSessionResponse:
    job = owned_upload(ctx.jobs, str(upload_id), ctx.user.id)
    writable_upload_state(job)
    return session_response(job)


@router.post("/uploads/{upload_id}/chunks", response_model=UploadSessionResponse)
async def receive_chunk(
    upload_id: uuid.UUID,
    request: Request,
    ctx: UploadContext = Depends(upload_context),
) -> UploadSessionResponse:
    """Serialize this upload before reading its bounded, retryable body."""
    data_dir, uploads_dir, _ = data_roots()
    owned_upload(ctx.jobs, str(upload_id), ctx.user.id)
    try:
        # A competing request must not block the event loop while its current
        # owner awaits network bytes. The client can retry this 409 response.
        with lock_job_workspace(data_dir=data_dir, job_id=str(upload_id), timeout_seconds=0.01):
            job = owned_upload(ctx.jobs, str(upload_id), ctx.user.id)
            state = writable_upload_state(job)
            offset, digest = chunk_headers(request, state["size"])
            body = await read_chunk(request, expires_at=state["expires_at"], digest=digest)
            updated = append_chunk(job, ctx.jobs, upload_input_path(job, uploads_dir), offset, body)
            return session_response(updated)
    except JobWorkspaceLockTimeoutError as exc:
        raise HTTPException(409, "Another request is writing this upload") from exc
    except OSError as exc:
        if exc.errno == errno.ENOSPC:
            raise HTTPException(507, "Storage became temporarily unavailable") from exc
        raise


def _begin_completion(ctx: UploadContext, upload_id: str) -> Job | None:
    data_dir, uploads_dir, _ = data_roots()
    with lock_job_workspace(data_dir=data_dir, job_id=upload_id):
        job = owned_upload(ctx.jobs, upload_id, ctx.user.id)
        raw = (job.result_data or {}).get(UPLOAD_SESSION_KEY)
        if raw is None or raw["phase"] == "queued":
            return None
        state = writable_upload_state(job)
        path = upload_input_path(job, uploads_dir)
        if state["offset"] != state["size"] or not path.is_file() or path.stat().st_size != state["size"]:
            raise HTTPException(409, "Upload is incomplete")
        state["phase"] = "queued"
        result = {UPLOAD_SESSION_KEY: state}
        ctx.jobs.update_job(job.id, result_data=result)
        job.result_data = result
        return job


@router.post("/uploads/{upload_id}/complete", response_model=JobResponse)
def complete_upload(
    upload_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    ctx: UploadContext = Depends(upload_context),
) -> JobResponse:
    """The durable phase transition makes completion retries charge/queue once."""
    job = _begin_completion(ctx, str(upload_id))
    if job is None:
        return JobResponse.model_validate(owned_upload(ctx.jobs, str(upload_id), ctx.user.id))
    state = upload_state(job)
    metadata = StreamProcessMetadata.model_validate(state["metadata"])
    _, uploads_dir, artifacts_dir = data_roots()
    return videos._queue_saved_upload(
        background_tasks=background_tasks,
        job_id=job.id,
        input_path=upload_input_path(job, uploads_dir),
        artifacts_root=artifacts_dir,
        filename=Path(metadata.filename.replace("\\", "/")).name,
        video_resolution=metadata.video_resolution,
        authorized_credits=metadata.authorized_credits,
        proc_settings=_processing_settings(metadata),
        current_user=ctx.user,
        job_store=ctx.jobs,
        history_store=ctx.history,
        ledger_store=ctx.ledger,
        db=ctx.db,
        pre_created_job=job,
        pre_reserved_charge_plan=_charge_plan(job),
        pre_reserved_balance=state["balance"],
    )


@router.delete("/uploads/{upload_id}")
def cancel_upload(upload_id: uuid.UUID, ctx: UploadContext = Depends(upload_context)) -> dict[str, str]:
    data_dir, _, _ = data_roots()
    with lock_job_workspace(data_dir=data_dir, job_id=str(upload_id)):
        job = owned_upload(ctx.jobs, str(upload_id), ctx.user.id)
        state = upload_state(job)
        if state["phase"] != "uploading":
            raise HTTPException(409, "Upload was already submitted for processing")
        state["phase"] = "cancelled"
        result = {**(job.result_data or {}), UPLOAD_SESSION_KEY: state}
        ctx.jobs.update_job(job.id, result_data=result)
        job.result_data = result
    _cleanup_upload(ctx, job, "Upload cancelled")
    return {"status": "cancelled"}
