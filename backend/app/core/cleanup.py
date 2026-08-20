from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from .config import settings
from .erasure_journal import ErasureJournal, configured_erasure_journal
from .job_lifecycle import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES
from .workspace_deletion import (
    UPLOAD_SUFFIXES,
    delete_job_workspace,
    delete_local_path,
    lock_job_workspace,
    reclaim_abandoned_lifecycle_locks,
)
from .workspace_ownership import (
    get_workspace_owner,
    list_workspace_ownership_markers,
    remove_workspace_ownership_after_verified_cleanup,
)

if TYPE_CHECKING:
    from .database import Database

logger = logging.getLogger(__name__)

MEBIBYTE = 1024 * 1024


class RetentionJob(Protocol):
    id: str
    user_id: str
    status: str
    updated_at: int


class RetentionJobStore(Protocol):
    def list_jobs_updated_before(
        self,
        timestamp: int,
        statuses: set[str] | frozenset[str],
    ) -> Sequence[RetentionJob]: ...

    def get_job(self, job_id: str) -> RetentionJob | None: ...

    def delete_job(self, job_id: str) -> None: ...


class RetentionHistoryStore(Protocol):
    def delete_job_events(self, job_ids: list[str]) -> int: ...


@dataclass(frozen=True, slots=True)
class CleanupReport:
    deleted_job_ids: list[str]
    failed_job_ids: list[str]
    deleted_orphan_items: int
    failed_orphan_items: int = 0


def cleanup_expired_workspaces(
    *,
    job_store: RetentionJobStore,
    history_store: RetentionHistoryStore,
    uploads_dir: Path,
    artifacts_dir: Path,
    workspace_retention_hours: int,
    stale_job_retention_hours: int,
    orphan_retention_hours: int,
    erasure_journal: ErasureJournal,
    now: int | None = None,
    before_delete_job: Callable[[RetentionJob], None] | None = None,
) -> CleanupReport:
    """Delete expired media workspaces while preserving recent and active work."""
    current_time = int(time.time()) if now is None else now
    terminal_cutoff = current_time - (workspace_retention_hours * 3600)
    active_cutoff = current_time - (stale_job_retention_hours * 3600)

    terminal_jobs = job_store.list_jobs_updated_before(
        terminal_cutoff,
        TERMINAL_JOB_STATUSES,
    )
    stale_active_jobs = job_store.list_jobs_updated_before(
        active_cutoff,
        ACTIVE_JOB_STATUSES,
    )
    candidates = {job.id: job for job in (*terminal_jobs, *stale_active_jobs)}

    deleted_job_ids: list[str] = []
    failed_job_ids: list[str] = []
    for job_id in sorted(candidates):
        try:
            with lock_job_workspace(data_dir=artifacts_dir.parent, job_id=job_id):
                latest_job = job_store.get_job(job_id)
                if latest_job is None or not _job_is_expired(
                    latest_job,
                    terminal_cutoff=terminal_cutoff,
                    active_cutoff=active_cutoff,
                ):
                    continue
                if (
                    latest_job.status in ACTIVE_JOB_STATUSES
                    and before_delete_job is not None
                ):
                    before_delete_job(latest_job)
                erasure_journal.append(
                    kind="job",
                    user_id=latest_job.user_id,
                    job_ids=[job_id],
                    now=current_time,
                )
                delete_job_workspace(
                    job_id=job_id,
                    uploads_dir=uploads_dir,
                    artifacts_dir=artifacts_dir,
                    expected_user_id=latest_job.user_id,
                )
                history_store.delete_job_events([job_id])
                job_store.delete_job(job_id)
                deleted_job_ids.append(job_id)
        except Exception:
            failed_job_ids.append(job_id)
            logger.exception("Workspace cleanup failed", extra={"job_id": job_id})

    orphan_cutoff = current_time - (orphan_retention_hours * 3600)
    deleted_orphan_uploads, failed_orphan_uploads = _cleanup_orphan_uploads(
        uploads_dir,
        cutoff_time=orphan_cutoff,
        job_store=job_store,
        erasure_journal=erasure_journal,
        now=current_time,
    )
    deleted_orphan_artifacts, failed_orphan_artifacts = _cleanup_orphan_artifacts(
        artifacts_dir,
        cutoff_time=orphan_cutoff,
        job_store=job_store,
        erasure_journal=erasure_journal,
        now=current_time,
    )
    deleted_orphan_markers, failed_orphan_markers = _cleanup_orphan_ownership_markers(
        data_dir=artifacts_dir.parent,
        cutoff_time=orphan_cutoff,
        job_store=job_store,
    )

    deleted_orphan_items = (
        deleted_orphan_uploads
        + deleted_orphan_artifacts
        + deleted_orphan_markers
    )
    failed_orphan_items = (
        failed_orphan_uploads
        + failed_orphan_artifacts
        + failed_orphan_markers
    )

    if deleted_job_ids or failed_job_ids or deleted_orphan_items or failed_orphan_items:
        logger.info(
            "Workspace retention complete",
            extra={
                "deleted_jobs": len(deleted_job_ids),
                "failed_jobs": len(failed_job_ids),
                "deleted_orphans": deleted_orphan_items,
                "failed_orphans": failed_orphan_items,
            },
        )
    return CleanupReport(
        deleted_job_ids=deleted_job_ids,
        failed_job_ids=failed_job_ids,
        deleted_orphan_items=deleted_orphan_items,
        failed_orphan_items=failed_orphan_items,
    )


