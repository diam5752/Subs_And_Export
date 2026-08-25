"""Cross-process admission and bounded capacity pools for media work."""

from __future__ import annotations

import fcntl
import math
import os
import stat
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .config import settings

MEDIA_ADMISSION_LOCK_TIMEOUT_SECONDS = 30.0
MEDIA_CAPACITY_LOCK_TIMEOUT_SECONDS = 3600.0
_MEDIA_LOCK_DIR = ".media-capacity-locks"
_MEDIA_LOCK_POLL_SECONDS = 0.05
_MAX_CAPACITY_SLOTS = 60
_POOL_NAMES = frozenset({"audio-extraction", "provider-transcription", "render"})


class MediaAdmissionLockTimeoutError(TimeoutError):
    """Raised when media-job admission cannot be serialized promptly."""


class MediaRenderCapacityTimeoutError(TimeoutError):
    """Raised when every bounded render slot remains occupied."""


class MediaExtractionCapacityTimeoutError(TimeoutError):
    """Raised when every bounded audio-extraction slot remains occupied."""


class ProviderTranscriptionCapacityTimeoutError(TimeoutError):
    """Raised when the bounded provider concurrency budget remains occupied."""


def render_slot_weight(
    width: int | None,
    height: int | None,
    *,
    capacity: int,
) -> int:
    """Reserve both launch lanes for a render larger than 1080x1920."""
    _validate_slot_count(capacity, label="capacity")
    if width is None or height is None or width <= 0 or height <= 0:
        return 1
    if width * height > 1080 * 1920:
        return min(2, capacity)
    return 1


def provider_transcription_slot_weight(duration_seconds: float | None) -> int:
    """Mirror Scribe v2's documented internal chunk concurrency."""
    if duration_seconds is None:
        return 1
    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration <= 0:
        return 1
    return min(4, max(1, math.ceil(duration / 480.0)))


