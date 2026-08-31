"""Queue handoff for a validated and durably charged upload."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from fastapi import BackgroundTasks

from ...core.auth import User
from ...core.config import settings
from ...core.errors import ProcessingQuoteChangedError, sanitize_message
from ...services.ffmpeg_utils import MediaProbe
from ...services.history import HistoryStore
from ...services.jobs import Job, JobStore
from ...services.usage_ledger import ChargePlan, UsageLedgerStore
from .settings import ProcessingSettings


@dataclass(frozen=True)
class SavedUploadContext:
    background_tasks: BackgroundTasks
    job_id: str
    input_path: Path
    artifacts_root: Path
    filename: str
    video_resolution: str
    authorized_credits: int
    proc_settings: ProcessingSettings
    current_user: User
    job_store: JobStore
    history_store: HistoryStore
    ledger_store: UsageLedgerStore


def validate_pre_reserved_state(
    pre_created_job: Job | None,
    pre_reserved_charge_plan: ChargePlan | None,
    pre_reserved_balance: int | None,
) -> None:
    reserved_state = (
        pre_created_job,
        pre_reserved_charge_plan,
        pre_reserved_balance,
    )
    if any(value is not None for value in reserved_state) and any(value is None for value in reserved_state):
        raise ValueError("Incomplete pre-upload reservation state")


def saved_upload_duration_error(probe: MediaProbe) -> str | None:
    duration = probe.duration_s
    if duration is None or not math.isfinite(duration) or duration <= 0:
        return "Could not determine video duration"
    if duration > settings.max_video_duration_seconds:
        return f"Video too long (max {settings.max_video_duration_seconds / 60:.1f} minutes)"
    return None


def authorize_saved_upload_quote(
    context: SavedUploadContext,
    *,
    probe: MediaProbe,
    charge_plan: ChargePlan | None,
    job_created: bool,
    assert_quote: Callable[..., None],
    reject_saved: Callable[..., None],
) -> None:
    duration = cast(float, probe.duration_s)
    try:
        assert_quote(
            duration_seconds=float(duration),
            authorized_credits=context.authorized_credits,
        )
    except ProcessingQuoteChangedError as exc:
        reject_saved(
            context,
            charge_plan=charge_plan,
            job_created=job_created,
            error=str(exc),
        )
        raise


def preflight_saved_upload(
    context: SavedUploadContext,
    *,
    duration: float,
    stt_model: str,
    preflight_charges: Callable[..., None],
    reject_saved: Callable[..., None],
) -> None:
    try:
        preflight_charges(
            ledger_store=context.ledger_store,
            user_id=context.current_user.id,
            tier=context.proc_settings.transcribe_tier,
            duration_seconds=duration,
            provider=context.proc_settings.transcribe_provider,
            stt_model=stt_model,
        )
    except Exception:
        reject_saved(
            context,
            charge_plan=None,
            job_created=False,
            error="Processing preflight failed",
        )
        raise


def schedule_saved_upload(
    context: SavedUploadContext,
    *,
    job: Job,
    charge_plan: ChargePlan,
    probe: MediaProbe,
    run_processing: Callable[..., Any],
    record_event: Callable[..., None],
    refund_charge: Callable[..., None],
    cleanup_rejected: Callable[..., None],
) -> None:
    """Enqueue one worker and undo the charge/workspace if handoff fails."""
    output_path = context.artifacts_root / context.job_id / "processed.mp4"
    artifact_path = context.artifacts_root / context.job_id
    try:
        _enqueue_saved_upload_worker(
            context,
            output_path=output_path,
            artifact_path=artifact_path,
            charge_plan=charge_plan,
            probe=probe,
            run_processing=run_processing,
        )
        _record_saved_upload_queued(context, record_event=record_event)
    except Exception as exc:
        _rollback_saved_upload_handoff(
            context,
            charge_plan=charge_plan,
            error=exc,
            refund_charge=refund_charge,
            cleanup_rejected=cleanup_rejected,
        )
        raise


def _enqueue_saved_upload_worker(
    context: SavedUploadContext,
    *,
    output_path: Path,
    artifact_path: Path,
    charge_plan: ChargePlan,
    probe: MediaProbe,
    run_processing: Callable[..., Any],
) -> None:
    context.background_tasks.add_task(
        run_processing,
        context.job_id,
        context.input_path,
        output_path,
        artifact_path,
        context.proc_settings,
        context.job_store,
        context.history_store,
        context.current_user,
        context.filename,
        ledger_store=context.ledger_store,
        charge_plan=charge_plan,
        source_probe=probe,
    )


def _record_saved_upload_queued(context: SavedUploadContext, *, record_event: Callable[..., None]) -> None:
    record_event(
        context.history_store,
        context.current_user,
        "process_started",
        f"Queued {context.filename}",
        {
            "job_id": context.job_id,
            "transcribe_tier": context.proc_settings.transcribe_tier,
            "provider": context.proc_settings.transcribe_provider
            or settings.transcribe_tier_provider[settings.default_transcribe_tier],
            "video_quality": context.proc_settings.video_quality,
            "video_resolution": context.video_resolution,
        },
    )


def _rollback_saved_upload_handoff(
    context: SavedUploadContext,
    *,
    charge_plan: ChargePlan,
    error: Exception,
    refund_charge: Callable[..., None],
    cleanup_rejected: Callable[..., None],
) -> None:
    refund_charge(
        context.ledger_store,
        charge_plan,
        status="failed",
        error=sanitize_message(str(error)),
    )
    cleanup_rejected(
        job_id=context.job_id,
        user_id=context.current_user.id,
        input_path=context.input_path,
        artifacts_root=context.artifacts_root,
        kind="job",
        job_store=context.job_store,
    )
