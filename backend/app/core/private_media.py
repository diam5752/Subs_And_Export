"""Bounded, observable streaming for authenticated private media."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from starlette.responses import FileResponse
from starlette.types import Message, Receive, Scope, Send

logger = logging.getLogger(__name__)

PRIVATE_MEDIA_CHUNK_SIZE_BYTES = 1024 * 1024
PrivateMediaTransferKind = Literal["download", "preview"]


@dataclass(slots=True)
class _TransferObservation:
    send: Send
    started_at: float
    status_code: int
    range_requested: bool
    bytes_emitted: int = 0
    content_length: int | None = None
    content_range: str | None = None

    async def observe_send(self, message: Message) -> None:
        message_type = message["type"]
        if message_type == "http.response.start":
            self._observe_start(message)
        await self.send(message)
        self._observe_body(message_type, message)

    def _observe_start(self, message: Message) -> None:
        self.status_code = int(message["status"])
        for name, value in message["headers"]:
            normalized_name = name.lower()
            if normalized_name == b"content-length":
                try:
                    self.content_length = int(value.decode("ascii"))
                except (UnicodeDecodeError, ValueError):
                    self.content_length = None
            elif normalized_name == b"content-range":
                self.content_range = value.decode("ascii", errors="replace")

    def _observe_body(self, message_type: str, message: Message) -> None:
        if message_type == "http.response.body":
            self.bytes_emitted += len(message.get("body", b""))
        elif message_type == "http.response.pathsend" and self.content_length is not None:
            self.bytes_emitted = self.content_length

    def log_result(
        self,
        *,
        job_id: str,
        transfer_kind: PrivateMediaTransferKind,
        outcome: str,
        error_type: str | None,
    ) -> None:
        elapsed_seconds = max(time.perf_counter() - self.started_at, 0.0)
        data: dict[str, object] = {
            "event": "private_media_transfer",
            "outcome": outcome,
            "job_id": job_id,
            "transfer_kind": transfer_kind,
            "status_code": self.status_code,
            "bytes_emitted": self.bytes_emitted,
            "range_requested": self.range_requested,
            "duration_ms": round(elapsed_seconds * 1000, 3),
        }
        if self.content_length is not None:
            data["content_length"] = self.content_length
        if self.content_range is not None:
            data["content_range"] = self.content_range
        if self.bytes_emitted > 0 and elapsed_seconds > 0:
            data["throughput_mib_s"] = round(
                (self.bytes_emitted / (1024 * 1024)) / elapsed_seconds,
                3,
            )
        if error_type is not None:
            data["error_type"] = error_type
        log = logger.info if outcome == "completed" else logger.warning
        log("Private media transfer finished", extra={"data": data})


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
        observation = _TransferObservation(
            send=send,
            started_at=time.perf_counter(),
            status_code=self.status_code,
            range_requested=any(name.lower() == b"range" for name, _ in scope.get("headers", [])),
        )
        outcome = "completed"
        error_type: str | None = None

        try:
            await super().__call__(scope, receive, observation.observe_send)
        except asyncio.CancelledError as exc:
            outcome = "cancelled"
            error_type = type(exc).__name__
            raise
        except Exception as exc:
            outcome = "failed"
            error_type = type(exc).__name__
            raise
        finally:
            observation.log_result(
                job_id=self.job_id,
                transfer_kind=self.transfer_kind,
                outcome=outcome,
                error_type=error_type,
            )
