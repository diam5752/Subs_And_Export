"""Billing-aware, replayable account and media erasure."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import delete, select

from backend.app.core.auth import UserStore
from backend.app.core.database import Database
from backend.app.core.erasure_journal import (
    ErasureJournal,
    ErasureTombstone,
    JobTerminalErasureTombstone,
)
from backend.app.core.job_lifecycle import ACTIVE_JOB_STATUSES
from backend.app.core.workspace_deletion import (
    UPLOAD_SUFFIXES,
    delete_job_workspace,
    lock_account_lifecycle,
    lock_job_workspaces,
)
from backend.app.core.workspace_ownership import (
    get_workspace_owner,
    list_owned_workspace_ids,
    remove_workspace_ownership_after_verified_cleanup,
)
from backend.app.db.models import (
    DbJob,
    DbProviderBudgetReservation,
    DbTokenUsage,
    DbUsageLedger,
    DbUser,
)
from backend.app.services.billing import BillingService
from backend.app.services.product_feedback import (
    acquire_feedback_account_delivery_lock,
)


class ActiveAccountJobsError(RuntimeError):
    """Raised when an interactive erasure races active processing."""


class ErasureReplayConflictError(RuntimeError):
    """Raised when restored state does not match an authoritative tombstone."""


@dataclass(frozen=True, slots=True)
class AccountErasureReport:
    account_found: bool
    deleted_job_ids: list[str]


def _journal_owned_job_ids(
    *,
    journal: ErasureJournal,
    user_id: str,
) -> set[str]:
    """Return only canonical workspaces durably attributed to this account."""
    entries = [
        entry for entry in journal.read_all() if isinstance(entry, (ErasureTombstone, JobTerminalErasureTombstone))
    ]
    owned_ids = {job_id for entry in entries if entry.user_id == user_id for job_id in entry.job_ids}
    if any(entry.user_id != user_id and any(job_id in owned_ids for job_id in entry.job_ids) for entry in entries):
        raise ErasureReplayConflictError(
            "Workspace ownership conflicts across erasure intents",
        )
    return owned_ids


def _workspace_media_remains(
    *,
    job_id: str,
    uploads_dir: Path,
    artifacts_root: Path,
) -> bool:
    """Check only the exact upload/artifact coordinates owned by one job ID."""
    artifact_path = artifacts_root / job_id
    if artifact_path.exists() or artifact_path.is_symlink():
        return True
    if not uploads_dir.exists():
        return False
    expected_stem = f"{job_id}_input"
    return any(item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES for item in uploads_dir.iterdir())


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
    """Erase an account behind the exclusive media-lifecycle barrier."""
    with lock_account_lifecycle(
        data_dir=data_dir,
        user_id=user_id,
        shared=False,
    ):
        return _erase_account_and_media_locked(
            db=db,
            billing_service=billing_service,
            user_store=user_store,
            user_id=user_id,
            data_dir=data_dir,
            journal=journal,
            expected_job_ids=expected_job_ids,
            require_terminal_jobs=require_terminal_jobs,
        )


def _erase_account_and_media_locked(
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
    """Erase locally while the caller holds the exclusive account barrier."""
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    expected_ids = set(expected_job_ids) if expected_job_ids is not None else None
    marker_owned_ids = set(
        list_owned_workspace_ids(data_dir=data_dir, user_id=user_id),
    )
    if expected_ids is None:
        journal_owned_ids = _journal_owned_job_ids(journal=journal, user_id=user_id) if journal is not None else set()
        with db.session() as discovery_session:
            database_job_ids = set(
                discovery_session.scalars(
                    select(DbJob.id).where(DbJob.user_id == user_id).order_by(DbJob.created_at.asc(), DbJob.id.asc()),
                ).all(),
            )
        deletion_job_ids = sorted(
            database_job_ids | journal_owned_ids | marker_owned_ids,
        )
    else:
        expected_ids.update(marker_owned_ids)
        deletion_job_ids = sorted(expected_ids)
    locked_job_ids = set(deletion_job_ids)

    # Filesystem locks must precede database row locks. An exporter holds the
    # same file lock and updates its job row before releasing it; reversing
    # this order would deadlock account deletion against that final update.
    with lock_job_workspaces(data_dir=data_dir, job_ids=deletion_job_ids):
        with db.session() as session:
            acquire_feedback_account_delivery_lock(session, user_id)
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
            recorded_jobs = (
                list(
                    session.scalars(
                        select(DbJob).where(DbJob.id.in_(deletion_job_ids)).with_for_update(),
                    ).all(),
                )
                if deletion_job_ids
                else []
            )
            if any(job.user_id != user_id for job in recorded_jobs):
                raise ErasureReplayConflictError(
                    "Restored project ownership conflicts with erasure intent",
                )
            for job_id in deletion_job_ids:
                marker_owner = get_workspace_owner(
                    data_dir=data_dir,
                    job_id=job_id,
                )
                if marker_owner is not None and marker_owner != user_id:
                    raise ErasureReplayConflictError(
                        "Workspace ownership marker conflicts with account deletion",
                    )

            if expected_ids is not None:
                if not current_job_ids.issubset(expected_ids):
                    raise ErasureReplayConflictError("Restored account contains an unrecorded project")
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
                    expected_user_id=user_id,
                )
                if _workspace_media_remains(
                    job_id=job_id,
                    uploads_dir=uploads_dir,
                    artifacts_root=artifacts_root,
                ):
                    raise RuntimeError(
                        "Account media cleanup could not be verified",
                    )
                remove_workspace_ownership_after_verified_cleanup(
                    data_dir=data_dir,
                    job_id=job_id,
                    expected_user_id=user_id,
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
