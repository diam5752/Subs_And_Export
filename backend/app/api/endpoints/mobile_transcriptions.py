"""Native-client transcription with no server-side video workspace."""

from __future__ import annotations

import asyncio
import math
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ...core.auth import User
from ...core.config import settings
from ...core.media_capacity import (
    MediaExtractionCapacityTimeoutError,
    lock_audio_extraction,
)
from ...core.ratelimit import limiter_processing
from ...services import pricing
from ...services.ffmpeg_utils import probe_media_bytes
from ...services.jobs import JobStore
from ...services.mobile_transcriptions import (
    MobileTranscriptionInProgressError,
    MobileTranscriptionTerminalError,
    get_mobile_transcription_replay,
    process_mobile_transcription,
)
from ...services.usage_ledger import UsageLedgerStore
from ..deps import (
    get_current_user_with_media_lifecycle,
    get_job_store,
    get_usage_ledger_store,
)
from .validation import assert_processing_quote_authorized

router = APIRouter()

MOBILE_AUDIO_MAX_BYTES = 16 * 1024 * 1024
MOBILE_AUDIO_CONTENT_TYPES = frozenset(
    {"audio/mp4", "audio/m4a", "audio/x-m4a"},
)
_IDEMPOTENCY_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


class MobileWordResponse(BaseModel):
    start: float
    end: float
    text: str


class MobileCueResponse(BaseModel):
    start: float
    end: float
    text: str
    words: list[MobileWordResponse]


class MobileTranscriptionResponse(BaseModel):
    request_id: str
    duration_seconds: float
    credits_charged: int
    balance: int
    video_uploaded: bool
    server_media_retained: bool
    cues: list[MobileCueResponse]


def _required_int_header(request: Request, name: str) -> int:
    raw_value = request.headers.get(name)
    try:
        value = int(raw_value or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {name} header") from exc
    if str(value) != raw_value or value <= 0:
        raise HTTPException(status_code=400, detail=f"Invalid {name} header")
    return value


def _request_metadata(request: Request) -> tuple[str, str, int, int | None]:
    idempotency_key = request.headers.get("idempotency-key", "")
    if _IDEMPOTENCY_KEY.fullmatch(idempotency_key) is None:
        raise HTTPException(status_code=400, detail="Invalid Idempotency-Key header")
    content_type = request.headers.get("content-type", "").partition(";")[0].lower()
    if content_type not in MOBILE_AUDIO_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported mobile audio type")
    authorized_credits = _required_int_header(
        request,
        "x-gsubs-authorized-credits",
    )
    raw_length = request.headers.get("content-length")
    content_length = _required_int_header(request, "content-length") if raw_length else None
    if content_length is not None and content_length > MOBILE_AUDIO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Mobile audio is too large")
    return idempotency_key, content_type, authorized_credits, content_length


async def _read_audio_body(request: Request, expected_length: int | None) -> bytes:
    body = bytearray()
    iterator = request.stream().__aiter__()
    while True:
        try:
            chunk = await asyncio.wait_for(
                anext(iterator),
                timeout=settings.upload_inactivity_timeout_seconds,
            )
        except StopAsyncIteration:
            break
        except TimeoutError as exc:
            raise HTTPException(status_code=408, detail="Audio upload stalled") from exc
        body.extend(chunk)
        if len(body) > MOBILE_AUDIO_MAX_BYTES:
            raise HTTPException(status_code=413, detail="Mobile audio is too large")
    if not body or (expected_length is not None and len(body) != expected_length):
        raise HTTPException(status_code=400, detail="Incomplete mobile audio body")
    return bytes(body)


def _authoritative_duration(audio_bytes: bytes, authorized_credits: int) -> float:
    try:
        with lock_audio_extraction(timeout_seconds=5.0):
            probe = probe_media_bytes(audio_bytes)
    except MediaExtractionCapacityTimeoutError as exc:
        raise HTTPException(
            status_code=429,
            detail="Audio validation capacity is temporarily busy",
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not validate mobile audio") from exc
    if probe.has_video:
        raise HTTPException(status_code=400, detail="Mobile audio must not contain video")
    duration = probe.duration_s
    if duration is None or not math.isfinite(duration) or duration <= 0:
        raise HTTPException(status_code=400, detail="Could not determine audio duration")
    if probe.audio_codec != "aac":
        raise HTTPException(status_code=400, detail="Mobile audio must use AAC")
    if duration > settings.max_video_duration_seconds:
        minutes = settings.max_video_duration_seconds / 60
        raise HTTPException(status_code=400, detail=f"Audio too long (max {minutes:.1f} minutes)")
    assert_processing_quote_authorized(
        duration_seconds=duration,
        authorized_credits=authorized_credits,
    )
    return float(duration)


def _response_payload(
    payload: dict[str, object],
    response: Response,
) -> MobileTranscriptionResponse:
    response.headers["Cache-Control"] = "private, no-store"
    return MobileTranscriptionResponse.model_validate(payload)


@router.post(
    "/mobile-transcriptions",
    response_model=MobileTranscriptionResponse,
    dependencies=[Depends(limiter_processing)],
)
async def mobile_transcription(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user_with_media_lifecycle),
    job_store: JobStore = Depends(get_job_store),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
) -> MobileTranscriptionResponse:
    """Return subtitles from audio while keeping all video work on the iPhone."""
    idempotency_key, content_type, credits, content_length = _request_metadata(request)
    replay = await run_in_threadpool(
        get_mobile_transcription_replay,
        user_id=current_user.id,
        idempotency_key=idempotency_key,
        ledger_store=ledger_store,
    )
    if replay is None:
        await run_in_threadpool(
            ledger_store.points_store.assert_can_spend,
            current_user.id,
            pricing.VIDEO_CREDIT_BRACKETS[0].credits,
            require_paid=not settings.mock_external_services,
        )
    audio_bytes = await _read_audio_body(request, content_length)
    duration = await run_in_threadpool(
        _authoritative_duration,
        audio_bytes,
        credits,
    )
    if replay is not None:
        return _response_payload(replay, response)
    try:
        payload = await run_in_threadpool(
            process_mobile_transcription,
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            audio_bytes=audio_bytes,
            content_type=content_type,
            duration_seconds=duration,
            job_store=job_store,
            ledger_store=ledger_store,
        )
    except MobileTranscriptionInProgressError as exc:
        raise HTTPException(status_code=409, detail="Transcription is already in progress") from exc
    except MobileTranscriptionTerminalError as exc:
        raise HTTPException(status_code=409, detail="Previous transcription failed; try again") from exc
    return _response_payload(payload, response)
