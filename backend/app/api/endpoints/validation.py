"""Validation functions for video processing endpoints."""

from __future__ import annotations

import re

from fastapi import HTTPException

# Constants
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}
ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "application/octet-stream",
}
ALLOWED_TRANSCRIBE_PROVIDERS = {"local", "openai", "groq", "whispercpp"}
ALLOWED_VIDEO_QUALITIES = {"low size", "balanced", "high quality"}
ALLOWED_HIGHLIGHT_STYLES = {"static", "karaoke", "pop", "active-graphics", "active"}
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\\-]{0,63}$")


def validate_transcribe_provider(provider: str) -> str:
    """Validate and normalize transcribe provider."""
    normalized = provider.strip().lower()
    if normalized not in ALLOWED_TRANSCRIBE_PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid transcribe provider")
    return normalized


def validate_model_name(value: str, *, allow_empty: bool, field_name: str) -> str | None:
    """Validate model name for security."""
    cleaned = value.strip()
    if not cleaned:
        if allow_empty:
            return None
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if ".." in cleaned or cleaned.startswith(("/", "\\")) or "\\" in cleaned or ":" in cleaned:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    if not MODEL_NAME_PATTERN.match(cleaned):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return cleaned


def validate_video_quality(value: str) -> str:
    """Validate video quality setting."""
    normalized = value.strip().lower()
    if normalized not in ALLOWED_VIDEO_QUALITIES:
        raise HTTPException(status_code=400, detail="Invalid video quality")
    return normalized


def validate_subtitle_position(value: int) -> int:
    """Validate subtitle position (5-35 range)."""
    if value < 5 or value > 35:
        raise HTTPException(status_code=400, detail="subtitle_position out of range (5-35)")
    return value


def validate_max_subtitle_lines(value: int) -> int:
    """Validate max subtitle lines (0-4 range)."""
    if value < 0 or value > 4:
        raise HTTPException(status_code=400, detail="max_subtitle_lines out of range (0-4)")
    return value


def validate_shadow_strength(value: int) -> int:
    """Validate shadow strength (0-10 range)."""
    if value < 0 or value > 10:
        raise HTTPException(status_code=400, detail="shadow_strength out of range (0-10)")
    return value


def validate_subtitle_size(value: int) -> int:
    """Validate subtitle size (50-150 range)."""
    if value < 50 or value > 150:
        raise HTTPException(status_code=400, detail="subtitle_size out of range (50-150)")
    return value


def validate_highlight_style(value: str) -> str:
    """Validate highlight style setting."""
    normalized = value.strip().lower()
    if normalized not in ALLOWED_HIGHLIGHT_STYLES:
        raise HTTPException(status_code=400, detail="Invalid highlight style")
    return normalized


def validate_upload_content_type(content_type: str) -> str:
    """Validate upload content type."""
    normalized = content_type.strip().lower()
    if not normalized:
        normalized = "application/octet-stream"
    if normalized not in ALLOWED_VIDEO_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid content type")
    return normalized
