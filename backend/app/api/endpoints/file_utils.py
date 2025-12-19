"""File and directory utilities for video processing endpoints."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ...core import config
from ...core.settings import load_app_settings

logger = logging.getLogger(__name__)

APP_SETTINGS = load_app_settings()
MAX_UPLOAD_BYTES = APP_SETTINGS.max_upload_mb * 1024 * 1024


def data_roots() -> tuple[Path, Path, Path]:
    """Resolve data directories relative to the configured project root.
    
    Returns:
        Tuple of (data_dir, uploads_dir, artifacts_dir)
    """
    data_dir = config.PROJECT_ROOT / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, uploads_dir, artifacts_dir


def relpath_safe(path: Path, base: Path) -> Path:
    """Return ``path`` relative to ``base`` when possible, otherwise the absolute path."""
    try:
        return path.relative_to(base)
    except ValueError:
        return path


def link_or_copy_file(source: Path, destination: Path) -> None:
    """Create a hard link or copy a file to destination.
    
    Raises:
        FileExistsError: If destination already exists
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")

    try:
        os.link(source, destination)
        return
    except Exception:
        pass

    shutil.copy2(source, destination)


def save_upload_with_limit(upload: UploadFile, destination: Path) -> None:
    """Write an upload to disk while enforcing the configured size limit.
    
    Raises:
        HTTPException: If file is too large or empty
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    upload.file.seek(0)
    with destination.open("wb") as buffer:
        for chunk in iter(lambda: upload.file.read(1024 * 1024), b""):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                buffer.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large; limit is {APP_SETTINGS.max_upload_mb}MB",
                )
            buffer.write(chunk)
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload")


# Initialize directories on import
DATA_DIR, UPLOADS_DIR, ARTIFACTS_DIR = data_roots()
