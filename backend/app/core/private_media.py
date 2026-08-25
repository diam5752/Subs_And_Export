"""Bounded, observable streaming for authenticated private media."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Literal

from starlette.responses import FileResponse
from starlette.types import Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

PRIVATE_MEDIA_CHUNK_SIZE_BYTES = 1024 * 1024
PrivateMediaTransferKind = Literal["download", "preview"]


class PrivateMediaFileResponse(FileResponse):
    """Stream private files in bounded MiB frames and record transfer results."""

    chunk_size = PRIVATE_MEDIA_CHUNK_SIZE_BYTES

    def __init__(
        self,
        path: Path,
        *,
        job_id: str,
        transfer_kind: PrivateMediaTransferKind,
        filename: str | None = None,
        content_disposition_type: str = "attachment",
    ) -> None:
        super().__init__(
            path,
            filename=filename,
            content_disposition_type=content_disposition_type,
        )
        self.job_id = job_id
        self.transfer_kind = transfer_kind

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started_at = time.perf_counter()
        bytes_emitted = 0
        status_code = self.status_code
        content_length: int | None = None
        content_range: str | None = None
        outcome = "completed"
        error_type: str | None = None
        range_requested = any(name.lower() == b"range" for name, _ in scope.get("headers", []))

        async def observed_send(message: Message) -> None:
            nonlocal bytes_emitted, content_length, content_range, status_code
            message_type = message["type"]
            if message_type == "http.response.start":
                status_code = int(message["status"])
                for name, value in message["headers"]:
                    normalized_name = name.lower()
                    if normalized_name == b"content-length":
                        try:
                            content_length = int(value.decode("ascii"))
                        except (UnicodeDecodeError, ValueError):
                            content_length = None
                    elif normalized_name == b"content-range":
                        content_range = value.decode("ascii", errors="replace")

            await send(message)

            if message_type == "http.response.body":
                bytes_emitted += len(message.get("body", b""))
            elif message_type == "http.response.pathsend" and content_length is not None:
                bytes_emitted = content_length

        try:
            await super().__call__(scope, receive, observed_send)
        except asyncio.CancelledError as exc:
            outcome = "cancelled"
            error_type = type(exc).__name__
            raise
        except Exception as exc:
            outcome = "failed"
            error_type = type(exc).__name__
            raise
        finally:
            elapsed_seconds = max(time.perf_counter() - started_at, 0.0)
            data: dict[str, object] = {
                "event": "private_media_transfer",
                "outcome": outcome,
                "job_id": self.job_id,
                "transfer_kind": self.transfer_kind,
                "status_code": status_code,
                "bytes_emitted": bytes_emitted,
                "range_requested": range_requested,
                "duration_ms": round(elapsed_seconds * 1000, 3),
            }
            if content_length is not None:
                data["content_length"] = content_length
            if content_range is not None:
                data["content_range"] = content_range
            if bytes_emitted > 0 and elapsed_seconds > 0:
                data["throughput_mib_s"] = round(
                    (bytes_emitted / (1024 * 1024)) / elapsed_seconds,
                    3,
                )
            if error_type is not None:
                data["error_type"] = error_type

            log = logger.info if outcome == "completed" else logger.warning
            log("Private media transfer finished", extra={"data": data})
