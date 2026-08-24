"""Cross-process admission and CPU-capacity locks for media work."""

from __future__ import annotations

import fcntl
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

MEDIA_ADMISSION_LOCK_TIMEOUT_SECONDS = 30.0
MEDIA_CPU_LOCK_TIMEOUT_SECONDS = 3600.0
_MEDIA_LOCK_DIR = ".media-capacity-locks"
_MEDIA_LOCK_POLL_SECONDS = 0.05


class MediaAdmissionLockTimeoutError(TimeoutError):
    """Raised when media-job admission cannot be serialized promptly."""


class MediaCpuLockTimeoutError(TimeoutError):
    """Raised when the shared host CPU slot remains occupied too long."""


@contextmanager
def lock_media_admission(
    *,
    data_dir: Path | None = None,
    timeout_seconds: float = MEDIA_ADMISSION_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize the active-job check with creation of one media request."""
    with _lock_media_capacity(
        data_dir=data_dir or settings.data_dir,
        lock_name="admission.lock",
        timeout_seconds=timeout_seconds,
        timeout_error=MediaAdmissionLockTimeoutError,
        timeout_message="Media admission is busy. Please retry shortly.",
    ):
        yield


@contextmanager
def lock_media_cpu(
    *,
    data_dir: Path | None = None,
    timeout_seconds: float = MEDIA_CPU_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Allow only one local FFmpeg workload on the shared host at a time."""
    with _lock_media_capacity(
        data_dir=data_dir or settings.data_dir,
        lock_name="cpu.lock",
        timeout_seconds=timeout_seconds,
        timeout_error=MediaCpuLockTimeoutError,
        timeout_message="Media processing capacity is temporarily busy.",
    ):
        yield


@contextmanager
def _lock_media_capacity(
    *,
    data_dir: Path,
    lock_name: str,
    timeout_seconds: float,
    timeout_error: type[TimeoutError],
    timeout_message: str,
) -> Iterator[None]:
    if timeout_seconds < 0:
        raise ValueError("Media-capacity lock timeout cannot be negative")
    if lock_name not in {"admission.lock", "cpu.lock"}:
        raise ValueError("Unknown media-capacity lock")

    lock_root = data_dir.resolve() / _MEDIA_LOCK_DIR
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_fd = os.open(
        lock_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    lock_fd: int | None = None
    acquired = False
    deadline = time.monotonic() + timeout_seconds
    last_busy_error: BlockingIOError | None = None
    try:
        os.fchmod(directory_fd, 0o700)
        lock_fd = os.open(
            lock_name,
            os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_fd,
        )
        lock_stat = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_stat.st_mode):
            raise RuntimeError("Media-capacity lock is not a regular file")
        os.fchmod(lock_fd, 0o600)

        while not acquired:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError as exc:
                last_busy_error = exc
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise timeout_error(timeout_message) from last_busy_error
                time.sleep(min(_MEDIA_LOCK_POLL_SECONDS, remaining))

        yield
    finally:
        if lock_fd is not None:
            if acquired:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(directory_fd)
