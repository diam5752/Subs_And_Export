import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_old_uploads(uploads_dir: Path, retention_hours: int = 24) -> None:
    """Delete files and directories in uploads_dir older than retention_hours."""
    now = time.time()
    retention_seconds = retention_hours * 3600
    cutoff_time = now - retention_seconds

    logger.info("Starting cleanup of uploads older than %s hours...", retention_hours)
    _cleanup_dir(uploads_dir, cutoff_time)
    logger.info("Upload cleanup complete.")


def cleanup_old_jobs(
    uploads_dir: Path,
    artifacts_dir: Path,
    retention_hours: int = 24
) -> None:
    """
    Delete files and directories in uploads_dir and artifacts_dir
    that are older than retention_hours.
    """
    now = time.time()
    retention_seconds = retention_hours * 3600
    cutoff_time = now - retention_seconds

    logger.info("Starting cleanup of files older than %s hours...", retention_hours)

    # 1. Cleanup Uploads (Files)
    _cleanup_dir(uploads_dir, cutoff_time)

    # 2. Cleanup Artifacts (Directories mainly)
    _cleanup_dir(artifacts_dir, cutoff_time)

    logger.info("Cleanup complete.")


def _cleanup_dir(root_dir: Path, cutoff_time: float) -> None:
    """Helper to delete items inside a directory older than cutoff_time."""
    if not root_dir.exists():
        return

    for item in root_dir.iterdir():
        if item.name == ".gitkeep":
            continue
        _check_and_delete(item, cutoff_time)


def _check_and_delete(path: Path, cutoff_time: float) -> None:
    try:
        if not path.exists():
            return

        mtime = path.stat().st_mtime
        if mtime >= cutoff_time:
            return

        logger.info("Deleting expired item: %s", path)
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    except Exception as exc:
        logger.error("Error deleting %s: %s", path, exc)
