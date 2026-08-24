"""Background processing tasks for video processing endpoints."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Literal

from ...core.auth import User
from ...core.config import settings as app_settings
from ...core.database import Database
from ...core.erasure_journal import JobTerminalStatus, configured_erasure_journal
from ...core.errors import (
    ProviderDispatchAlreadyClaimedError,
    sanitize_message,
)
from ...core.job_lifecycle import CANCELLABLE_JOB_STATUSES
from ...core.workspace_deletion import (
    JobWorkspaceLockTimeoutError,
    delete_job_workspace,
    lock_job_workspace,
)
from ...services.ffmpeg_utils import MediaProbe, probe_media
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.points import PointsStore
from ...services.usage_ledger import ChargePlan, UsageLedgerStore
from ...services.video_processing import process_video_pipeline, resolve_runtime_transcribe_provider
from ...services.video_quality import crf_for_video_quality
from .file_utils import data_roots, relpath_safe
from .settings import ProcessingSettings

logger = logging.getLogger(__name__)


class DeletedJobError(InterruptedError):
    """Raised when account or job erasure wins a processing race."""


class JobCancellationError(InterruptedError):
    """Raised only after authoritative job state requests cancellation."""


class StaleWorkerError(RuntimeError):
    """Raised when another actor has already moved a job out of processing."""


CleanupFailureDisposition = Literal[
    "failed",
    "cancellation_deferred",
    "deleted",
    "unchanged",
]


def raise_for_rejected_worker_write(*, job_store: JobStore, job_id: str) -> None:
    """Translate a rejected compare-and-set into the correct worker stop."""
    current_job = job_store.get_job(job_id)
    if current_job is None:
        raise DeletedJobError("Job was deleted")
    if current_job.status in {"cancelling", "cancelled"}:
        raise JobCancellationError("Job cancelled by user")
    raise StaleWorkerError(
        f"Job is no longer processing (status={current_job.status})"
    )


def delete_local_workspace_best_effort(
    *,
    job_id: str,
    expected_user_id: str | None,
    workspace_lock_held: bool = False,
) -> None:
    """Remove one job's local media without masking its terminal status."""
    try:
        data_dir, uploads_dir, artifacts_root = data_roots()
        if workspace_lock_held:
            _delete_local_workspace_unlocked(
                job_id=job_id,
                uploads_dir=uploads_dir,
                artifacts_root=artifacts_root,
                expected_user_id=expected_user_id,
            )
        else:
            with lock_job_workspace(data_dir=data_dir, job_id=job_id):
                _delete_local_workspace_unlocked(
                    job_id=job_id,
                    uploads_dir=uploads_dir,
                    artifacts_root=artifacts_root,
                    expected_user_id=expected_user_id,
                )
    except Exception:
        logger.exception(
            "Failed to lock terminal job workspace for cleanup",
            extra={"job_id": job_id},
        )


def _delete_local_workspace_unlocked(
    *,
    job_id: str,
    uploads_dir: Path,
    artifacts_root: Path,
    expected_user_id: str | None,
) -> None:
    """Best-effort deletion used only while the caller holds the job lock."""
    try:
        delete_job_workspace(
            job_id=job_id,
            uploads_dir=uploads_dir,
            artifacts_dir=artifacts_root,
            expected_user_id=expected_user_id,
        )
    except Exception:
        logger.exception(
            "Failed to clean terminal job workspace",
            extra={"job_id": job_id},
        )


