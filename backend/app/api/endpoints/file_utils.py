"""File and directory utilities for video processing endpoints."""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from fastapi import HTTPException, UploadFile

from ...core.config import settings

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024


def data_roots() -> tuple[Path, Path, Path]:
    """Resolve data directories relative to the configured project root.

    Returns:
        Tuple of (data_dir, uploads_dir, artifacts_dir)
    """
    data_dir = settings.data_dir
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, uploads_dir, artifacts_dir


def validate_path_is_safe(path: Path, base_dir: Path | None = None) -> None:
    """
    Security: Ensure path is within the allowed data directory to prevent traversal attacks.
    """
    if base_dir is None:
        base_dir = settings.data_dir

    try:
        # Resolve symlinks and .. components
        resolved_path = path.resolve()
        resolved_base = base_dir.resolve()

        # Check if resolved path is within resolved base
        if not resolved_path.is_relative_to(resolved_base):
             # Try parent directory check for cases where file doesn't exist yet
             if not resolved_path.parent.is_relative_to(resolved_base):
                raise ValueError("Path traversal detected")
    except (ValueError, RuntimeError) as e:
        logger.warning(f"Path security check failed: {path} not in {base_dir}")
        raise HTTPException(status_code=400, detail="Invalid path")


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
    validate_path_is_safe(destination)
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
    validate_path_is_safe(destination)

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
                    detail=f"File too large; limit is {settings.max_upload_mb}MB",
                )
            buffer.write(chunk)
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload")


# Initialize directories on import
DATA_DIR, UPLOADS_DIR, ARTIFACTS_DIR = data_roots()
