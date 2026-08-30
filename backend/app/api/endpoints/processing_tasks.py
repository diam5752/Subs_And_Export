"""Background processing tasks for video processing endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ...core.auth import User
from ...core.database import Database
from ...core.erasure_journal import JobTerminalStatus, configured_erasure_journal
from ...core.errors import ProviderDispatchAlreadyClaimedError, sanitize_message
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
from .processing_events import record_event_safe as _record_event_safe
from .processing_state import (
    DeletedJobError,
    JobCancellationError,
    StaleWorkerError,
    raise_for_rejected_worker_write,
    resolve_terminal_cleanup_failure,
)
from .processing_worker_failures import (
    WorkerFailureCallbacks,
    WorkerFailureContext,
    handle_deleted_worker,
    handle_worker_cancellation,
    handle_worker_failure,
)
from .processing_worker_runtime import (
    WorkerExecutionContext,
    WorkerRuntime,
    run_processing_success,
)
from .settings import ProcessingSettings

logger = logging.getLogger(__name__)


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

    reservation = charge_plan.transcription
    if reservation:
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
    _record_event_safe(history_store, user, kind, summary, data, logger=logger)


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


def _worker_runtime() -> WorkerRuntime:
    return WorkerRuntime(
        process_pipeline=process_video_pipeline,
        resolve_provider=resolve_runtime_transcribe_provider,
        resolve_video_crf=crf_for_video_quality,
        probe_media=probe_media,
        relative_path=relpath_safe,
        data_roots=data_roots,
        raise_for_rejected_write=raise_for_rejected_worker_write,
        record_event=record_event_safe,
    )


def _worker_failure_context(
    execution: WorkerExecutionContext,
    *,
    worker_user_id: str | None,
    workspace_lock_held: bool,
) -> WorkerFailureContext:
    return WorkerFailureContext(
        job_id=execution.job_id,
        input_path=execution.input_path,
        job_store=execution.job_store,
        history_store=execution.history_store,
        user=execution.user,
        original_name=execution.original_name,
        ledger_store=execution.ledger_store,
        charge_plan=execution.charge_plan,
        worker_user_id=worker_user_id,
        workspace_lock_held=workspace_lock_held,
    )


def _worker_failure_callbacks() -> WorkerFailureCallbacks:
    return WorkerFailureCallbacks(
        abort_deleted=abort_deleted_job,
        record_and_delete_workspace=record_and_delete_local_workspace,
        resolve_cleanup_failure=resolve_terminal_cleanup_failure,
        record_event=record_event_safe,
        refund_charge=refund_charge_best_effort,
    )


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
    source_probe: MediaProbe | None = None,
) -> None:
    """Background task to run the heavy video processing."""
    execution = WorkerExecutionContext(
        job_id=job_id,
        input_path=input_path,
        output_path=output_path,
        artifact_dir=artifact_dir,
        settings=settings,
        job_store=job_store,
        history_store=history_store,
        user=user,
        original_name=original_name,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=source_probe,
    )
    runtime = _worker_runtime()
    failure_callbacks = _worker_failure_callbacks()
    worker_user_id = user.id if user is not None else None
    workspace_lock: Any = None
    workspace_lock_held = False
    try:
        data_dir, _, _ = data_roots()
        workspace_lock = lock_job_workspace(data_dir=data_dir, job_id=job_id)
        workspace_lock.__enter__()
        workspace_lock_held = True
        run_processing_success(execution, runtime)
    except ProviderDispatchAlreadyClaimedError:
        logger.info(
            "Skipping duplicate paid provider dispatch",
            extra={"job_id": job_id},
        )
    except JobWorkspaceLockTimeoutError as exc:
        logger.info(
            "Skipping video-processing worker while workspace is busy",
            extra={"job_id": job_id, "reason": sanitize_message(str(exc))},
        )
    except StaleWorkerError as exc:
        logger.info(
            "Stopping stale video-processing worker",
            extra={"job_id": job_id, "reason": sanitize_message(str(exc))},
        )
    except DeletedJobError as exc:
        handle_deleted_worker(
            _worker_failure_context(
                execution,
                worker_user_id=worker_user_id,
                workspace_lock_held=workspace_lock_held,
            ),
            failure_callbacks,
            exc,
        )
    except JobCancellationError as exc:
        handle_worker_cancellation(
            _worker_failure_context(
                execution,
                worker_user_id=worker_user_id,
                workspace_lock_held=workspace_lock_held,
            ),
            failure_callbacks,
            exc,
        )
    except Exception as exc:
        handle_worker_failure(
            _worker_failure_context(
                execution,
                worker_user_id=worker_user_id,
                workspace_lock_held=workspace_lock_held,
            ),
            failure_callbacks,
            exc,
        )
    finally:
        if workspace_lock is not None and workspace_lock_held:
            workspace_lock.__exit__(None, None, None)
