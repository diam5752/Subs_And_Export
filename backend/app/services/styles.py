from dataclasses import dataclass
from typing import Literal

from backend.app.core.config import settings

SubtitleHighlightStyle = Literal["static", "karaoke", "pop", "active-graphics"]


@dataclass(slots=True)
class SubtitleStyle:
    """
    Centralized configuration for subtitle visualization styling.
    """
    font_family: str = "Arial"
    font_size: int = settings.default_sub_font_size
    primary_color: str = "#FFFF00"
    secondary_color: str = "#FFFFFF"
    stroke_color: str = "black"
    stroke_width: int = 2

    # Rendering Mode
    highlight_style: SubtitleHighlightStyle = "karaoke"

    # Layout
    max_lines: int = 2
    position: int = 16

    # Visual Tweaks
    shadow_strength: int = 4
    margin_x: int = 90
    margin_bottom: int = 320