@contextmanager
def lock_media_admission(
    *,
    data_dir: Path | None = None,
    timeout_seconds: float = MEDIA_ADMISSION_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize only the active-job check and durable job reservation."""
    with _lock_single_capacity(
        data_dir=data_dir or settings.data_dir,
        lock_name="admission.lock",
        timeout_seconds=timeout_seconds,
        timeout_error=MediaAdmissionLockTimeoutError,
        timeout_message="Media admission is busy. Please retry shortly.",
    ):
        yield


@contextmanager
def lock_media_render(
    *,
    data_dir: Path | None = None,
    capacity: int | None = None,
    slots_required: int = 1,
    timeout_seconds: float = MEDIA_CAPACITY_LOCK_TIMEOUT_SECONDS,
) -> Iterator[tuple[int, ...]]:
    """Acquire one or more bounded FFmpeg render slots."""
    with _lock_capacity_pool(
        data_dir=data_dir or settings.data_dir,
        pool_name="render",
        capacity=settings.media_render_slots if capacity is None else capacity,
        slots_required=slots_required,
        timeout_seconds=timeout_seconds,
        timeout_error=MediaRenderCapacityTimeoutError,
        timeout_message="Media rendering capacity is temporarily busy.",
    ) as slots:
        yield slots


@contextmanager
def lock_audio_extraction(
    *,
    data_dir: Path | None = None,
    capacity: int | None = None,
    timeout_seconds: float = MEDIA_CAPACITY_LOCK_TIMEOUT_SECONDS,
) -> Iterator[tuple[int, ...]]:
    """Acquire one bounded audio-extraction slot."""
    with _lock_capacity_pool(
        data_dir=data_dir or settings.data_dir,
        pool_name="audio-extraction",
        capacity=settings.media_extraction_slots if capacity is None else capacity,
        slots_required=1,
        timeout_seconds=timeout_seconds,
        timeout_error=MediaExtractionCapacityTimeoutError,
        timeout_message="Audio extraction capacity is temporarily busy.",
    ) as slots:
        yield slots


@contextmanager
def lock_provider_transcription(
    *,
    data_dir: Path | None = None,
    capacity: int | None = None,
    slots_required: int = 1,
    timeout_seconds: float = MEDIA_CAPACITY_LOCK_TIMEOUT_SECONDS,
) -> Iterator[tuple[int, ...]]:
    """Reserve the weighted external Scribe concurrency budget."""
    with _lock_capacity_pool(
        data_dir=data_dir or settings.data_dir,
        pool_name="provider-transcription",
        capacity=(
            settings.provider_transcription_slots
            if capacity is None
            else capacity
        ),
        slots_required=slots_required,
        timeout_seconds=timeout_seconds,
        timeout_error=ProviderTranscriptionCapacityTimeoutError,
        timeout_message="Transcription capacity is temporarily busy.",
    ) as slots:
        yield slots


def _validate_timeout(timeout_seconds: float) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("Media-capacity lock timeout cannot be negative or non-finite")


def _validate_slot_count(value: int, *, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > _MAX_CAPACITY_SLOTS
    ):
        raise ValueError(
            f"Media-capacity {label} must be between 1 and {_MAX_CAPACITY_SLOTS}",
        )


def _open_lock_directory(data_dir: Path) -> int:
    lock_root = data_dir.resolve() / _MEDIA_LOCK_DIR
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory_fd = os.open(
        lock_root,
        os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW,
    )
    os.fchmod(directory_fd, 0o700)
    return directory_fd


def _open_lock_file(directory_fd: int, lock_name: str) -> int:
    lock_fd: int | None = None
    for attempt in range(3):
        try:
            lock_fd = os.open(
                lock_name,
                os.O_RDWR | os.O_CREAT | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
            break
        except FileNotFoundError:
            # Two first-time contenders can race while the same slot inode is
            # materialized on Darwin. The directory descriptor remains the
            # trusted boundary, so a bounded retry is safe.
            if attempt == 2:
                raise
            time.sleep(0)
    if lock_fd is None:
        raise RuntimeError("Media-capacity lock could not be opened")
    lock_stat = os.fstat(lock_fd)
    if not stat.S_ISREG(lock_stat.st_mode):
        os.close(lock_fd)
        raise RuntimeError("Media-capacity lock is not a regular file")
    os.fchmod(lock_fd, 0o600)
    return lock_fd


@contextmanager
def _lock_single_capacity(
    *,
    data_dir: Path,
    lock_name: str,
    timeout_seconds: float,
    timeout_error: type[TimeoutError],
    timeout_message: str,
) -> Iterator[None]:
    _validate_timeout(timeout_seconds)
    if lock_name != "admission.lock":
        raise ValueError("Unknown single media-capacity lock")

    directory_fd = _open_lock_directory(data_dir)
    lock_fd: int | None = None
    acquired = False
    deadline = time.monotonic() + timeout_seconds
    last_busy_error: BlockingIOError | None = None
    try:
        lock_fd = _open_lock_file(directory_fd, lock_name)
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


@contextmanager
def _lock_capacity_pool(
    *,
    data_dir: Path,
    pool_name: str,
    capacity: int,
    slots_required: int,
    timeout_seconds: float,
    timeout_error: type[TimeoutError],
    timeout_message: str,
) -> Iterator[tuple[int, ...]]:
    _validate_timeout(timeout_seconds)
    _validate_slot_count(capacity, label="capacity")
    _validate_slot_count(slots_required, label="slot request")
    if slots_required > capacity:
        raise ValueError("Media-capacity slot request exceeds pool capacity")
    if pool_name not in _POOL_NAMES:
        raise ValueError("Unknown media-capacity pool")

    directory_fd = _open_lock_directory(data_dir)
    acquired: list[tuple[int, int]] = []
    deadline = time.monotonic() + timeout_seconds
    last_busy_error: BlockingIOError | None = None
    try:
        while len(acquired) < slots_required:
            acquired.clear()
            for slot_index in range(capacity):
                lock_fd = _open_lock_file(
                    directory_fd,
                    f"{pool_name}-{slot_index}.lock",
                )
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    last_busy_error = exc
                    os.close(lock_fd)
                    continue
                acquired.append((slot_index, lock_fd))
                if len(acquired) == slots_required:
                    break

            if len(acquired) == slots_required:
                break

            for _, lock_fd in acquired:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
                os.close(lock_fd)
            acquired.clear()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise timeout_error(timeout_message) from last_busy_error
            time.sleep(min(_MEDIA_LOCK_POLL_SECONDS, remaining))

        yield tuple(slot_index for slot_index, _ in acquired)
    finally:
        for _, lock_fd in acquired:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        os.close(directory_fd)
