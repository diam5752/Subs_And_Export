import bisect
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw

from backend.app.services.renderers.base import AbstractRenderer
from backend.app.services.renderers.utils import get_font_path, load_font
from backend.app.services.subtitles import Cue


class ActiveWordRenderer(AbstractRenderer):
    """
    Renders one word at a time, popped in the center.
    Corresponds to max_lines=0 mode.
    """
    def __init__(
        self,
        cues: List[Cue],
        font: str,
        font_size: int,
        primary_color: str,
        stroke_color: str,
        stroke_width: int,
        width: int,
        height: int,
        margin_bottom: int
    ):
        self.cues = cues
        self.cue_starts = [c.start for c in cues]
        self.font_path = get_font_path(font)
        self.base_font_size = font_size
        self.primary_color = primary_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.width = width
        self.height = height
        self.margin_bottom = margin_bottom

        # State caching
        self.last_active_cue_idx = -1
        self.last_active_word_idx = -1
        self.cached_frame = None

    def _find_active_word(self, cue: Cue, t: float) -> Optional[int]:
        if not cue.words: return None
        for i, w in enumerate(cue.words):
            if w.start <= t < w.end:
                return i
        return None

    def render_frame(self, t: float) -> np.ndarray:
        # 1. Find Active Cue
        idx = bisect.bisect_right(self.cue_starts, t) - 1

        active_cue = None
        active_word_idx = None

        if idx >= 0:
            candidate = self.cues[idx]
            if candidate.start <= t < candidate.end:
                active_cue = candidate
                active_word_idx = self._find_active_word(candidate, t)

        # 2. Check Cache
        if active_cue is None:
            if self.last_active_cue_idx == -2:
                return self.cached_frame

            # Draw Clear
            img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
            active_frame = np.array(img)

            self.cached_frame = active_frame
            self.last_active_cue_idx = -2
            self.last_active_word_idx = -1
            return active_frame

        if (self.last_active_cue_idx == idx and
            self.last_active_word_idx == active_word_idx):
            return self.cached_frame

        # 3. Render
        img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        if active_word_idx is not None and active_cue.words:
            word_obj = active_cue.words[active_word_idx]
            sw_font = load_font(self.font_path, self.base_font_size)

            w_len = draw.textlength(word_obj.text, font=sw_font)
            x = (self.width - w_len) // 2
            y = self.height - self.margin_bottom - self.base_font_size

            draw.text(
                (x, y),
                word_obj.text,
                font=sw_font,
                fill=self.primary_color,
                stroke_width=self.stroke_width,
                stroke_fill=self.stroke_color,
                anchor="lt"
            )

        active_frame = np.array(img)
        self.cached_frame = active_frame
        self.last_active_cue_idx = idx
        self.last_active_word_idx = active_word_idx

        return active_frame
