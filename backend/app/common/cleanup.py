import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

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

    logger.info(f"Starting cleanup of files older than {retention_hours} hours...")

    # helper to check and delete
    def check_and_delete(path: Path):
        try:
            if not path.exists():
                return

            # Use stat().st_mtime for modification time
            mtime = path.stat().st_mtime

            if mtime < cutoff_time:
                logger.info(f"Deleting expired item: {path}")
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
        except Exception as e:
            logger.error(f"Error deleting {path}: {e}")

    # 1. Cleanup Uploads (Files)
    if uploads_dir.exists():
        for item in uploads_dir.iterdir():
            if item.name == ".gitkeep":
                continue
            check_and_delete(item)

    # 2. Cleanup Artifacts (Directories mainly)
    if artifacts_dir.exists():
        for item in artifacts_dir.iterdir():
            if item.name == ".gitkeep":
                continue
            check_and_delete(item)

    logger.info("Cleanup complete.")
