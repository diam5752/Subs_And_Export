"""Terminal failure and cancellation paths for processing workers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ...core.auth import User
from ...core.errors import sanitize_message
from ...core.job_lifecycle import CANCELLABLE_JOB_STATUSES
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.usage_ledger import ChargePlan, UsageLedgerStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerFailureContext:
    job_id: str
    input_path: Path
    job_store: JobStore
    history_store: HistoryStore | None
    user: User | None
    original_name: str | None
    ledger_store: UsageLedgerStore | None
    charge_plan: ChargePlan | None
    worker_user_id: str | None
    workspace_lock_held: bool

    @property
    def display_name(self) -> str:
        return self.original_name or self.input_path.name


@dataclass(frozen=True)
class WorkerFailureCallbacks:
    abort_deleted: Callable[..., None]
    record_and_delete_workspace: Callable[..., None]
    resolve_cleanup_failure: Callable[..., str]
    record_event: Callable[..., None]
    refund_charge: Callable[..., None]


def _abort_deleted_job(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    *,
    error: str,
) -> None:
    callbacks.abort_deleted(
        job_id=context.job_id,
        expected_user_id=context.worker_user_id,
        ledger_store=context.ledger_store,
        charge_plan=context.charge_plan,
        error=error,
        workspace_lock_held=context.workspace_lock_held,
    )


def _record_terminal_event(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    *,
    status: str,
    error: str,
) -> None:
    callbacks.record_event(
        context.history_store,
        context.user,
        f"process_{status}",
        f"Processing {status} for {context.display_name}",
        {"job_id": context.job_id, "error": error},
    )
    callbacks.refund_charge(
        context.ledger_store,
        context.charge_plan,
        status=status,
        error=error,
    )


def _handle_unjournaled_cleanup(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    *,
    original_error: str,
    log_message: str,
) -> None:
    privacy_error = "Privacy cleanup could not be recorded"
    logger.exception(log_message, extra={"job_id": context.job_id})
    disposition = callbacks.resolve_cleanup_failure(
        job_store=context.job_store,
        job_id=context.job_id,
        privacy_error=privacy_error,
    )
    if disposition == "deleted":
        _abort_deleted_job(
            context,
            callbacks,
            error=original_error,
        )
        return
    cancellation_deferred = disposition == "cancellation_deferred"
    callbacks.record_event(
        context.history_store,
        context.user,
        ("process_cancellation_cleanup_deferred" if cancellation_deferred else "process_failed"),
        (
            f"Cancellation cleanup deferred for {context.display_name}"
            if cancellation_deferred
            else f"Privacy cleanup failed for {context.display_name}"
        ),
        {"job_id": context.job_id, "error": privacy_error},
    )
    if disposition in {"failed", "cancellation_deferred"}:
        callbacks.refund_charge(
            context.ledger_store,
            context.charge_plan,
            status="cancelled" if cancellation_deferred else "failed",
            error=original_error,
        )


def handle_deleted_worker(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    error: Exception,
) -> None:
    _abort_deleted_job(
        context,
        callbacks,
        error=sanitize_message(str(error)),
    )


def handle_worker_cancellation(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    error: Exception,
) -> None:
    safe_error = sanitize_message(str(error))
    current_job = context.job_store.get_job(context.job_id)
    if current_job is None:
        _abort_deleted_job(context, callbacks, error=safe_error)
        return
    try:
        callbacks.record_and_delete_workspace(
            job_id=context.job_id,
            user_id=current_job.user_id,
            terminal_status="cancelled",
            workspace_lock_held=context.workspace_lock_held,
        )
    except Exception:
        _handle_unjournaled_cleanup(
            context,
            callbacks,
            original_error=safe_error,
            log_message="Refusing unjournaled cancellation cleanup",
        )
        return
    context.job_store.update_job_if_status(
        context.job_id,
        expected_statuses={"cancelling"},
        status="cancelled",
        message="Cancelled by user",
    )
    _record_terminal_event(
        context,
        callbacks,
        status="cancelled",
        error=safe_error,
    )


def _handle_raced_cancellation(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    *,
    latest_job: Any,
    safe_error: str,
) -> Any | None:
    try:
        callbacks.record_and_delete_workspace(
            job_id=context.job_id,
            user_id=latest_job.user_id,
            terminal_status="cancelled",
            workspace_lock_held=context.workspace_lock_held,
        )
    except Exception:
        logger.exception(
            "Deferring raced cancellation until its intent is durable",
            extra={"job_id": context.job_id},
        )
        callbacks.record_event(
            context.history_store,
            context.user,
            "process_cancellation_cleanup_deferred",
            f"Cancellation cleanup deferred for {context.display_name}",
            {"job_id": context.job_id, "error": safe_error},
        )
        callbacks.refund_charge(
            context.ledger_store,
            context.charge_plan,
            status="cancelled",
            error=safe_error,
        )
        return None
    cancellation_completed = context.job_store.update_job_if_status(
        context.job_id,
        expected_statuses={"cancelling"},
        status="cancelled",
        message="Cancelled by user",
    )
    if not cancellation_completed:
        return latest_job
    latest_job = context.job_store.get_job(context.job_id)
    if latest_job is None:
        _abort_deleted_job(context, callbacks, error=safe_error)
    return latest_job


def _handle_failed_transition_race(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    *,
    safe_error: str,
) -> None:
    latest_job = context.job_store.get_job(context.job_id)
    if latest_job is None:
        _abort_deleted_job(context, callbacks, error=safe_error)
        return
    if latest_job.status == "cancelling":
        latest_job = _handle_raced_cancellation(
            context,
            callbacks,
            latest_job=latest_job,
            safe_error=safe_error,
        )
        if latest_job is None:
            return
    if latest_job.status == "cancelled":
        _record_terminal_event(
            context,
            callbacks,
            status="cancelled",
            error=safe_error,
        )
        return
    logger.info(
        "Not overwriting terminal job after worker failure",
        extra={"job_id": context.job_id, "status": latest_job.status},
    )


def handle_worker_failure(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    error: Exception,
) -> None:
    safe_error = sanitize_message(str(error))
    current_job = context.job_store.get_job(context.job_id)
    if current_job is None:
        _abort_deleted_job(context, callbacks, error=safe_error)
        return
    if not _record_failed_workspace_cleanup(
        context,
        callbacks,
        current_user_id=current_job.user_id,
        current_status=current_job.status,
        safe_error=safe_error,
    ):
        return
    _transition_failed_worker(
        context,
        callbacks,
        current_status=current_job.status,
        safe_error=safe_error,
    )


def _record_failed_workspace_cleanup(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    *,
    current_user_id: str,
    current_status: str,
    safe_error: str,
) -> bool:
    try:
        callbacks.record_and_delete_workspace(
            job_id=context.job_id,
            user_id=current_user_id,
            terminal_status=("cancelled" if current_status == "cancelling" else "failed"),
            workspace_lock_held=context.workspace_lock_held,
        )
    except Exception:
        _handle_unjournaled_cleanup(
            context,
            callbacks,
            original_error=safe_error,
            log_message="Refusing unjournaled failure cleanup",
        )
        return False
    return True


def _transition_failed_worker(
    context: WorkerFailureContext,
    callbacks: WorkerFailureCallbacks,
    *,
    current_status: str,
    safe_error: str,
) -> None:
    if current_status == "cancelling" and context.job_store.update_job_if_status(
        context.job_id,
        expected_statuses={"cancelling"},
        status="cancelled",
        message="Cancelled by user",
    ):
        _record_terminal_event(
            context,
            callbacks,
            status="cancelled",
            error=safe_error,
        )
        return
    if not context.job_store.update_job_if_status(
        context.job_id,
        expected_statuses=CANCELLABLE_JOB_STATUSES,
        status="failed",
        message=safe_error,
    ):
        _handle_failed_transition_race(
            context,
            callbacks,
            safe_error=safe_error,
        )
        return
    _record_terminal_event(
        context,
        callbacks,
        status="failed",
        error=safe_error,
    )
