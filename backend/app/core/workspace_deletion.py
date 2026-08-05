"""Exact, local-only deletion primitives for per-job media workspaces."""

from __future__ import annotations

import fcntl
import hashlib
import os
import shutil
import stat
import time
from collections.abc import Iterable, Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path

UPLOAD_SUFFIXES = frozenset({".mp4", ".mov", ".mkv"})
JOB_WORKSPACE_LOCK_TIMEOUT_SECONDS = 30.0
JOB_WORKSPACE_LOCK_STRIPES = 256
_JOB_WORKSPACE_LOCK_POLL_SECONDS = 0.05
_JOB_WORKSPACE_LOCK_DIR = ".job-locks"


class JobWorkspaceLockTimeoutError(TimeoutError):
    """Raised when a job workspace remains busy past the bounded wait."""


@contextmanager
def lock_job_workspace(
    *,
    data_dir: Path,
    job_id: str,
    timeout_seconds: float = JOB_WORKSPACE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize one job's writers and erasers across backend processes."""
    if not job_id:
        raise ValueError("Job workspace lock requires a job ID")
    if timeout_seconds < 0:
        raise ValueError("Job workspace lock timeout cannot be negative")

    lock_root = data_dir.resolve() / _JOB_WORKSPACE_LOCK_DIR
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_stripe = _job_workspace_lock_stripe(job_id)
    lock_name = f"stripe-{lock_stripe:03d}.lock"
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
    file_flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW
    directory_fd = os.open(lock_root, directory_flags)
    lock_fd: int | None = None
    acquired = False
    try:
        os.fchmod(directory_fd, 0o700)
        lock_fd = os.open(lock_name, file_flags, 0o600, dir_fd=directory_fd)
        lock_stat = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise RuntimeError("Job workspace lock is not a regular file")
        os.fchmod(lock_fd, 0o600)

        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise JobWorkspaceLockTimeoutError(
                        "Project is busy. Please retry shortly.",
                    ) from exc
                time.sleep(min(_JOB_WORKSPACE_LOCK_POLL_SECONDS, remaining))
        yield
    finally:
        if lock_fd is not None:
            if acquired:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(directory_fd)


@contextmanager
def lock_job_workspaces(
    *,
    data_dir: Path,
    job_ids: Iterable[str],
    timeout_seconds: float = JOB_WORKSPACE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Acquire deduplicated stripes in deterministic order and one time bound."""
    if timeout_seconds < 0:
        raise ValueError("Job workspace lock timeout cannot be negative")
    representative_by_stripe: dict[int, str] = {}
    for job_id in sorted(set(job_ids)):
        representative_by_stripe.setdefault(
            _job_workspace_lock_stripe(job_id),
            job_id,
        )
    deadline = time.monotonic() + timeout_seconds
    with ExitStack() as stack:
        for lock_stripe in sorted(representative_by_stripe):
            remaining = max(0.0, deadline - time.monotonic())
            stack.enter_context(
                lock_job_workspace(
                    data_dir=data_dir,
                    job_id=representative_by_stripe[lock_stripe],
                    timeout_seconds=remaining,
                ),
            )
        yield


def _job_workspace_lock_stripe(job_id: str) -> int:
    if not job_id:
        raise ValueError("Job workspace lock requires a job ID")
    digest = hashlib.sha256(job_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:2], byteorder="big") % JOB_WORKSPACE_LOCK_STRIPES


def delete_job_workspace(
    *,
    job_id: str,
    uploads_dir: Path,
    artifacts_dir: Path,
) -> None:
    """Delete the exact local upload and artifact tree for one job."""
    artifacts_root = artifacts_dir.resolve()
    artifact_dir = artifacts_root / job_id
    if artifact_dir.is_symlink():
        # Never follow a workspace symlink into another job. The link belongs
        # to this exact workspace; its target does not.
        delete_local_path(artifact_dir)
    else:
        resolved_artifact_dir = artifact_dir.resolve()
        if resolved_artifact_dir.parent != artifacts_root:
            raise ValueError("Invalid job workspace path")
        if artifact_dir.exists():
            delete_local_path(artifact_dir)

    if not uploads_dir.exists():
        return
    expected_stem = f"{job_id}_input"
    for item in uploads_dir.iterdir():
        if item.stem == expected_stem and item.suffix.lower() in UPLOAD_SUFFIXES:
            delete_local_path(item)


def delete_local_path(path: Path) -> None:
    """Delete one exact local path without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
