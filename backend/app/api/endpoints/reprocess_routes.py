"""Reprocess routes."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.auth import User
from ...core.config import settings
from ...core.database import Database
from ...core.erasure_journal import configured_erasure_journal
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
    data_roots,
    link_or_copy_file,
    require_storage_capacity,
    upload_storage_reservation_bytes,
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
)

router = APIRouter()


class ReprocessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorized_credits: int = Field(..., strict=True)
    transcribe_tier: str = Field(settings.default_transcribe_tier, max_length=50)
    transcribe_provider: str = Field(settings.transcribe_tier_provider[settings.default_transcribe_tier], max_length=50)
    openai_model: str = Field("", max_length=50)
    video_quality: str = Field("high quality", max_length=50)
    video_resolution: str = Field("", max_length=50)
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


def _record_and_delete_failed_reprocess(
    *,
    job_id: str,
    user_id: str,
    input_path: Path,
    artifacts_root: Path,
    database_job_may_exist: bool,
    job_store: JobStore,
    history_store: HistoryStore,
) -> None:
    """Persist restore-safe intent before removing a failed reprocess copy."""
    with lock_job_workspace(data_dir=artifacts_root.parent, job_id=job_id):
        configured_erasure_journal().append(
            kind="job" if database_job_may_exist else "workspace",
            user_id=user_id,
            job_ids=[job_id],
        )
        delete_job_workspace(
            job_id=job_id,
            uploads_dir=input_path.parent,
            artifacts_dir=artifacts_root,
            expected_user_id=user_id,
        )
        if database_job_may_exist:
            history_store.delete_job_events([job_id])
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
            raise RuntimeError("Failed reprocess cleanup could not be verified")
        remove_workspace_ownership_after_verified_cleanup(
            data_dir=artifacts_root.parent,
            job_id=job_id,
            expected_user_id=user_id,
        )


def _reserve_reprocess_job(
    *,
    new_job_id: str,
    current_user: User,
    source_input: Path,
    input_path: Path,
    data_dir: Path,
    artifacts_root: Path,
    proc_settings: ProcessingSettings,
    duration_seconds: float,
    source_size_bytes: int,
    stt_model: str,
    job_store: JobStore,
    history_store: HistoryStore,
    ledger_store: UsageLedgerStore,
    db: Database,
) -> tuple[Job, ChargePlan, int]:
    """Copy, create and charge one reprocess job under atomic admission."""
    with media_job_admission(db):
        active_jobs = job_store.count_active_jobs_for_user(current_user.id)
        if active_jobs >= settings.max_concurrent_jobs:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Too many active jobs. Please wait for your current jobs "
                    f"to finish (max {settings.max_concurrent_jobs})."
                ),
            )

        require_storage_capacity(
            data_dir,
            required_bytes=upload_storage_reservation_bytes(source_size_bytes),
            db=db,
        )

        try:
            with lock_job_workspace(data_dir=data_dir, job_id=new_job_id):
                record_workspace_ownership(
                    data_dir=data_dir,
                    job_id=new_job_id,
                    user_id=current_user.id,
                )
                link_or_copy_file(source_input, input_path)
        except BaseException as exc:
            _record_and_delete_failed_reprocess(
                job_id=new_job_id,
                user_id=current_user.id,
                input_path=input_path,
                artifacts_root=artifacts_root,
                database_job_may_exist=False,
                job_store=job_store,
                history_store=history_store,
            )
            if isinstance(exc, FileNotFoundError):
                raise HTTPException(
                    status_code=404,
                    detail="Source video not found; upload again to reprocess",
                ) from exc
            raise

        try:
            job = job_store.create_job(new_job_id, current_user.id)
        except BaseException:
            _record_and_delete_failed_reprocess(
                job_id=new_job_id,
                user_id=current_user.id,
                input_path=input_path,
                artifacts_root=artifacts_root,
                database_job_may_exist=True,
                job_store=job_store,
                history_store=history_store,
            )
            raise

        try:
            charge_plan, new_balance = reserve_processing_charges(
                ledger_store=ledger_store,
                user_id=current_user.id,
                job_id=new_job_id,
                tier=proc_settings.transcribe_tier,
                duration_seconds=duration_seconds,
                provider=proc_settings.transcribe_provider,
                stt_model=stt_model,
            )
        except BaseException:
            _record_and_delete_failed_reprocess(
                job_id=new_job_id,
                user_id=current_user.id,
                input_path=input_path,
                artifacts_root=artifacts_root,
                database_job_may_exist=True,
                job_store=job_store,
                history_store=history_store,
            )
            raise

    return job, charge_plan, new_balance


def _require_reprocessable_job(
    job_id: str,
    *,
    current_user: User,
    job_store: JobStore,
) -> Job:
    source_job = job_store.get_job(job_id)
    if source_job is None or source_job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if source_job.status != "completed":
        raise HTTPException(
            status_code=400,
            detail="Job must be completed to reprocess",
        )
    if job_store.count_active_jobs_for_user(current_user.id) >= settings.max_concurrent_jobs:
        raise HTTPException(
            status_code=429,
            detail=(
                "Too many active jobs. Please wait for your current jobs "
                f"to finish (max {settings.max_concurrent_jobs})."
            ),
        )
    return source_job


def _processing_settings_from_reprocess(request: ReprocessRequest) -> ProcessingSettings:
    return build_processing_settings(
        transcribe_tier=request.transcribe_tier,
        transcribe_provider=request.transcribe_provider,
        openai_model=request.openai_model,
        video_quality=request.video_quality,
        video_resolution=request.video_resolution,
        context_prompt=request.context_prompt,
        subtitle_position=request.subtitle_position,
        max_subtitle_lines=request.max_subtitle_lines,
        subtitle_color=request.subtitle_color,
        shadow_strength=request.shadow_strength,
        highlight_style=request.highlight_style,
        subtitle_size=request.subtitle_size,
        karaoke_enabled=request.karaoke_enabled,
        watermark_enabled=request.watermark_enabled,
    )


def _find_reprocess_source(
    *,
    job_id: str,
    source_job: Job,
    data_dir: Path,
    uploads_dir: Path,
) -> Path:
    for extension in sorted(ALLOWED_VIDEO_EXTENSIONS):
        candidate = uploads_dir / f"{job_id}_input{extension}"
        if candidate.exists():
            return candidate

    candidate_rel = (source_job.result_data or {}).get("video_path")
    if isinstance(candidate_rel, str) and candidate_rel:
        candidate = (data_dir / candidate_rel).resolve()
        if candidate.is_relative_to(data_dir.resolve()) and candidate.exists():
            return candidate
    raise HTTPException(
        status_code=404,
        detail="Source video not found; upload again to reprocess",
    )


def _validate_reprocess_source(
    source_input: Path,
    *,
    authorized_credits: int,
) -> tuple[int, MediaProbe]:
    if source_input.suffix.lower() not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid source video extension")
    size_bytes = source_input.stat().st_size
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Empty source video")
    if size_bytes > (settings.max_upload_mb * 1024 * 1024):
        raise HTTPException(
            status_code=413,
            detail=f"File too large; limit is {settings.max_upload_mb}MB",
        )
    try:
        probe = probe_media(source_input)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Could not validate source media file",
        ) from exc
    duration = probe.duration_s
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise HTTPException(
            status_code=400,
            detail="Could not determine video duration",
        )
    if duration > settings.max_video_duration_seconds:
        raise HTTPException(
            status_code=400,
            detail=(f"Video too long (max {settings.max_video_duration_seconds / 60:.1f} minutes)"),
        )
    assert_processing_quote_authorized(
        duration_seconds=float(duration),
        authorized_credits=authorized_credits,
    )
    return size_bytes, probe


@dataclass(frozen=True)
class _ReprocessScheduleContext:
    source_job: Job
    source_job_id: str
    new_job_id: str
    input_path: Path
    output_path: Path
    artifact_path: Path
    artifacts_root: Path
    proc_settings: ProcessingSettings
    job_store: JobStore
    history_store: HistoryStore
    ledger_store: UsageLedgerStore
    current_user: User
    charge_plan: ChargePlan
    probe: MediaProbe
    background_tasks: BackgroundTasks


def _schedule_reprocess_job(context: _ReprocessScheduleContext) -> None:
    original_filename = (context.source_job.result_data or {}).get("original_filename")
    event_filename = (
        context.source_job.result_data.get("original_filename", "video") if context.source_job.result_data else "video"
    )
    try:
        _record_reprocess_started(
            history_store=context.history_store,
            current_user=context.current_user,
            event_filename=event_filename,
            new_job_id=context.new_job_id,
            source_job_id=context.source_job_id,
            proc_settings=context.proc_settings,
        )
        _enqueue_reprocess_worker(
            background_tasks=context.background_tasks,
            new_job_id=context.new_job_id,
            input_path=context.input_path,
            output_path=context.output_path,
            artifact_path=context.artifact_path,
            proc_settings=context.proc_settings,
            job_store=context.job_store,
            history_store=context.history_store,
            current_user=context.current_user,
            original_filename=original_filename,
            ledger_store=context.ledger_store,
            charge_plan=context.charge_plan,
            probe=context.probe,
        )
    except BaseException as exc:
        _rollback_failed_reprocess_schedule(
            job_id=context.new_job_id,
            user_id=context.current_user.id,
            input_path=context.input_path,
            artifacts_root=context.artifacts_root,
            job_store=context.job_store,
            history_store=context.history_store,
            ledger_store=context.ledger_store,
            charge_plan=context.charge_plan,
            error=exc,
        )
        raise


def _record_reprocess_started(
    *,
    history_store: HistoryStore,
    current_user: User,
    event_filename: object,
    new_job_id: str,
    source_job_id: str,
    proc_settings: ProcessingSettings,
) -> None:
    record_event_safe(
        history_store,
        current_user,
        "process_started",
        f"Reprocessing {event_filename}",
        {
            "job_id": new_job_id,
            "source_job_id": source_job_id,
            "provider": proc_settings.transcribe_provider,
            "transcribe_tier": proc_settings.transcribe_tier,
            "source": "local",
        },
    )


def _enqueue_reprocess_worker(
    *,
    background_tasks: BackgroundTasks,
    new_job_id: str,
    input_path: Path,
    output_path: Path,
    artifact_path: Path,
    proc_settings: ProcessingSettings,
    job_store: JobStore,
    history_store: HistoryStore,
    current_user: User,
    original_filename: str | None,
    ledger_store: UsageLedgerStore,
    charge_plan: ChargePlan,
    probe: MediaProbe,
) -> None:
    background_tasks.add_task(
        run_video_processing,
        new_job_id,
        input_path,
        output_path,
        artifact_path,
        proc_settings,
        job_store,
        history_store,
        current_user,
        original_filename,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=probe,
    )


def _rollback_failed_reprocess_schedule(
    *,
    job_id: str,
    user_id: str,
    input_path: Path,
    artifacts_root: Path,
    job_store: JobStore,
    history_store: HistoryStore,
    ledger_store: UsageLedgerStore,
    charge_plan: ChargePlan,
    error: BaseException,
) -> None:
    refund_charge_best_effort(
        ledger_store,
        charge_plan,
        status="failed",
        error=sanitize_message(str(error)),
    )
    _record_and_delete_failed_reprocess(
        job_id=job_id,
        user_id=user_id,
        input_path=input_path,
        artifacts_root=artifacts_root,
        database_job_may_exist=True,
        job_store=job_store,
        history_store=history_store,
    )


@router.post("/jobs/{job_id}/reprocess", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
def reprocess_job(
    job_id: str,
    request: ReprocessRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user_with_media_lifecycle),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
    db: Database = Depends(get_db),
) -> JobResponse:
    source_job = _require_reprocessable_job(
        job_id,
        current_user=current_user,
        job_store=job_store,
    )
    proc_settings = _processing_settings_from_reprocess(request)
    data_dir, uploads_dir, artifacts_root = data_roots()
    source_input = _find_reprocess_source(
        job_id=job_id,
        source_job=source_job,
        data_dir=data_dir,
        uploads_dir=uploads_dir,
    )
    size_bytes, probe = _validate_reprocess_source(
        source_input,
        authorized_credits=request.authorized_credits,
    )
    duration_seconds = float(cast(float, probe.duration_s))
    stt_model = pricing.resolve_requested_transcribe_model(
        tier=proc_settings.transcribe_tier,
        provider=proc_settings.transcribe_provider,
        openai_model=proc_settings.openai_model,
    )
    preflight_processing_charges(
        ledger_store=ledger_store,
        user_id=current_user.id,
        tier=proc_settings.transcribe_tier,
        duration_seconds=duration_seconds,
        provider=proc_settings.transcribe_provider,
        stt_model=stt_model,
    )

    new_job_id = str(uuid.uuid4())
    input_path = uploads_dir / f"{new_job_id}_input{source_input.suffix.lower()}"
    output_path = artifacts_root / new_job_id / "processed.mp4"
    artifact_path = artifacts_root / new_job_id
    job, charge_plan, new_balance = _reserve_reprocess_job(
        new_job_id=new_job_id,
        current_user=current_user,
        source_input=source_input,
        input_path=input_path,
        data_dir=data_dir,
        artifacts_root=artifacts_root,
        proc_settings=proc_settings,
        duration_seconds=duration_seconds,
        source_size_bytes=size_bytes,
        stt_model=stt_model,
        job_store=job_store,
        history_store=history_store,
        ledger_store=ledger_store,
        db=db,
    )
    _schedule_reprocess_job(
        _ReprocessScheduleContext(
            source_job=source_job,
            source_job_id=job_id,
            new_job_id=new_job_id,
            input_path=input_path,
            output_path=output_path,
            artifact_path=artifact_path,
            artifacts_root=artifacts_root,
            proc_settings=proc_settings,
            job_store=job_store,
            history_store=history_store,
            ledger_store=ledger_store,
            current_user=current_user,
            charge_plan=charge_plan,
            probe=probe,
            background_tasks=background_tasks,
        )
    )
    return JobResponse.model_validate(job).model_copy(update={"balance": new_balance})
