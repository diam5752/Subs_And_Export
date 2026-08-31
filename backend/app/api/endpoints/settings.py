"""Processing settings models and builders for video processing endpoints."""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException
from pydantic import BaseModel

from ...core.config import settings
from .validation import (
    validate_highlight_style,
    validate_max_subtitle_lines,
    validate_model_name,
    validate_shadow_strength,
    validate_subtitle_position,
    validate_subtitle_size,
    validate_transcribe_provider,
    validate_transcribe_tier,
    validate_video_quality,
)

logger = logging.getLogger(__name__)


class ProcessingSettings(BaseModel):
    """Settings for video processing."""

    transcribe_tier: str = settings.default_transcribe_tier
    transcribe_provider: str = "groq"
    openai_model: str | None = None
    video_quality: str = "high quality"
    target_width: int | None = None
    target_height: int | None = None
    context_prompt: str = ""
    subtitle_position: int = 16  # 5-95 progression from safe bottom to safe top
    max_subtitle_lines: int = 2
    subtitle_color: str | None = None
    shadow_strength: int = 4
    highlight_style: str = "karaoke"
    subtitle_size: int = 100  # 50-150 percentage scale
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


ALLOWED_TIER_PROVIDER_OVERRIDES: dict[str, set[str]] = {
    "standard": {"mock", "groq", "local"},
    "pro": {"mock", "elevenlabs", "groq", "openai", "local"},
}


def _validate_request_field_lengths(
    *,
    context_prompt: str,
    transcribe_tier: str,
    video_quality: str,
    transcribe_provider: str,
    openai_model: str,
    video_resolution: str,
    highlight_style: str,
) -> None:
    limits = (
        (context_prompt, 5000, "Context prompt too long (max 5000 chars)"),
        (transcribe_tier, 50, "Model name too long"),
        (video_quality, 50, "Video quality string too long"),
        (transcribe_provider, 50, "Provider name too long"),
        (openai_model, 50, "OpenAI model name too long"),
        (video_resolution, 50, "Resolution string too long"),
        (highlight_style, 20, "Highlight style too long"),
    )
    for value, maximum, detail in limits:
        if len(value) > maximum:
            raise HTTPException(status_code=400, detail=detail)


def _resolve_transcribe_settings(
    transcribe_tier: str,
    transcribe_provider: str,
    openai_model: str,
) -> tuple[str, str, str | None]:
    tier = validate_transcribe_tier(transcribe_tier)
    provider = (
        validate_transcribe_provider(transcribe_provider)
        if transcribe_provider
        else settings.transcribe_tier_provider[tier]
    )
    if provider not in ALLOWED_TIER_PROVIDER_OVERRIDES[tier]:
        raise HTTPException(
            status_code=400,
            detail="transcribe_provider does not match selected tier",
        )

    model = validate_model_name(
        openai_model,
        allow_empty=True,
        field_name="openai_model",
    )
    if model and provider != "openai":
        raise HTTPException(
            status_code=400,
            detail="openai_model requires transcribe_provider=openai",
        )
    if settings.mock_external_services:
        return tier, "mock", None
    return tier, provider, model


def _validate_subtitle_color(subtitle_color: str | None) -> str | None:
    if not subtitle_color:
        return subtitle_color
    if len(subtitle_color) > 20:
        raise HTTPException(status_code=400, detail="Subtitle color too long")
    if not re.match(r"^&H[0-9A-Fa-f]{8}$", subtitle_color):
        raise HTTPException(
            status_code=400,
            detail="Invalid subtitle color format (expected &HAABBGGRR)",
        )
    return subtitle_color


def parse_resolution(res_str: str | None) -> tuple[int | None, int | None]:
    """Parse resolution strings like '1080x1920' or '2160×3840'.

    Returns:
        Tuple of (width, height) or (None, None) if empty/invalid
    """
    if not res_str:
        return None, None
    cleaned = res_str.lower().replace("×", "x")
    parts = cleaned.split("x")
    if len(parts) != 2:
        return None, None
    try:
        w = int(parts[0])
        h = int(parts[1])
        if w > 0 and h > 0:
            if w > settings.max_resolution_dimension or h > settings.max_resolution_dimension:
                logger.warning(f"Resolution {w}x{h} exceeds max {settings.max_resolution_dimension}")
                return None, None
            return w, h
    except Exception as e:
        logger.warning(f"Failed to parse resolution: {e}")
    return None, None


def build_processing_settings(
    *,
    transcribe_tier: str,
    transcribe_provider: str,
    openai_model: str,
    video_quality: str,
    video_resolution: str,
    context_prompt: str,
    subtitle_position: int,
    max_subtitle_lines: int,
    subtitle_color: str | None,
    shadow_strength: int,
    highlight_style: str,
    subtitle_size: int,
    karaoke_enabled: bool,
    watermark_enabled: bool,
) -> ProcessingSettings:
    """Build and validate processing settings from request parameters.

    Raises:
        HTTPException: If any validation fails
    """
    _validate_request_field_lengths(
        context_prompt=context_prompt,
        transcribe_tier=transcribe_tier,
        video_quality=video_quality,
        transcribe_provider=transcribe_provider,
        openai_model=openai_model,
        video_resolution=video_resolution,
        highlight_style=highlight_style,
    )
    tier, provider, openai_model_value = _resolve_transcribe_settings(
        transcribe_tier,
        transcribe_provider,
        openai_model,
    )

    quality = validate_video_quality(video_quality)
    subtitle_position = validate_subtitle_position(subtitle_position)
    max_subtitle_lines = validate_max_subtitle_lines(max_subtitle_lines)
    shadow_strength = validate_shadow_strength(shadow_strength)
    highlight_style = validate_highlight_style(highlight_style)
    subtitle_size = validate_subtitle_size(subtitle_size)

    subtitle_color = _validate_subtitle_color(subtitle_color)

    target_width, target_height = parse_resolution(video_resolution)
    return ProcessingSettings(
        transcribe_tier=tier,
        transcribe_provider=provider,
        openai_model=openai_model_value,
        video_quality=quality,
        target_width=target_width,
        target_height=target_height,
        context_prompt=context_prompt,
        subtitle_position=subtitle_position,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_color=subtitle_color,
        shadow_strength=shadow_strength,
        highlight_style=highlight_style,
        subtitle_size=subtitle_size,
        karaoke_enabled=karaoke_enabled,
        watermark_enabled=watermark_enabled,
    )
