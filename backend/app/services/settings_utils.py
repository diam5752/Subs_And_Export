"""Helpers for parsing and validating subtitle settings."""

from __future__ import annotations

from typing import Union

from backend.app.core.config import settings


def font_size_from_subtitle_size(subtitle_size: int | None) -> int:
    """
    Map the UI's subtitle size slider value (50-150%) to ASS font sizes.

    The slider sends a numeric percentage where:
    - 50 = 50% of base (very small)
    - 100 = 100% of base (standard)
    - 150 = 150% of base (maximum impact)
    """
    size = subtitle_size if subtitle_size is not None else 100
    # Clamp to valid range
    size = max(50, min(150, size))
    base = settings.default_sub_font_size
    return int(round(base * size / 100))


def parse_legacy_position(position_value: Union[int, str, None]) -> int:
    """
    Parse legacy string position values and new numeric values.

    Handles backward compatibility:
    - "top" -> 32
    - "default" -> 16
    - "bottom" -> 6
    - numeric values passed through directly
    """
    if position_value is None:
        return 16  # Default middle position

    if isinstance(position_value, int):
        return max(5, min(50, position_value))

    if isinstance(position_value, str):
        legacy_map = {"top": 32, "default": 16, "bottom": 6}
        return legacy_map.get(position_value.lower().strip(), 16)

    return 16  # Fallback to default
