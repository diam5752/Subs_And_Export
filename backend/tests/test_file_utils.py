from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import anyio
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.api.endpoints import file_utils
from backend.app.core.database import Database
from backend.app.core.media_capacity import lock_media_render


def _streaming_request(chunks: list[bytes]) -> Request:
    pending = list(chunks)

    async def receive() -> dict[str, object]:
        body = pending.pop(0) if pending else b""
        return {
            "type": "http.request",
            "body": body,
            "more_body": bool(pending),
        }

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/process-stream",
            "headers": [],
        },
        receive,
    )


def _stalled_streaming_request(first_chunk: bytes) -> Request:
    delivered_first_chunk = False

    async def receive() -> dict[str, object]:
        nonlocal delivered_first_chunk
        if not delivered_first_chunk:
            delivered_first_chunk = True
            return {
                "type": "http.request",
                "body": first_chunk,
                "more_body": True,
            }
        await anyio.sleep_forever()
        raise AssertionError("unreachable")

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/process-stream",
            "headers": [],
        },
        receive,
    )


def _slow_active_streaming_request(chunks: list[bytes], *, delay_seconds: float) -> Request:
    pending = list(chunks)

    async def receive() -> dict[str, object]:
        await anyio.sleep(delay_seconds)
        body = pending.pop(0) if pending else b""
        return {
            "type": "http.request",
            "body": body,
            "more_body": bool(pending),
        }

    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/videos/process-stream",
            "headers": [],
        },
        receive,
    )


