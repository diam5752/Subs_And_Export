"""Fail-closed recovery for media jobs interrupted by a service restart."""

from __future__ import annotations

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.erasure_journal import configured_erasure_journal
from backend.app.core.workspace_deletion import (
    delete_job_workspace,
    lock_job_workspace,
)
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import UsageLedgerStore

_INTERRUPTED_JOB_STATUSES = frozenset({"pending", "processing"})
_RESTART_FAILURE_MESSAGE = (
    "Processing was interrupted by a service restart. Reserved credits were refunded; please try again."
)


def reconcile_interrupted_media_jobs(db: Database) -> int:
    """Refund and fail every worker-owned job left by the previous process."""
    job_store = JobStore(db=db)
    ledger_store = UsageLedgerStore(
        db=db,
        points_store=PointsStore(db=db),
    )
    data_dir = settings.data_dir
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    journal = configured_erasure_journal()
    reconciled = 0

    for candidate in job_store.list_jobs_with_statuses(
        _INTERRUPTED_JOB_STATUSES,
    ):
        with lock_job_workspace(data_dir=data_dir, job_id=candidate.id):
            current_job = job_store.get_job(candidate.id)
            if current_job is None or current_job.status not in _INTERRUPTED_JOB_STATUSES:
                continue

            journal.append_job_terminal(
                user_id=current_job.user_id,
                job_ids=[current_job.id],
                terminal_status="failed",
            )
            delete_job_workspace(
                job_id=current_job.id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_dir,
                expected_user_id=current_job.user_id,
            )
            ledger_store.fail_job_reservations(
                current_job.id,
                error="Processing interrupted by service restart",
                status="failed",
            )
            transitioned = job_store.update_job_if_status(
                current_job.id,
                expected_statuses=_INTERRUPTED_JOB_STATUSES,
                status="failed",
                message=_RESTART_FAILURE_MESSAGE,
            )
            if not transitioned:
                latest_job = job_store.get_job(current_job.id)
                if latest_job is None or latest_job.status != "failed":
                    raise RuntimeError(
                        "Interrupted media job changed state during startup recovery",
                    )
            reconciled += 1

    return reconciled
