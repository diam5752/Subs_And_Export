"""Request and response models shared by export routes."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...core.config import settings
from ...services.subtitle_exports import SUBTITLE_EXPORT_FORMATS
from ...services.video_quality import crf_for_video_quality


class ExportRequest(BaseModel):
    resolution: str = Field(..., max_length=50)
    subtitle_position: int | None = None
    max_subtitle_lines: int | None = None
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int | None = None
    highlight_style: str | None = Field(None, max_length=20)
    subtitle_size: int | None = None
    karaoke_enabled: bool | None = None
    watermark_enabled: bool | None = None
    video_quality: str | None = Field(None, max_length=50)

    @field_validator("subtitle_color")
    @classmethod
    def validate_subtitle_color(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not re.match(r"^&H[0-9A-Fa-f]{8}$", value):
            raise ValueError("Invalid subtitle color format (expected &HAABBGGRR)")
        return value

    @field_validator("video_quality")
    @classmethod
    def validate_video_quality_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        crf_for_video_quality(normalized)
        return normalized

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, value: str) -> str:
        cleaned = value.strip().lower().replace("×", "x")
        if cleaned in SUBTITLE_EXPORT_FORMATS:
            return cleaned
        parts = cleaned.split("x")
        if len(parts) != 2:
            raise ValueError("Invalid resolution format (expected WIDTHxHEIGHT or subtitle export format)")
        try:
            width, height = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValueError("Invalid resolution format (expected WIDTHxHEIGHT or subtitle export format)") from exc
        if width <= 0 or height <= 0:
            raise ValueError("Resolution dimensions must be positive")
        if width > settings.max_resolution_dimension or height > settings.max_resolution_dimension:
            raise ValueError(f"Resolution exceeds max {settings.max_resolution_dimension}")
        return f"{width}x{height}"


class ArtifactDownloadGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_path: str = Field(..., min_length=1, max_length=1_024)
    filename: str = Field(..., min_length=1, max_length=255)


class ArtifactDownloadGrantResponse(BaseModel):
    download_url: str
    expires_in: int