def test_save_request_stream_removes_incomplete_upload(tmp_path: Path) -> None:
    destination = tmp_path / "upload.mp4"

    async def run() -> None:
        with pytest.raises(HTTPException) as exc_info:
            await file_utils.save_request_stream_with_limit(
                _streaming_request([b"abc"]),
                destination,
                expected_size=4,
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Incomplete upload"

    anyio.run(run)
    assert not destination.exists()


def test_save_request_stream_times_out_and_removes_a_stalled_partial_upload(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "upload.mp4"

    async def run() -> None:
        with pytest.raises(HTTPException) as exc_info:
            await file_utils.save_request_stream_with_limit(
                _stalled_streaming_request(b"partial-video"),
                destination,
                expected_size=1_000,
                inactivity_timeout_seconds=0.01,
            )
        assert exc_info.value.status_code == 408
        assert exc_info.value.detail == "Upload stalled before completion"

    # REGRESSION: a paused mobile upload previously waited forever for the
    # next body chunk, retaining both its partial private file and credits.
    anyio.run(run)
    assert not destination.exists()


def test_save_request_stream_allows_slow_active_chunks(tmp_path: Path) -> None:
    destination = tmp_path / "upload.mp4"

    async def run() -> None:
        saved = await file_utils.save_request_stream_with_limit(
            _slow_active_streaming_request(
                [b"slow-", b"mobile-", b"upload"],
                delay_seconds=0.005,
            ),
            destination,
            expected_size=len(b"slow-mobile-upload"),
            inactivity_timeout_seconds=0.05,
        )
        assert saved == len(b"slow-mobile-upload")

    anyio.run(run)
    assert destination.read_bytes() == b"slow-mobile-upload"


def test_save_request_stream_rejects_non_positive_inactivity_timeout(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "upload.mp4"

    async def run() -> None:
        with pytest.raises(ValueError, match="must be positive"):
            await file_utils.save_request_stream_with_limit(
                _streaming_request([b"video"]),
                destination,
                expected_size=5,
                inactivity_timeout_seconds=0,
            )

    anyio.run(run)
    assert not destination.exists()


def test_save_request_stream_enforces_limit_while_receiving(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "upload.mp4"
    monkeypatch.setattr(file_utils, "MAX_UPLOAD_BYTES", 3)

    async def run() -> None:
        with pytest.raises(HTTPException) as exc_info:
            await file_utils.save_request_stream_with_limit(
                _streaming_request([b"ab", b"cd"]),
                destination,
                expected_size=None,
            )
        assert exc_info.value.status_code == 413

    anyio.run(run)
    assert not destination.exists()


def test_save_request_stream_rejects_empty_body(tmp_path: Path) -> None:
    destination = tmp_path / "upload.mp4"

    async def run() -> None:
        with pytest.raises(HTTPException) as exc_info:
            await file_utils.save_request_stream_with_limit(
                _streaming_request([]),
                destination,
                expected_size=None,
            )
        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == "Empty upload"

    anyio.run(run)
    assert not destination.exists()


def test_upload_storage_reservation_uses_declared_size_or_safe_max(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(file_utils, "MAX_UPLOAD_BYTES", 500)
    monkeypatch.setattr(file_utils, "UPLOAD_WORKING_SPACE_BYTES", 64)

    assert file_utils.upload_storage_reservation_bytes(125) == 189
    assert file_utils.upload_storage_reservation_bytes(None) == 564


def test_active_upload_reservations_ignore_invalid_private_values() -> None:
    jobs = [
        SimpleNamespace(
            result_data={file_utils.UPLOAD_STORAGE_RESERVATION_KEY: 100},
        ),
        SimpleNamespace(
            result_data={file_utils.UPLOAD_STORAGE_RESERVATION_KEY: True},
        ),
        SimpleNamespace(
            result_data={file_utils.UPLOAD_STORAGE_RESERVATION_KEY: -1},
        ),
        SimpleNamespace(result_data={}),
        SimpleNamespace(result_data=None),
    ]

    assert file_utils.active_upload_storage_reservation_bytes(jobs) == 100


def test_storage_preflight_includes_other_in_flight_uploads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    active_job = SimpleNamespace(
        result_data={file_utils.UPLOAD_STORAGE_RESERVATION_KEY: 600},
    )
    job_store = MagicMock()
    job_store.list_jobs_with_statuses.return_value = [active_job]
    monkeypatch.setattr(file_utils, "JobStore", lambda db: job_store)
    monkeypatch.setattr(
        file_utils,
        "active_render_storage_reservation_bytes",
        lambda **_kwargs: 250,
    )
    ensure = MagicMock(return_value=True)
    monkeypatch.setattr(file_utils, "ensure_storage_capacity", ensure)

    file_utils.require_storage_capacity(
        tmp_path,
        required_bytes=400,
        db=MagicMock(spec=Database),
    )

    assert ensure.call_args.kwargs["required_bytes"] == 1_250


def test_second_render_reservation_cannot_overcommit_same_free_space(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: queued exports each checked the same free-space snapshot
    # before their render slot, so several large variants could all pass and
    # later exhaust the root disk.
    job_store = MagicMock()
    job_store.list_jobs_with_statuses.return_value = []
    monkeypatch.setattr(file_utils, "JobStore", lambda db: job_store)
    observed_required_bytes: list[int] = []

    def bounded_capacity(_data_dir: Path, *, required_bytes: int, **_kwargs) -> bool:
        observed_required_bytes.append(required_bytes)
        return required_bytes <= 1_000

    monkeypatch.setattr(file_utils, "ensure_storage_capacity", bounded_capacity)
    database = MagicMock(spec=Database)

    with lock_media_render(data_dir=tmp_path, capacity=2) as first_slots:
        with file_utils.reserve_render_storage(
            data_dir=tmp_path,
            required_bytes=600,
            render_slots=first_slots,
            db=database,
        ):
            with lock_media_render(data_dir=tmp_path, capacity=2) as second_slots:
                with pytest.raises(HTTPException) as exc_info:
                    with file_utils.reserve_render_storage(
                        data_dir=tmp_path,
                        required_bytes=600,
                        render_slots=second_slots,
                        db=database,
                    ):
                        pass

    assert exc_info.value.status_code == 507
    assert observed_required_bytes == [600, 1_200]
    assert file_utils.active_render_storage_reservation_bytes(
        data_dir=tmp_path,
        capacity=2,
    ) == 0


def test_link_or_copy_file_uses_hard_link_when_available(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "nested" / "destination.bin"
    source.write_bytes(b"subtitle-video")

    file_utils.link_or_copy_file(source, destination)

    assert destination.read_bytes() == b"subtitle-video"
    assert source.stat().st_ino == destination.stat().st_ino


def test_link_or_copy_file_falls_back_to_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"subtitle-video")

    def fail_hard_link(_source: Path, _destination: Path) -> None:
        raise OSError("cross-device link")

    monkeypatch.setattr(file_utils.os, "link", fail_hard_link)
    file_utils.link_or_copy_file(source, destination)

    assert destination.read_bytes() == source.read_bytes()
    assert source.stat().st_ino != destination.stat().st_ino


def test_link_or_copy_file_refuses_to_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    destination = tmp_path / "destination.bin"
    source.write_bytes(b"source")
    destination.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        file_utils.link_or_copy_file(source, destination)

    assert destination.read_bytes() == b"existing"


def test_sanitize_download_filename_preserves_unicode_and_real_extension() -> None:
    # REGRESSION: the static route exposed processed_*.mp4 instead of the requested export name.
    assert file_utils.sanitize_download_filename(
        "Ε Isous_subs.mp4",
        "processed_1080x1920.mp4",
    ) == "Ε Isous_subs.mp4"
    assert file_utils.sanitize_download_filename(
        "../../bad\r\nname.exe",
        "processed.srt",
    ) == "bad__name.srt"
    assert file_utils.sanitize_download_filename(None, "processed.vtt") == "processed.vtt"
