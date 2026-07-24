"""Helpers for parsing and validating subtitle settings."""

from __future__ import annotations

from backend.app.core.config import settings

SUBTITLE_POSITION_MIN = 5
SUBTITLE_POSITION_MAX = 95
DEFAULT_SUBTITLE_POSITION = 16
ASS_FONT_RENDER_SCALE = 1.12


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


def font_size_for_ass_rendering(font_size: int) -> int:
    """Calibrate CSS-sized text to libass without changing line wrapping."""
    return max(1, int(round(font_size * ASS_FONT_RENDER_SCALE)))


def normalize_subtitle_position(position_value: object) -> int:
    """Return a safe numeric position from the bottom-safe to top-safe edge."""
    if position_value is None:
        return DEFAULT_SUBTITLE_POSITION

    if isinstance(position_value, int) and not isinstance(position_value, bool):
        return max(SUBTITLE_POSITION_MIN, min(SUBTITLE_POSITION_MAX, position_value))
    return DEFAULT_SUBTITLE_POSITION
