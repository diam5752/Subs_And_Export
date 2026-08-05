"""Billing-aware, replayable account and media erasure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select

from backend.app.core.auth import UserStore
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournal
from backend.app.core.workspace_deletion import (
    delete_job_workspace,
    lock_job_workspaces,
)
from backend.app.db.models import (
    DbJob,
    DbProviderBudgetReservation,
    DbTokenUsage,
    DbUsageLedger,
    DbUser,
)
from backend.app.services.billing import BillingService

ACTIVE_JOB_STATUSES = frozenset({"pending", "processing"})


class ActiveAccountJobsError(RuntimeError):
    """Raised when an interactive erasure races active processing."""


class ErasureReplayConflictError(RuntimeError):
    """Raised when restored state does not match an authoritative tombstone."""


@dataclass(frozen=True, slots=True)
class AccountErasureReport:
    account_found: bool
    deleted_job_ids: list[str]


def erase_account_and_media(
    *,
    db: Database,
    billing_service: BillingService,
    user_store: UserStore,
    user_id: str,
    data_dir: Path,
    journal: ErasureJournal | None,
    expected_job_ids: list[str] | None = None,
    require_terminal_jobs: bool = True,
) -> AccountErasureReport:
    """Erase an account locally while retaining detached financial records."""
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    expected_ids = set(expected_job_ids) if expected_job_ids is not None else None
    if expected_ids is None:
        with db.session() as discovery_session:
            deletion_job_ids = list(
                discovery_session.scalars(
                    select(DbJob.id)
                    .where(DbJob.user_id == user_id)
                    .order_by(DbJob.created_at.asc(), DbJob.id.asc()),
                ).all(),
            )
    else:
        deletion_job_ids = sorted(expected_ids)
    locked_job_ids = set(deletion_job_ids)

    # Filesystem locks must precede database row locks. An exporter holds the
    # same file lock and updates its job row before releasing it; reversing
    # this order would deadlock account deletion against that final update.
    with lock_job_workspaces(data_dir=data_dir, job_ids=deletion_job_ids):
        with db.session() as session:
            billing_service.prepare_account_deletion(
                session=session,
                user_id=user_id,
            )
            locked_user = session.scalar(
                select(DbUser).where(DbUser.id == user_id).with_for_update(),
            )
            jobs = list(
                session.scalars(
                    select(DbJob)
                    .where(DbJob.user_id == user_id)
                    .order_by(DbJob.created_at.asc(), DbJob.id.asc())
                    .with_for_update(),
                ).all(),
            )
            current_job_ids = {job.id for job in jobs}

            if expected_ids is not None:
                if not current_job_ids.issubset(expected_ids):
                    raise ErasureReplayConflictError("Restored account contains an unrecorded project")
                restored_recorded_jobs = list(
                    session.scalars(
                        select(DbJob).where(DbJob.id.in_(expected_ids)).with_for_update(),
                    ).all(),
                ) if expected_ids else []
                if any(job.user_id != user_id for job in restored_recorded_jobs):
                    raise ErasureReplayConflictError("Restored project ownership conflicts with erasure intent")
            elif not current_job_ids.issubset(locked_job_ids):
                # A new project appeared after discovery. Fail closed instead
                # of deleting a workspace whose exporter we did not lock.
                raise ActiveAccountJobsError("Account jobs changed during deletion")

            if require_terminal_jobs and any(job.status in ACTIVE_JOB_STATUSES for job in jobs):
                raise ActiveAccountJobsError("Account has active media processing")
            if locked_user is None and expected_ids is None:
                raise RuntimeError("Account is no longer available")

            if journal is not None:
                journal.append(
                    kind="account",
                    user_id=user_id,
                    job_ids=deletion_job_ids,
                )

            for job_id in deletion_job_ids:
                delete_job_workspace(
                    job_id=job_id,
                    uploads_dir=uploads_dir,
                    artifacts_dir=artifacts_root,
                )

            if deletion_job_ids:
                session.execute(
                    delete(DbTokenUsage).where(
                        DbTokenUsage.job_id.in_(deletion_job_ids),
                    ),
                )
            usage_idempotency_keys = list(
                session.scalars(
                    select(DbUsageLedger.idempotency_key).where(
                        DbUsageLedger.user_id == user_id,
                        DbUsageLedger.idempotency_key.is_not(None),
                    ),
                ).all(),
            )
            if usage_idempotency_keys:
                session.execute(
                    delete(DbProviderBudgetReservation).where(
                        DbProviderBudgetReservation.idempotency_key.in_(usage_idempotency_keys),
                    ),
                )

            if locked_user is not None:
                user_store.delete_user_in_session(session, user_id)

    return AccountErasureReport(
        account_found=locked_user is not None,
        deleted_job_ids=deletion_job_ids,
    )
