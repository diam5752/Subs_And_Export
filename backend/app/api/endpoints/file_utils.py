"""File and directory utilities for video processing endpoints."""

from __future__ import annotations

import logging
import os
import re
import shutil
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

import anyio
from fastapi import HTTPException
from starlette.requests import Request

from ...core.cleanup import ensure_storage_capacity, run_configured_retention
from ...core.config import settings
from ...core.database import Database
from ...core.job_lifecycle import ACTIVE_JOB_STATUSES
from ...services.jobs import JobStore

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = settings.max_upload_mb * 1024 * 1024
UPLOAD_WORKING_SPACE_BYTES = 64 * 1024 * 1024
UPLOAD_STORAGE_RESERVATION_KEY = "_upload_storage_reservation_bytes"
MAX_DOWNLOAD_FILENAME_CHARS = 180
_UNSAFE_DOWNLOAD_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class StorageReservationJob(Protocol):
    """Minimal active-job shape needed for disk reservation accounting."""

    result_data: dict[str, Any] | None


def upload_storage_reservation_bytes(expected_upload_bytes: int | None) -> int:
    """Reserve an upload plus bounded audio/transcript working space."""
    upload_bytes = expected_upload_bytes if expected_upload_bytes is not None else MAX_UPLOAD_BYTES
    return max(0, upload_bytes) + UPLOAD_WORKING_SPACE_BYTES


def active_upload_storage_reservation_bytes(
    jobs: Iterable[StorageReservationJob],
) -> int:
    """Return valid private reservations held by uploads not yet on disk."""
    total = 0
    for job in jobs:
        raw_value = (job.result_data or {}).get(UPLOAD_STORAGE_RESERVATION_KEY)
        if isinstance(raw_value, int) and not isinstance(raw_value, bool) and raw_value > 0:
            total += raw_value
    return total


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


def relpath_safe(path: Path, base: Path) -> Path:
    """Return ``path`` relative to ``base`` when possible, otherwise the absolute path."""
    try:
        return path.relative_to(base)
    except ValueError:
        return path


def sanitize_download_filename(requested: str | None, source_filename: str) -> str:
    """Return a header-safe basename whose extension matches the served file."""
    source_name = Path(source_filename).name
    source_suffix = Path(source_name).suffix
    candidate = requested or source_name
    candidate = unicodedata.normalize("NFC", candidate).replace("\\", "/").split("/")[-1]
    candidate = _UNSAFE_DOWNLOAD_FILENAME.sub("_", candidate).strip().rstrip(". ")

    if not candidate or candidate in {".", ".."}:
        candidate = source_name

    if source_suffix and Path(candidate).suffix.lower() != source_suffix.lower():
        candidate_stem = Path(candidate).stem if Path(candidate).suffix else candidate
        candidate = f"{candidate_stem}{source_suffix}"

    suffix = Path(candidate).suffix
    stem = candidate[: -len(suffix)] if suffix else candidate
    available_stem_chars = max(1, MAX_DOWNLOAD_FILENAME_CHARS - len(suffix))
    candidate = f"{stem[:available_stem_chars].rstrip()}{suffix}"
    return candidate or source_name


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
    except OSError as exc:
        logger.debug("Hard link unavailable; copying %s to %s: %s", source, destination, exc)

    shutil.copy2(source, destination)


async def save_request_stream_with_limit(
    request: Request,
    destination: Path,
    *,
    expected_size: int | None,
    cleanup_on_error: bool = True,
) -> int:
    """Stream a raw request body directly to disk with a strict size limit.

    This path never asks Starlette to parse or spool a multipart body before
    authentication and application-level size enforcement.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        async with await anyio.open_file(destination, "wb") as buffer:
            async for chunk in request.stream():
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large; limit is {settings.max_upload_mb}MB",
                    )
                await buffer.write(chunk)
    except BaseException:
        if cleanup_on_error:
            destination.unlink(missing_ok=True)
        raise

    if total == 0:
        if cleanup_on_error:
            destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload")
    if expected_size is not None and total != expected_size:
        if cleanup_on_error:
            destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Incomplete upload")
    return total


def require_storage_capacity(
    data_dir: Path,
    *,
    required_bytes: int,
    db: Database,
) -> None:
    """Reject if an operation plus in-flight upload reservations are unsafe."""
    active_jobs = JobStore(db=db).list_jobs_with_statuses(ACTIVE_JOB_STATUSES)
    reserved_bytes = active_upload_storage_reservation_bytes(active_jobs)
    has_capacity = ensure_storage_capacity(
        data_dir,
        required_bytes=max(0, required_bytes) + reserved_bytes,
        minimum_free_mb=settings.storage_min_free_mb,
        cleanup_callback=lambda: run_configured_retention(db),
    )
    if not has_capacity:
        raise HTTPException(
            status_code=507,
            detail=("Storage is temporarily busy. Existing projects are safe; please try again in a few minutes."),
        )


# Initialize the shared data root on import. Callers resolve upload and artifact
# directories per operation through ``data_roots`` instead of stale globals.
DATA_DIR = data_roots()[0]
