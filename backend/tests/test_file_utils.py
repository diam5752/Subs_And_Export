from pathlib import Path

import anyio
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.api.endpoints import file_utils


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
