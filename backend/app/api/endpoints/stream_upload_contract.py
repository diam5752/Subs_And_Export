"""Validated transport contract for raw streaming video uploads."""

from __future__ import annotations

import base64
import binascii
import json

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ...core.auth import User
from ...core.config import settings
from ...services import pricing
from ...services.jobs import JobStore
from .file_utils import MAX_UPLOAD_BYTES
from .validation import validate_authorized_credits

MAX_STREAM_UPLOAD_METADATA_HEADER_CHARS = 12_000
MAX_STREAM_UPLOAD_METADATA_BYTES = 9_000


class StreamProcessMetadata(BaseModel):
    """Validated settings sent ahead of a raw streaming video body."""

    model_config = ConfigDict(extra="forbid")

    filename: str = Field(..., min_length=1, max_length=255)
    authorized_credits: int = Field(..., strict=True)
    transcribe_tier: str = Field(settings.default_transcribe_tier, max_length=50)
    transcribe_provider: str = Field(
        settings.transcribe_tier_provider[settings.default_transcribe_tier],
        max_length=50,
    )
    openai_model: str = Field("", max_length=50)
    video_quality: str = Field("high quality", max_length=50)
    video_resolution: str = Field("", max_length=50)
    context_prompt: str = Field("", max_length=5000)
    subtitle_position: int = 16
    max_subtitle_lines: int = 2
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int = 4
    highlight_style: str = Field("karaoke", max_length=20)
    subtitle_size: int = 100
    karaoke_enabled: bool = True
    watermark_enabled: bool = False

    @field_validator("authorized_credits")
    @classmethod
    def authorized_credits_must_be_canonical(cls, value: int) -> int:
        return validate_authorized_credits(value)


def decode_stream_process_metadata(encoded: str | None) -> StreamProcessMetadata:
    if not encoded or len(encoded) > MAX_STREAM_UPLOAD_METADATA_HEADER_CHARS:
        raise HTTPException(status_code=400, detail="Invalid upload metadata")
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_STREAM_UPLOAD_METADATA_BYTES:
            raise ValueError("metadata too large")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("metadata must be an object")
        return StreamProcessMetadata.model_validate(payload)
    except (
        binascii.Error,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValidationError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=400, detail="Invalid upload metadata") from exc


def authorized_video_quote(authorized_credits: int) -> pricing.VideoCreditQuote:
    """Resolve the exact price ceiling already confirmed by the user."""
    for quote in pricing.VIDEO_CREDIT_BRACKETS:
        if quote.credits == authorized_credits:
            return quote
    raise HTTPException(status_code=400, detail="Invalid authorized credits")


def check_concurrent_job_capacity(job_store: JobStore, current_user: User) -> None:
    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= settings.max_concurrent_jobs:
        raise HTTPException(
            status_code=429,
            detail=(
                "Too many active jobs. Please wait for your current jobs to finish "
                f"(max {settings.max_concurrent_jobs})."
            ),
        )


def parse_content_length(
    request: Request,
    *,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> int | None:
    content_length = request.headers.get("content-length")
    if not content_length:
        return None
    try:
        parsed = int(content_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header") from exc
    if parsed <= 0:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header")
    if parsed > max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Request too large; limit is {settings.max_upload_mb}MB",
        )
    return parsed