def _job_is_expired(
    job: RetentionJob,
    *,
    terminal_cutoff: int,
    active_cutoff: int,
) -> bool:
    if job.status in TERMINAL_JOB_STATUSES:
        return job.updated_at < terminal_cutoff
    if job.status in ACTIVE_JOB_STATUSES:
        return job.updated_at < active_cutoff
    return False


def ensure_storage_capacity(
    data_dir: Path,
    *,
    required_bytes: int,
    minimum_free_mb: int,
    cleanup_callback: Callable[[], object] | None = None,
) -> bool:
    """Reserve free space for an operation, retrying once after safe cleanup."""
    required_free = max(0, required_bytes) + (minimum_free_mb * MEBIBYTE)
    if shutil.disk_usage(data_dir).free >= required_free:
        return True

    if cleanup_callback is not None:
        try:
            cleanup_callback()
        except Exception:
            logger.exception("Preflight workspace cleanup failed")

    return shutil.disk_usage(data_dir).free >= required_free


def run_configured_retention(db: Database) -> CleanupReport:
    """Run one retention pass using the live app configuration."""
    from backend.app.services.billing_retention import (
        cleanup_expired_billing_records,
    )
    from backend.app.services.erasure_reconciliation import reconcile_erasure_journal
    from backend.app.services.history import HistoryStore
    from backend.app.services.jobs import JobStore
    from backend.app.services.points import PointsStore
    from backend.app.services.usage_ledger import UsageLedgerStore

    uploads_dir = settings.data_dir / "uploads"
    artifacts_dir = settings.data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    reclaimed_locks = reclaim_abandoned_lifecycle_locks(
        data_dir=settings.data_dir,
    )
    if reclaimed_locks:
        logger.warning(
            "Reclaimed abandoned media lifecycle locks during retention",
            extra={"reclaimed_locks": reclaimed_locks},
        )
    erasure_journal = configured_erasure_journal()
    usage_ledger_store = UsageLedgerStore(
        db=db,
        points_store=PointsStore(db=db),
    )
    stale_before = int(time.time()) - (
        settings.stale_job_retention_hours * 3600
    )
    reconciled = usage_ledger_store.reconcile_stale_reservations(
        stale_before=stale_before,
    )
    if reconciled:
        logger.warning(
            "Reconciled stale paid provider reservations",
            extra={"reconciled_reservations": reconciled},
        )

    def compensate_stale_job(job: RetentionJob) -> None:
        usage_ledger_store.fail_job_reservations(
            job.id,
            error="Stale processing job expired",
        )

    report = cleanup_expired_workspaces(
        job_store=JobStore(db),
        history_store=HistoryStore(db),
        uploads_dir=uploads_dir,
        artifacts_dir=artifacts_dir,
        workspace_retention_hours=settings.workspace_retention_hours,
        stale_job_retention_hours=settings.stale_job_retention_hours,
        orphan_retention_hours=settings.orphan_retention_hours,
        erasure_journal=erasure_journal,
        before_delete_job=compensate_stale_job,
    )
    billing_report = cleanup_expired_billing_records(db)
    if billing_report.deleted_unpaid_attempts or billing_report.deleted_financial_records:
        logger.info(
            "Billing retention complete",
            extra={
                "deleted_unpaid_attempts": (billing_report.deleted_unpaid_attempts),
                "deleted_financial_records": (billing_report.deleted_financial_records),
            },
        )
    # Provider replay is deliberately last. A temporary ElevenLabs deletion
    # outage must fail the pass for alerting without postponing deletion of
    # expired local media. Restore/deploy still runs a separate mandatory
    # reconciliation while the public edge is closed.
    reconcile_erasure_journal(
        db=db,
        data_dir=settings.data_dir,
        journal=erasure_journal,
    )
    return report


