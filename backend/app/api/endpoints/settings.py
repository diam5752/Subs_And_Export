"""Processing settings models and builders for video processing endpoints."""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException
from pydantic import BaseModel

from ...core.config import settings
from ...services import pricing

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

    transcribe_model: str = settings.default_transcribe_tier
    transcribe_provider: str = "groq"
    openai_model: str | None = None
    video_quality: str = "high quality"
    target_width: int | None = None
    target_height: int | None = None
    use_llm: bool = settings.use_llm_by_default
    context_prompt: str = ""
    llm_model: str = settings.llm_model
    llm_temperature: float = settings.llm_temperature
    subtitle_position: int = 16  # 5-35 percentage from bottom
    max_subtitle_lines: int = 2
    subtitle_color: str | None = None
    shadow_strength: int = 4
    highlight_style: str = "karaoke"
    subtitle_size: int = 100  # 50-150 percentage scale
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


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
    transcribe_model: str,
    transcribe_provider: str,
    openai_model: str,
    video_quality: str,
    video_resolution: str,
    use_llm: bool,
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
    # Security: Validate input lengths to prevent DoS
    if len(context_prompt) > 5000:
        raise HTTPException(status_code=400, detail="Context prompt too long (max 5000 chars)")
    if len(transcribe_model) > 50:
        raise HTTPException(status_code=400, detail="Model name too long")
    if len(video_quality) > 50:
        raise HTTPException(status_code=400, detail="Video quality string too long")
    if len(transcribe_provider) > 50:
        raise HTTPException(status_code=400, detail="Provider name too long")
    if len(openai_model) > 50:
        raise HTTPException(status_code=400, detail="OpenAI model name too long")
    if len(video_resolution) > 50:
        raise HTTPException(status_code=400, detail="Resolution string too long")
    if len(highlight_style) > 20:
        raise HTTPException(status_code=400, detail="Highlight style too long")

    tier = validate_transcribe_tier(transcribe_model)
    provider = validate_transcribe_provider(transcribe_provider) if transcribe_provider else settings.transcribe_tier_provider[tier]
    expected_provider = settings.transcribe_tier_provider[tier]
    if provider != expected_provider:
        raise HTTPException(status_code=400, detail="transcribe_provider does not match selected tier")

    openai_model_value = validate_model_name(openai_model, allow_empty=True, field_name="openai_model")

    quality = validate_video_quality(video_quality)
    subtitle_position = validate_subtitle_position(subtitle_position)
    max_subtitle_lines = validate_max_subtitle_lines(max_subtitle_lines)
    shadow_strength = validate_shadow_strength(shadow_strength)
    highlight_style = validate_highlight_style(highlight_style)
    subtitle_size = validate_subtitle_size(subtitle_size)

    if subtitle_color:
        if len(subtitle_color) > 20:
            raise HTTPException(status_code=400, detail="Subtitle color too long")
        if not re.match(r"^&H[0-9A-Fa-f]{8}$", subtitle_color):
            raise HTTPException(status_code=400, detail="Invalid subtitle color format (expected &HAABBGGRR)")

    target_width, target_height = parse_resolution(video_resolution)
    llm_models = pricing.resolve_llm_models(tier)
    return ProcessingSettings(
        transcribe_model=tier,
        transcribe_provider=provider,
        openai_model=openai_model_value,
        video_quality=quality,
        target_width=target_width,
        target_height=target_height,
        use_llm=use_llm,
        context_prompt=context_prompt,
        subtitle_position=subtitle_position,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_color=subtitle_color,
        shadow_strength=shadow_strength,
        highlight_style=highlight_style,
        subtitle_size=subtitle_size,
        karaoke_enabled=karaoke_enabled,
        watermark_enabled=watermark_enabled,
        llm_model=llm_models.social,
    )
