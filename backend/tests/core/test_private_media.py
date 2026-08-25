"""Regression coverage for bounded private-media streaming."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from starlette.types import Message, Scope

from backend.app.core.private_media import (
    PRIVATE_MEDIA_CHUNK_SIZE_BYTES,
    PrivateMediaFileResponse,
)


def _scope(*, range_header: bytes | None = None) -> Scope:
    headers: list[tuple[bytes, bytes]] = []
    if range_header is not None:
        headers.append((b"range", range_header))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/static/artifacts/job/processed.mp4",
        "raw_path": b"/static/artifacts/job/processed.mp4",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 54321),
        "server": ("127.0.0.1", 8080),
        "extensions": {},
    }


async def _receive() -> Message:
    return {"type": "http.request", "body": b"", "more_body": False}


def _log_data(record: logging.LogRecord) -> dict[str, Any]:
    data = getattr(record, "data", None)
    assert isinstance(data, dict)
    return data


def test_private_media_uses_bounded_megabyte_chunks_and_logs_completion(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # REGRESSION: Starlette's 64 KiB default produced 257 backpressured ASGI
    # writes for a 16 MiB download across the two production proxy hops.
    content = b"x" * ((2 * PRIVATE_MEDIA_CHUNK_SIZE_BYTES) + 123)
    media_path = tmp_path / "processed.mp4"
    media_path.write_bytes(content)
    response = PrivateMediaFileResponse(
        media_path,
        job_id="job-123",
        transfer_kind="download",
        filename="export.mp4",
        content_disposition_type="attachment",
    )
    messages: list[Message] = []

    async def send(message: Message) -> None:
        messages.append(message)

    caplog.set_level(logging.INFO, logger="backend.app.core.private_media")
    asyncio.run(response(_scope(), _receive, send))

    body_messages = [message for message in messages if message["type"] == "http.response.body"]
    assert [len(message.get("body", b"")) for message in body_messages] == [
        PRIVATE_MEDIA_CHUNK_SIZE_BYTES,
        PRIVATE_MEDIA_CHUNK_SIZE_BYTES,
        123,
    ]
    data = _log_data(caplog.records[-1])
    assert data["event"] == "private_media_transfer"
    assert data["outcome"] == "completed"
    assert data["job_id"] == "job-123"
    assert data["transfer_kind"] == "download"
    assert data["status_code"] == 200
    assert data["bytes_emitted"] == len(content)
    assert data["range_requested"] is False
    assert data["duration_ms"] >= 0


def test_private_media_range_keeps_exact_semantics_with_large_chunks(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    content = b"r" * (3 * PRIVATE_MEDIA_CHUNK_SIZE_BYTES)
    media_path = tmp_path / "processed.mp4"
    media_path.write_bytes(content)
    response = PrivateMediaFileResponse(
        media_path,
        job_id="job-range",
        transfer_kind="preview",
    )
    messages: list[Message] = []
    range_end = PRIVATE_MEDIA_CHUNK_SIZE_BYTES + 122

    async def send(message: Message) -> None:
        messages.append(message)

    caplog.set_level(logging.INFO, logger="backend.app.core.private_media")
    asyncio.run(
        response(
            _scope(range_header=f"bytes=0-{range_end}".encode("ascii")),
            _receive,
            send,
        ),
    )

    start = next(message for message in messages if message["type"] == "http.response.start")
    headers = {name.decode("latin-1"): value.decode("latin-1") for name, value in start["headers"]}
    body_messages = [message for message in messages if message["type"] == "http.response.body"]
    assert start["status"] == 206
    assert headers["content-range"] == f"bytes 0-{range_end}/{len(content)}"
    assert [len(message.get("body", b"")) for message in body_messages] == [
        PRIVATE_MEDIA_CHUNK_SIZE_BYTES,
        123,
    ]
    data = _log_data(caplog.records[-1])
    assert data["status_code"] == 206
    assert data["bytes_emitted"] == range_end + 1
    assert data["range_requested"] is True
    assert data["content_range"] == headers["content-range"]


def test_private_media_logs_failed_transfer_without_claiming_emitted_bytes(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_path = tmp_path / "processed.mp4"
    media_path.write_bytes(b"x" * PRIVATE_MEDIA_CHUNK_SIZE_BYTES)
    response = PrivateMediaFileResponse(
        media_path,
        job_id="job-failed",
        transfer_kind="download",
    )

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body":
            raise ConnectionError("client disconnected")

    caplog.set_level(logging.INFO, logger="backend.app.core.private_media")
    with pytest.raises(ConnectionError, match="client disconnected"):
        asyncio.run(response(_scope(), _receive, send))

    data = _log_data(caplog.records[-1])
    assert data["outcome"] == "failed"
    assert data["status_code"] == 200
    assert data["bytes_emitted"] == 0


def test_private_media_logs_cancelled_transfer(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_path = tmp_path / "processed.mp4"
    media_path.write_bytes(b"x")
    response = PrivateMediaFileResponse(
        media_path,
        job_id="job-cancelled",
        transfer_kind="download",
    )

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body":
            raise asyncio.CancelledError

    caplog.set_level(logging.INFO, logger="backend.app.core.private_media")
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(response(_scope(), _receive, send))

    data = _log_data(caplog.records[-1])
    assert data["outcome"] == "cancelled"
    assert data["error_type"] == "CancelledError"
    assert data["bytes_emitted"] == 0


def test_private_media_accounts_for_pathsend_servers(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    content = b"sendfile-compatible"
    media_path = tmp_path / "processed.mp4"
    media_path.write_bytes(content)
    response = PrivateMediaFileResponse(
        media_path,
        job_id="job-pathsend",
        transfer_kind="preview",
    )
    messages: list[Message] = []
    scope = _scope()
    scope["extensions"] = {"http.response.pathsend": {}}

    async def send(message: Message) -> None:
        messages.append(message)

    caplog.set_level(logging.INFO, logger="backend.app.core.private_media")
    asyncio.run(response(scope, _receive, send))

    assert any(message["type"] == "http.response.pathsend" for message in messages)
    data = _log_data(caplog.records[-1])
    assert data["outcome"] == "completed"
    assert data["bytes_emitted"] == len(content)


def test_private_media_tolerates_invalid_content_length_in_observer(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    media_path = tmp_path / "processed.mp4"
    media_path.write_bytes(b"x")
    response = PrivateMediaFileResponse(
        media_path,
        job_id="job-invalid-length",
        transfer_kind="preview",
    )
    response.raw_headers.append((b"content-length", b"not-a-number"))

    async def send(message: Message) -> None:
        return None

    caplog.set_level(logging.INFO, logger="backend.app.core.private_media")
    asyncio.run(response(_scope(), _receive, send))

    data = _log_data(caplog.records[-1])
    assert data["outcome"] == "completed"
    assert data["bytes_emitted"] == 1
    assert "content_length" not in data