async def retention_worker(db: Database) -> None:
    """Delay the first cleanup and then run at the configured bounded interval."""
    while True:
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)
        try:
            await asyncio.to_thread(run_configured_retention, db)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Scheduled workspace cleanup failed",
                extra={"data": {"error_type": type(exc).__name__}},
            )


def _cleanup_orphan_uploads(
    uploads_dir: Path,
    *,
    cutoff_time: float,
    job_store: RetentionJobStore,
    erasure_journal: ErasureJournal,
    now: int,
) -> tuple[int, int]:
    if not uploads_dir.exists():
        return 0, 0
    deleted = 0
    failed = 0
    for item in uploads_dir.iterdir():
        if item.name == ".gitkeep" or not _is_older_than(item, cutoff_time):
            continue
        job_id = _upload_job_id(item)
        if job_id is None:
            logger.warning("Preserving unrecognized orphan upload for manual privacy review")
            failed += 1
            continue
        if job_store.get_job(job_id) is not None:
            continue
        try:
            with lock_job_workspace(data_dir=uploads_dir.parent, job_id=job_id):
                if not _is_older_than(item, cutoff_time):
                    continue
                if job_store.get_job(job_id) is not None:
                    continue
                erasure_journal.append_orphan_workspace(
                    job_ids=[job_id],
                    now=now,
                )
                delete_local_path(item)
                deleted += 1
        except Exception:
            failed += 1
            logger.exception("Failed to delete orphan upload")
    return deleted, failed


def _cleanup_orphan_artifacts(
    artifacts_dir: Path,
    *,
    cutoff_time: float,
    job_store: RetentionJobStore,
    erasure_journal: ErasureJournal,
    now: int,
) -> tuple[int, int]:
    if not artifacts_dir.exists():
        return 0, 0
    deleted = 0
    failed = 0
    for item in artifacts_dir.iterdir():
        if item.name == ".gitkeep" or not _is_older_than(item, cutoff_time):
            continue
        if job_store.get_job(item.name) is not None:
            continue
        try:
            with lock_job_workspace(data_dir=artifacts_dir.parent, job_id=item.name):
                if not _is_older_than(item, cutoff_time):
                    continue
                if job_store.get_job(item.name) is not None:
                    continue
                erasure_journal.append_orphan_workspace(
                    job_ids=[item.name],
                    now=now,
                )
                delete_local_path(item)
                deleted += 1
        except Exception:
            failed += 1
            logger.exception("Failed to delete orphan artifact")
    return deleted, failed


def _cleanup_orphan_ownership_markers(
    *,
    data_dir: Path,
    cutoff_time: float,
    job_store: RetentionJobStore,
) -> tuple[int, int]:
    """Remove old ownership-only crash residue after exact absence checks."""
    deleted = 0
    failed = 0
    cursor: str | None = None
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    while True:
        page = list_workspace_ownership_markers(
            data_dir=data_dir,
            limit=500,
            after=cursor,
        )
        for marker in page.markers:
            if marker.created_at >= cutoff_time:
                continue
            try:
                with lock_job_workspace(data_dir=data_dir, job_id=marker.job_id):
                    if job_store.get_job(marker.job_id) is not None:
                        continue
                    current_owner = get_workspace_owner(
                        data_dir=data_dir,
                        job_id=marker.job_id,
                    )
                    if current_owner is None:
                        continue
                    if current_owner != marker.user_id:
                        raise RuntimeError(
                            "Workspace ownership changed during retention",
                        )
                    artifact_path = artifacts_dir / marker.job_id
                    expected_stem = f"{marker.job_id}_input"
                    media_remains = artifact_path.exists() or artifact_path.is_symlink()
                    if uploads_dir.exists():
                        media_remains = media_remains or any(
                            item.stem == expected_stem
                            and item.suffix.lower() in UPLOAD_SUFFIXES
                            for item in uploads_dir.iterdir()
                        )
                    if media_remains:
                        continue
                    if remove_workspace_ownership_after_verified_cleanup(
                        data_dir=data_dir,
                        job_id=marker.job_id,
                        expected_user_id=marker.user_id,
                    ):
                        deleted += 1
            except Exception:
                failed += 1
                logger.exception("Failed to delete orphan workspace ownership marker")
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    return deleted, failed


def _upload_job_id(path: Path) -> str | None:
    if path.suffix.lower() not in UPLOAD_SUFFIXES or not path.stem.endswith("_input"):
        return None
    job_id = path.stem.removesuffix("_input")
    return job_id or None


def _is_older_than(path: Path, cutoff_time: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff_time
    except FileNotFoundError:
        return False
