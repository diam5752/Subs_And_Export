from __future__ import annotations

import threading
from pathlib import Path

import pytest

from backend.app.core.media_capacity import (
    MediaAdmissionLockTimeoutError,
    MediaExtractionCapacityTimeoutError,
    MediaRenderCapacityTimeoutError,
    ProviderTranscriptionCapacityTimeoutError,
    active_render_storage_reservation_bytes,
    lock_audio_extraction,
    lock_media_admission,
    lock_media_render,
    lock_provider_transcription,
    provider_transcription_slot_weight,
    publish_locked_render_storage_reservation,
    render_slot_weight,
)


@pytest.mark.parametrize(
    ("lock_factory", "timeout_error"),
    [
        (lock_media_admission, MediaAdmissionLockTimeoutError),
        (lock_audio_extraction, MediaExtractionCapacityTimeoutError),
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
        with lock_media_render(data_dir=tmp_path, timeout_seconds=-1):
            pass


def test_media_capacity_lock_rejects_explicit_zero_capacity(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="between 1 and"):
        with lock_media_render(data_dir=tmp_path, capacity=0):
            pass


def test_two_render_slots_allow_two_holders_and_block_a_third(tmp_path: Path) -> None:
    # REGRESSION: exports were globally serialized even when two bounded
    # encoders fit inside the shared host's CPU cgroup.
    barrier = threading.Barrier(3)
    release = threading.Event()
    results: list[str] = []

    def hold_render(name: str) -> None:
        with lock_media_render(data_dir=tmp_path, capacity=2):
            results.append(name)
            barrier.wait(timeout=2)
            release.wait(timeout=2)

    first = threading.Thread(target=hold_render, args=("first",))
    second = threading.Thread(target=hold_render, args=("second",))
    first.start()
    second.start()
    barrier.wait(timeout=2)

    with pytest.raises(MediaRenderCapacityTimeoutError):
        with lock_media_render(
            data_dir=tmp_path,
            capacity=2,
            timeout_seconds=0.05,
        ):
            pass

    release.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(results) == ["first", "second"]


def test_weighted_render_occupies_both_slots(tmp_path: Path) -> None:
    with lock_media_render(
        data_dir=tmp_path,
        capacity=2,
        slots_required=2,
    ):
        with pytest.raises(MediaRenderCapacityTimeoutError):
            with lock_media_render(
                data_dir=tmp_path,
                capacity=2,
                timeout_seconds=0.05,
            ):
                pass


def test_provider_pool_accounts_for_long_scribe_requests(tmp_path: Path) -> None:
    assert provider_transcription_slot_weight(479.0) == 1
    assert provider_transcription_slot_weight(600.0) == 2
    assert provider_transcription_slot_weight(7200.0) == 4

    with lock_provider_transcription(
        data_dir=tmp_path,
        capacity=8,
        slots_required=4,
    ):
        with lock_provider_transcription(
            data_dir=tmp_path,
            capacity=8,
            slots_required=4,
        ):
            with pytest.raises(ProviderTranscriptionCapacityTimeoutError):
                with lock_provider_transcription(
                    data_dir=tmp_path,
                    capacity=8,
                    timeout_seconds=0.05,
                ):
                    pass


def test_render_slot_weight_reserves_both_lanes_for_4k() -> None:
    assert render_slot_weight(720, 1280, capacity=2) == 1
    assert render_slot_weight(1080, 1920, capacity=2) == 1
    assert render_slot_weight(2160, 3840, capacity=2) == 2


def test_active_render_storage_reservations_are_counted_once_per_lease(
    tmp_path: Path,
) -> None:
    with lock_media_render(data_dir=tmp_path, capacity=2) as first_slots:
        publish_locked_render_storage_reservation(
            data_dir=tmp_path,
            slot_indexes=first_slots,
            reserved_bytes=400,
            capacity=2,
        )
        with lock_media_render(data_dir=tmp_path, capacity=2) as second_slots:
            publish_locked_render_storage_reservation(
                data_dir=tmp_path,
                slot_indexes=second_slots,
                reserved_bytes=600,
                capacity=2,
            )
            assert active_render_storage_reservation_bytes(
                data_dir=tmp_path,
                capacity=2,
            ) == 1_000


def test_multi_slot_render_storage_reservation_is_not_double_counted(
    tmp_path: Path,
) -> None:
    with lock_media_render(
        data_dir=tmp_path,
        capacity=2,
        slots_required=2,
    ) as slots:
        publish_locked_render_storage_reservation(
            data_dir=tmp_path,
            slot_indexes=slots,
            reserved_bytes=900,
            capacity=2,
        )
        assert active_render_storage_reservation_bytes(
            data_dir=tmp_path,
            capacity=2,
        ) == 900


def test_abandoned_render_storage_reservation_is_cleared(
    tmp_path: Path,
) -> None:
    with lock_media_render(data_dir=tmp_path, capacity=2) as slots:
        publish_locked_render_storage_reservation(
            data_dir=tmp_path,
            slot_indexes=slots,
            reserved_bytes=500,
            capacity=2,
        )

    assert active_render_storage_reservation_bytes(
        data_dir=tmp_path,
        capacity=2,
    ) == 0
    reservation_file = tmp_path / ".media-capacity-locks" / f"render-{slots[0]}.lock"
    assert reservation_file.read_bytes() == b""


def test_malformed_active_render_storage_reservation_fails_closed(
    tmp_path: Path,
) -> None:
    with lock_media_render(data_dir=tmp_path, capacity=2) as slots:
        reservation_file = (
            tmp_path / ".media-capacity-locks" / f"render-{slots[0]}.lock"
        )
        reservation_file.write_text("not-a-byte-count\n", encoding="ascii")

        with pytest.raises(RuntimeError, match="malformed"):
            active_render_storage_reservation_bytes(
                data_dir=tmp_path,
                capacity=2,
            )