def record_and_delete_local_workspace(
    *,
    job_id: str,
    user_id: str,
    terminal_status: JobTerminalStatus,
    workspace_lock_held: bool = False,
) -> None:
    """Record restore-safe terminal intent before deleting local media."""
    data_dir, uploads_dir, artifacts_root = data_roots()
    if workspace_lock_held:
        configured_erasure_journal().append_job_terminal(
            user_id=user_id,
            job_ids=[job_id],
            terminal_status=terminal_status,
        )
        delete_job_workspace(
            job_id=job_id,
            uploads_dir=uploads_dir,
            artifacts_dir=artifacts_root,
            expected_user_id=user_id,
        )
        return
    with lock_job_workspace(data_dir=data_dir, job_id=job_id):
        configured_erasure_journal().append_job_terminal(
            user_id=user_id,
            job_ids=[job_id],
            terminal_status=terminal_status,
        )
        delete_job_workspace(
            job_id=job_id,
            uploads_dir=uploads_dir,
            artifacts_dir=artifacts_root,
            expected_user_id=user_id,
        )


def refund_charge_best_effort(
    ledger_store: UsageLedgerStore | None,
    charge_plan: ChargePlan | None,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Best-effort refund of reserved charges. Never raises."""
    if not ledger_store or not charge_plan:
        return

    reservations = [charge_plan.transcription, charge_plan.social_copy]
    for reservation in reservations:
        if not reservation:
            continue
        try:
            ledger_store.refund_if_reserved(reservation, status=status, error=error)
        except Exception:
            logger.exception(
                "Failed to refund reserved credits (user_id=%s action=%s status=%s)",
                reservation.user_id,
                reservation.action,
                status,
            )


def abort_deleted_job(
    *,
    job_id: str,
    expected_user_id: str | None,
    ledger_store: UsageLedgerStore | None,
    charge_plan: ChargePlan | None,
    error: str,
    workspace_lock_held: bool = False,
) -> None:
    """Refund once and remove the exact local workspace of a deleted job."""
    delete_local_workspace_best_effort(
        job_id=job_id,
        expected_user_id=expected_user_id,
        workspace_lock_held=workspace_lock_held,
    )
    refund_charge_best_effort(
        ledger_store,
        charge_plan,
        status="cancelled",
        error=error,
    )


def record_event_safe(
    history_store: HistoryStore | None,
    user: User | None,
    kind: str,
    summary: str,
    data: dict[str, Any],
) -> None:
    """Best-effort history logger that never raises."""
    if not history_store or not user:
        return
    try:
        history_store.record_event(user, kind, summary, data)
    except Exception as exc:
        logger.warning("Failed to record history event %s: %s", kind, exc)


def resolve_terminal_cleanup_failure(
    *,
    job_store: JobStore,
    job_id: str,
    privacy_error: str,
) -> CleanupFailureDisposition:
    """Resolve cleanup failure from authoritative state, never a stale snapshot."""
    if job_store.update_job_if_status(
        job_id,
        expected_statuses=CANCELLABLE_JOB_STATUSES,
        status="failed",
        message=privacy_error,
    ):
        return "failed"

    latest_job = job_store.get_job(job_id)
    if latest_job is None:
        return "deleted"
    if latest_job.status in {"cancelling", "cancelled"}:
        return "cancellation_deferred"
    if latest_job.status == "failed":
        return "failed"
    return "unchanged"


def reconcile_stranded_cancellations(db: Database) -> int:
    """Finish crash-stranded cancellations before the app becomes healthy."""
    job_store = JobStore(db)
    ledger_store = UsageLedgerStore(db=db, points_store=PointsStore(db=db))
    data_dir, uploads_dir, artifacts_root = data_roots()
    journal = configured_erasure_journal()
    reconciled = 0

    for candidate in job_store.list_jobs_with_statuses({"cancelling"}):
        with lock_job_workspace(data_dir=data_dir, job_id=candidate.id):
            current_job = job_store.get_job(candidate.id)
            if current_job is None or current_job.status != "cancelling":
                continue
            journal.append_job_terminal(
                user_id=current_job.user_id,
                job_ids=[current_job.id],
                terminal_status="cancelled",
            )
            delete_job_workspace(
                job_id=current_job.id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_root,
                expected_user_id=current_job.user_id,
            )
            ledger_store.fail_job_reservations(
                current_job.id,
                error="Cancellation recovered after process restart",
                status="cancelled",
            )
            transitioned = job_store.update_job_if_status(
                current_job.id,
                expected_statuses={"cancelling"},
                status="cancelled",
                message="Cancelled by user",
            )
            if not transitioned:
                latest_job = job_store.get_job(current_job.id)
                if latest_job is None or latest_job.status != "cancelled":
                    raise RuntimeError(
                        "Stranded cancellation changed state during recovery",
                    )
            reconciled += 1
    return reconciled


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
    *,
    ledger_store: UsageLedgerStore | None = None,
    charge_plan: ChargePlan | None = None,
    db: Database | None = None,
    source_probe: MediaProbe | None = None,
) -> None:
    """Background task to run the heavy video processing."""
    worker_user_id = user.id if user is not None else None
    workspace_lock = None
    workspace_lock_held = False
    try:
        data_dir, _, _ = data_roots()
        workspace_lock = lock_job_workspace(data_dir=data_dir, job_id=job_id)
        workspace_lock.__enter__()
        workspace_lock_held = True
        if not job_store.update_job_if_status(
            job_id,
            expected_statuses={"pending"},
            status="processing",
            progress=0,
            message="Starting processing...",
        ):
            raise_for_rejected_worker_write(
                job_store=job_store,
                job_id=job_id,
            )

        last_update_time = 0.0
        last_check_time = 0.0

        def progress_callback(msg: str, percent: float) -> None:
            nonlocal last_update_time
            now = time.time()
            if percent <= 0 or percent >= 100 or (now - last_update_time) >= 1.0:
                if not job_store.update_job_if_status(
                    job_id,
                    expected_statuses={"processing"},
                    progress=int(percent),
                    message=msg,
                ):
                    raise_for_rejected_worker_write(
                        job_store=job_store,
                        job_id=job_id,
                    )
                last_update_time = now

        def check_cancelled(*, force: bool = False) -> None:
            """Check if job was cancelled by user."""
            nonlocal last_check_time
            now = time.monotonic()
            if not force and now - last_check_time < 0.5:
                return

            current_job = job_store.get_job(job_id)
            last_check_time = now
            if current_job is None:
                raise DeletedJobError("Job was deleted")
            if current_job.status in {"cancelling", "cancelled"}:
                raise JobCancellationError("Job cancelled by user")

        tier = settings.transcribe_tier
        requested_provider = settings.transcribe_provider or app_settings.transcribe_tier_provider.get(
            settings.transcribe_tier, app_settings.transcribe_tier_provider[app_settings.default_transcribe_tier]
        )
        provider = resolve_runtime_transcribe_provider(requested_provider)
        video_crf = crf_for_video_quality(settings.video_quality)
        target_width = settings.target_width
        target_height = settings.target_height
        source_duration_seconds: float | None = None

        effective_probe = source_probe
        try:
            if effective_probe is None:
                effective_probe = probe_media(input_path)
            if effective_probe.duration_s is not None and effective_probe.duration_s > 0:
                source_duration_seconds = float(effective_probe.duration_s)
        except Exception:
            source_duration_seconds = None

        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = process_video_pipeline(
            input_path=input_path,
            output_path=output_path,
            transcribe_tier=tier,
            generate_social_copy=settings.use_llm,
            use_llm_social_copy=settings.use_llm,
            llm_model=settings.llm_model,
            llm_temperature=settings.llm_temperature,
            artifact_dir=artifact_dir,
            video_crf=video_crf,
            initial_prompt=settings.context_prompt,
            transcribe_provider=provider,
            provider_model=settings.openai_model,
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
            watermark_enabled=settings.watermark_enabled,
            check_cancelled=check_cancelled,
            transcription_only=True,
            db=db,
            job_id=job_id,
            ledger_store=ledger_store,
            charge_plan=charge_plan,
            media_probe=effective_probe,
        )
        check_cancelled(force=True)

        # Result unpacking
        social = None
        final_path = output_path
        if isinstance(result, tuple):
            final_path, social = result
        else:
            final_path = result

        logger.debug(
            "process_video_pipeline completed: max_subtitle_lines=%s subtitle_color=%s shadow_strength=%s highlight_style=%s",
            settings.max_subtitle_lines,
            settings.subtitle_color,
            settings.shadow_strength,
            settings.highlight_style,
        )

        public_path = relpath_safe(final_path, data_dir).as_posix()
        artifact_public = relpath_safe(artifact_dir, data_dir).as_posix()

        result_data = {
            "video_path": public_path,
            "artifacts_dir": artifact_public,
            "public_url": f"/static/{public_path}",
            "artifact_url": f"/static/{artifact_public}",
            "transcription_url": f"/static/{artifact_public}/transcription.json",
            "social": social.generic.title_en if social else None,
            "original_filename": original_name or input_path.name,
            "video_crf": video_crf,
            "transcribe_tier": tier,
            "transcribe_provider": provider,
            "output_size": final_path.stat().st_size if final_path.exists() else 0,
            "resolution": f"{target_width}x{target_height}" if target_width and target_height else "",
            "duration_seconds": source_duration_seconds,
            "max_subtitle_lines": settings.max_subtitle_lines,
            "subtitle_position": settings.subtitle_position,
            "subtitle_color": settings.subtitle_color,
            "shadow_strength": settings.shadow_strength,
            "highlight_style": settings.highlight_style,
            "subtitle_size": settings.subtitle_size,
            "karaoke_enabled": settings.karaoke_enabled,
            "watermark_enabled": settings.watermark_enabled,
        }
        if not job_store.update_job_if_status(
            job_id,
            expected_statuses={"processing"},
            status="completed",
            progress=100,
            message="Done!",
            result_data=result_data,
        ):
            raise_for_rejected_worker_write(
                job_store=job_store,
                job_id=job_id,
            )
        if job_store.get_job(job_id) is None:
            raise DeletedJobError("Job was deleted")
        record_event_safe(
            history_store,
            user,
            "process_completed",
            f"Processed {original_name or input_path.name}",
            {
                "job_id": job_id,
                "transcribe_tier": tier,
                "provider": provider,
                "video_crf": video_crf,
                "output": result_data.get("public_url"),
                "artifacts": result_data.get("artifact_url"),
            },
        )

    except ProviderDispatchAlreadyClaimedError:
        logger.info(
            "Skipping duplicate paid provider dispatch",
            extra={"job_id": job_id},
        )
        return
    except JobWorkspaceLockTimeoutError as exc:
        # Another writer/eraser owns the shared workspace stripe. This worker
        # never acquired write authority, so it must not clean or mutate the
        # job that the winning actor is still responsible for.
        logger.info(
            "Skipping video-processing worker while workspace is busy",
            extra={"job_id": job_id, "reason": sanitize_message(str(exc))},
        )
        return
    except StaleWorkerError as exc:
        logger.info(
            "Stopping stale video-processing worker",
            extra={"job_id": job_id, "reason": sanitize_message(str(exc))},
        )
        return
    except DeletedJobError as exc:
        abort_deleted_job(
            job_id=job_id,
            expected_user_id=worker_user_id,
            ledger_store=ledger_store,
            charge_plan=charge_plan,
            error=sanitize_message(str(exc)),
            workspace_lock_held=workspace_lock_held,
        )
    except JobCancellationError as exc:
        current_job = job_store.get_job(job_id)
        if current_job is None:
            abort_deleted_job(
                job_id=job_id,
                expected_user_id=worker_user_id,
                ledger_store=ledger_store,
                charge_plan=charge_plan,
                error=sanitize_message(str(exc)),
                workspace_lock_held=workspace_lock_held,
            )
            return
        try:
            record_and_delete_local_workspace(
                job_id=job_id,
                user_id=current_job.user_id,
                terminal_status="cancelled",
                workspace_lock_held=workspace_lock_held,
            )
        except Exception:
            privacy_error = "Privacy cleanup could not be recorded"
            logger.exception(
                "Refusing unjournaled cancellation cleanup",
                extra={"job_id": job_id},
            )
            disposition = resolve_terminal_cleanup_failure(
                job_store=job_store,
                job_id=job_id,
                privacy_error=privacy_error,
            )
            if disposition == "deleted":
                abort_deleted_job(
                    job_id=job_id,
                    expected_user_id=worker_user_id,
                    ledger_store=ledger_store,
                    charge_plan=charge_plan,
                    error=sanitize_message(str(exc)),
                    workspace_lock_held=workspace_lock_held,
                )
                return
            cancellation_deferred = disposition == "cancellation_deferred"
            record_event_safe(
                history_store,
                user,
                (
                    "process_cancellation_cleanup_deferred"
                    if cancellation_deferred
                    else "process_failed"
                ),
                (
                    f"Cancellation cleanup deferred for {original_name or input_path.name}"
                    if cancellation_deferred
                    else f"Privacy cleanup failed for {original_name or input_path.name}"
                ),
                {"job_id": job_id, "error": privacy_error},
            )
            if disposition in {"failed", "cancellation_deferred"}:
                refund_charge_best_effort(
                    ledger_store,
                    charge_plan,
                    status=(
                        "cancelled"
                        if cancellation_deferred
                        else "failed"
                    ),
                    error=sanitize_message(str(exc)),
                )
            return
        job_store.update_job_if_status(
            job_id,
            expected_statuses={"cancelling"},
            status="cancelled",
            message="Cancelled by user",
        )
        record_event_safe(
            history_store,
            user,
            "process_cancelled",
            f"Processing cancelled for {original_name or input_path.name}",
            {"job_id": job_id, "error": sanitize_message(str(exc))},
        )
        refund_charge_best_effort(ledger_store, charge_plan, status="cancelled", error=sanitize_message(str(exc)))
    except Exception as exc:
        safe_msg = sanitize_message(str(exc))
        current_job = job_store.get_job(job_id)
        if current_job is None:
            abort_deleted_job(
                job_id=job_id,
                expected_user_id=worker_user_id,
                ledger_store=ledger_store,
                charge_plan=charge_plan,
                error=safe_msg,
                workspace_lock_held=workspace_lock_held,
            )
            return
        try:
            record_and_delete_local_workspace(
                job_id=job_id,
                user_id=current_job.user_id,
                terminal_status=(
                    "cancelled"
                    if current_job.status == "cancelling"
                    else "failed"
                ),
                workspace_lock_held=workspace_lock_held,
            )
        except Exception:
            privacy_error = "Privacy cleanup could not be recorded"
            logger.exception(
                "Refusing unjournaled failure cleanup",
                extra={"job_id": job_id},
            )
            disposition = resolve_terminal_cleanup_failure(
                job_store=job_store,
                job_id=job_id,
                privacy_error=privacy_error,
            )
            if disposition == "deleted":
                abort_deleted_job(
                    job_id=job_id,
                    expected_user_id=worker_user_id,
                    ledger_store=ledger_store,
                    charge_plan=charge_plan,
                    error=safe_msg,
                    workspace_lock_held=workspace_lock_held,
                )
                return
            cancellation_deferred = disposition == "cancellation_deferred"
            record_event_safe(
                history_store,
                user,
                (
                    "process_cancellation_cleanup_deferred"
                    if cancellation_deferred
                    else "process_failed"
                ),
                (
                    f"Cancellation cleanup deferred for {original_name or input_path.name}"
                    if cancellation_deferred
                    else f"Privacy cleanup failed for {original_name or input_path.name}"
                ),
                {"job_id": job_id, "error": privacy_error},
            )
            if disposition in {"failed", "cancellation_deferred"}:
                refund_charge_best_effort(
                    ledger_store,
                    charge_plan,
                    status=(
                        "cancelled"
                        if cancellation_deferred
                        else "failed"
                    ),
                    error=safe_msg,
                )
            return
        cancellation_completed = False
        if current_job.status == "cancelling":
            cancellation_completed = job_store.update_job_if_status(
                job_id,
                expected_statuses={"cancelling"},
                status="cancelled",
                message="Cancelled by user",
            )
        if cancellation_completed:
            record_event_safe(
                history_store,
                user,
                "process_cancelled",
                f"Processing cancelled for {original_name or input_path.name}",
                {"job_id": job_id, "error": safe_msg},
            )
            refund_charge_best_effort(
                ledger_store,
                charge_plan,
                status="cancelled",
                error=safe_msg,
            )
            return

        transitioned_to_failed = job_store.update_job_if_status(
            job_id,
            expected_statuses=CANCELLABLE_JOB_STATUSES,
            status="failed",
            message=safe_msg,
        )
        if not transitioned_to_failed:
            latest_job = job_store.get_job(job_id)
            if latest_job is None:
                abort_deleted_job(
                    job_id=job_id,
                    expected_user_id=worker_user_id,
                    ledger_store=ledger_store,
                    charge_plan=charge_plan,
                    error=safe_msg,
                    workspace_lock_held=workspace_lock_held,
                )
                return
            if latest_job.status == "cancelling":
                try:
                    record_and_delete_local_workspace(
                        job_id=job_id,
                        user_id=latest_job.user_id,
                        terminal_status="cancelled",
                        workspace_lock_held=workspace_lock_held,
                    )
                except Exception:
                    logger.exception(
                        "Deferring raced cancellation until its intent is durable",
                        extra={"job_id": job_id},
                    )
                    record_event_safe(
                        history_store,
                        user,
                        "process_cancellation_cleanup_deferred",
                        (
                            "Cancellation cleanup deferred for "
                            f"{original_name or input_path.name}"
                        ),
                        {"job_id": job_id, "error": safe_msg},
                    )
                    refund_charge_best_effort(
                        ledger_store,
                        charge_plan,
                        status="cancelled",
                        error=safe_msg,
                    )
                    return
                cancellation_completed = job_store.update_job_if_status(
                    job_id,
                    expected_statuses={"cancelling"},
                    status="cancelled",
                    message="Cancelled by user",
                )
                if cancellation_completed:
                    latest_job = job_store.get_job(job_id)
                    if latest_job is None:
                        abort_deleted_job(
                            job_id=job_id,
                            expected_user_id=worker_user_id,
                            ledger_store=ledger_store,
                            charge_plan=charge_plan,
                            error=safe_msg,
                            workspace_lock_held=workspace_lock_held,
                        )
                        return
            if latest_job is not None and latest_job.status == "cancelled":
                record_event_safe(
                    history_store,
                    user,
                    "process_cancelled",
                    f"Processing cancelled for {original_name or input_path.name}",
                    {"job_id": job_id, "error": safe_msg},
                )
                refund_charge_best_effort(
                    ledger_store,
                    charge_plan,
                    status="cancelled",
                    error=safe_msg,
                )
                return
            logger.info(
                "Not overwriting terminal job after worker failure",
                extra={"job_id": job_id, "status": latest_job.status},
            )
            return
        record_event_safe(
            history_store,
            user,
            "process_failed",
            f"Processing failed for {original_name or input_path.name}",
            {"job_id": job_id, "error": safe_msg},
        )
        refund_charge_best_effort(ledger_store, charge_plan, status="failed", error=safe_msg)
    finally:
        if workspace_lock is not None and workspace_lock_held:
            workspace_lock.__exit__(None, None, None)
