"""Authoritative worker-state transitions shared by processing tasks."""

from typing import Literal

from ...core.job_lifecycle import CANCELLABLE_JOB_STATUSES
from ...services.jobs import JobStore


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
    raise StaleWorkerError(f"Job is no longer processing (status={current_job.status})")


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
