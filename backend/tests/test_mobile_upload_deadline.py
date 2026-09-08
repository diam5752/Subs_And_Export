import asyncio

import anyio
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.app.api.endpoints.mobile_transcriptions import _read_audio_body
from backend.app.core.config import settings


def _audio_request(chunks: int) -> Request:
    received = 0

    async def receive():
        nonlocal received
        await asyncio.sleep(0.005)
        received += 1
        return {"type": "http.request", "body": b"x", "more_body": received < chunks}

    return Request({"type": "http", "method": "POST", "path": "/videos/mobile-transcriptions", "headers": []}, receive)


def test_mobile_trickle_cannot_extend_total_deadline(monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_inactivity_timeout_seconds", 1)
    monkeypatch.setattr(settings, "upload_total_timeout_seconds", 0.04)

    async def run() -> None:
        with pytest.raises(HTTPException) as error:
            await _read_audio_body(_audio_request(100), 100)
        assert error.value.status_code == 408
        assert error.value.detail == "Audio upload exceeded the total time limit"

    anyio.run(run)


def test_mobile_audio_within_both_deadlines_succeeds(monkeypatch) -> None:
    monkeypatch.setattr(settings, "upload_inactivity_timeout_seconds", 1)
    monkeypatch.setattr(settings, "upload_total_timeout_seconds", 1)

    async def run() -> None:
        assert await _read_audio_body(_audio_request(3), 3) == b"xxx"

    anyio.run(run)
