from dataclasses import dataclass
from typing import Literal

from backend.app.core import config


@dataclass
class SubtitleStyle:
    """
    Centralized configuration for subtitle visualization styling.
    """
    font_family: str = "Arial"
    font_size: int = config.DEFAULT_SUB_FONT_SIZE
    primary_color: str = "#FFFF00"
    secondary_color: str = "#FFFFFF"
    stroke_color: str = "black"
    stroke_width: int = 2

    # Rendering Mode
    highlight_style: Literal["static", "karaoke", "pop", "active-graphics"] = "karaoke"

    # Layout
    max_lines: int = 2
    position: int = 16

    # Visual Tweaks
    shadow_strength: int = 4
    margin_x: int = 90
    margin_bottom: int = 320

    def to_renderer_kwargs(self, width: int, height: int) -> dict:
        """
        Helper to convert style object to renderer initialization arguments.
        """
        base = {
            "font": self.font_family,
            "font_size": self.font_size,
            "primary_color": self.primary_color,
            "stroke_color": self.stroke_color,
            "stroke_width": self.stroke_width,
            "width": width,
            "height": height,
            "margin_bottom": self.margin_bottom
        }

        if self.highlight_style == "pop" or self.max_lines == 0:
             # ActiveWordRenderer kwargs
            return base
        else:
            # KaraokeRenderer kwargs
            base.update({
                "secondary_color": self.secondary_color,
                "margin_x": self.margin_x,
                "max_lines": self.max_lines
            })
            return base
