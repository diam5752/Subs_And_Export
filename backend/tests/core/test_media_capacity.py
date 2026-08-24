from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend.app.core.media_capacity import (
    MediaAdmissionLockTimeoutError,
    MediaCpuLockTimeoutError,
    lock_media_admission,
    lock_media_cpu,
)


@pytest.mark.parametrize(
    ("lock_factory", "timeout_error"),
    [
        (lock_media_admission, MediaAdmissionLockTimeoutError),
        (lock_media_cpu, MediaCpuLockTimeoutError),
    ],
)
def test_media_capacity_lock_blocks_a_second_holder(
    tmp_path: Path,
    lock_factory,
    timeout_error: type[TimeoutError],
) -> None:
    # REGRESSION: independent requests could previously start overlapping
    # media work on the same shared VM without a cross-process capacity guard.
    result: list[str] = []

    def contend() -> None:
        try:
            with lock_factory(data_dir=tmp_path, timeout_seconds=0.05):
                result.append("acquired")
        except timeout_error:
            result.append("blocked")

    with lock_factory(data_dir=tmp_path):
        contender = threading.Thread(target=contend)
        contender.start()
        contender.join(timeout=2)
        assert not contender.is_alive()

    assert result == ["blocked"]
    lock_root = tmp_path / ".media-capacity-locks"
    assert lock_root.stat().st_mode & 0o777 == 0o700
    assert all(item.stat().st_mode & 0o777 == 0o600 for item in lock_root.iterdir())


def test_media_capacity_lock_is_reusable_after_release(tmp_path: Path) -> None:
    with lock_media_admission(data_dir=tmp_path):
        pass
    with lock_media_admission(data_dir=tmp_path, timeout_seconds=0.05):
        pass


def test_media_capacity_lock_rejects_negative_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        with lock_media_cpu(data_dir=tmp_path, timeout_seconds=-1):
            pass
