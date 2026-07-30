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

if TYPE_CHECKING:
    from .database import Database

logger = logging.getLogger(__name__)

ACTIVE_JOB_STATUSES = frozenset({"pending", "processing"})
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})
UPLOAD_SUFFIXES = frozenset({".mp4", ".mov", ".mkv"})
MEBIBYTE = 1024 * 1024


class RetentionJob(Protocol):
    id: str
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


def cleanup_expired_workspaces(
    *,
    job_store: RetentionJobStore,
    history_store: RetentionHistoryStore,
    uploads_dir: Path,
    artifacts_dir: Path,
    workspace_retention_hours: int,
    stale_job_retention_hours: int,
    orphan_retention_hours: int,
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
            delete_job_workspace(
                job_id=job_id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_dir,
            )
            history_store.delete_job_events([job_id])
            job_store.delete_job(job_id)
            deleted_job_ids.append(job_id)
        except Exception:
            failed_job_ids.append(job_id)
            logger.exception("Workspace cleanup failed", extra={"job_id": job_id})

    orphan_cutoff = current_time - (orphan_retention_hours * 3600)
    deleted_orphan_items = _cleanup_orphan_uploads(
        uploads_dir,
        cutoff_time=orphan_cutoff,
        job_store=job_store,
    )
    deleted_orphan_items += _cleanup_orphan_artifacts(
        artifacts_dir,
        cutoff_time=orphan_cutoff,
        job_store=job_store,
    )

    if deleted_job_ids or failed_job_ids or deleted_orphan_items:
        logger.info(
            "Workspace retention complete",
            extra={
                "deleted_jobs": len(deleted_job_ids),
                "failed_jobs": len(failed_job_ids),
                "deleted_orphans": deleted_orphan_items,
            },
        )
    return CleanupReport(
        deleted_job_ids=deleted_job_ids,
        failed_job_ids=failed_job_ids,
        deleted_orphan_items=deleted_orphan_items,
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


def delete_job_workspace(
    *,
    job_id: str,
    uploads_dir: Path,
    artifacts_dir: Path,
) -> None:
    """Delete the exact local upload and artifact tree for one job."""
    artifacts_root = artifacts_dir.resolve()
    artifact_dir = (artifacts_root / job_id).resolve()
    if artifact_dir.parent != artifacts_root:
        raise ValueError("Invalid job workspace path")

    if artifact_dir.exists() or artifact_dir.is_symlink():
        _delete_path(artifact_dir)

    if not uploads_dir.exists():
        return
    expected_stem = f"{job_id}_input"
    for item in uploads_dir.iterdir():
        if item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES:
            _delete_path(item)


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
    from backend.app.services.history import HistoryStore
    from backend.app.services.jobs import JobStore
    from backend.app.services.points import PointsStore
    from backend.app.services.usage_ledger import UsageLedgerStore

    uploads_dir = settings.data_dir / "uploads"
    artifacts_dir = settings.data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
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
    return report


async def retention_worker(db: Database) -> None:
    """Run cleanup immediately and then at the configured bounded interval."""
    while True:
        try:
            await asyncio.to_thread(run_configured_retention, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Scheduled workspace cleanup failed")
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)


def cleanup_old_uploads(uploads_dir: Path, retention_hours: int = 24) -> None:
    """Legacy mtime cleanup retained for maintenance scripts and compatibility."""
    cutoff_time = time.time() - (retention_hours * 3600)
    _cleanup_dir(uploads_dir, cutoff_time)


def cleanup_old_jobs(
    uploads_dir: Path,
    artifacts_dir: Path,
    retention_hours: int = 24,
) -> None:
    """Legacy mtime cleanup retained for maintenance scripts and compatibility."""
    cutoff_time = time.time() - (retention_hours * 3600)
    _cleanup_dir(uploads_dir, cutoff_time)
    _cleanup_dir(artifacts_dir, cutoff_time)


def _cleanup_orphan_uploads(
    uploads_dir: Path,
    *,
    cutoff_time: float,
    job_store: RetentionJobStore,
) -> int:
    if not uploads_dir.exists():
        return 0
    deleted = 0
    for item in uploads_dir.iterdir():
        if item.name == ".gitkeep" or not _is_older_than(item, cutoff_time):
            continue
        job_id = _upload_job_id(item)
        if job_id is not None and job_store.get_job(job_id) is not None:
            continue
        try:
            _delete_path(item)
            deleted += 1
        except OSError:
            logger.exception("Failed to delete orphan upload")
    return deleted


def _cleanup_orphan_artifacts(
    artifacts_dir: Path,
    *,
    cutoff_time: float,
    job_store: RetentionJobStore,
) -> int:
    if not artifacts_dir.exists():
        return 0
    deleted = 0
    for item in artifacts_dir.iterdir():
        if item.name == ".gitkeep" or not _is_older_than(item, cutoff_time):
            continue
        if job_store.get_job(item.name) is not None:
            continue
        try:
            _delete_path(item)
            deleted += 1
        except OSError:
            logger.exception("Failed to delete orphan artifact")
    return deleted


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


def _cleanup_dir(root_dir: Path, cutoff_time: float) -> None:
    if not root_dir.exists():
        return
    for item in root_dir.iterdir():
        if item.name == ".gitkeep":
            continue
        _check_and_delete(item, cutoff_time)


def _check_and_delete(path: Path, cutoff_time: float) -> None:
    try:
        if not path.exists() or not _is_older_than(path, cutoff_time):
            return
        _delete_path(path)
    except Exception as exc:
        logger.error("Error deleting %s: %s", path, exc)


def _delete_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
