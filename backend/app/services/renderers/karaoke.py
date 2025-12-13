import bisect
from typing import List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from backend.app.services.renderers.base import AbstractRenderer
from backend.app.services.renderers.utils import get_font_path
from backend.app.services.subtitles import Cue


class KaraokeRenderer(AbstractRenderer):
    """
    Renders standard subtitles with line logic and optional highlighting.
    Corresponds to max_lines > 0 mode.
    """
    def __init__(
        self,
        cues: List[Cue],
        max_lines: int,
        font: str,
        font_size: int,
        primary_color: str,
        secondary_color: str,
        stroke_color: str,
        stroke_width: int,
        width: int,
        height: int,
        margin_bottom: int,
        margin_x: int,
        enable_highlight: bool = True
    ):
        self.cues = cues
        self.cue_starts = [c.start for c in cues]
        self.max_lines = max_lines
        self.font_path = get_font_path(font)
        self.base_font_size = font_size
        self.primary_color = primary_color
        self.secondary_color = secondary_color
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.width = width
        self.height = height
        self.margin_bottom = margin_bottom
        self.margin_x = margin_x
        self.enable_highlight = enable_highlight

        # State caching
        self.last_active_cue_idx = -1
        self.last_active_word_idx = -1
        self.cached_frame = None
        self.cached_layout = None  # (lines_struct, pil_font, space_width)

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

            img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
            active_frame = np.array(img)
            self.cached_frame = active_frame
            self.last_active_cue_idx = -2
            self.last_active_word_idx = -1
            return active_frame

        if (self.last_active_cue_idx == idx and
            self.last_active_word_idx == active_word_idx):
            return self.cached_frame

        # 3. Render Logic
        img = Image.new('RGBA', (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # --- Multi-line Layout Logic ---

        # Check layout cache
        if self.last_active_cue_idx == idx and self.cached_layout:
             # print("DEBUG: Layout Cache HIT")
             lines_struct, pil_font, space_width, cached_widths = self.cached_layout
        else:
            # print("DEBUG: Layout Cache MISS - computing")
            current_font_size = self.base_font_size
            lines_struct = []
            cached_widths = []  # List[List[float]] corresponding to lines_struct
            pil_font = None
            space_width = 0
            max_text_width = self.width - (self.margin_x * 2)

            if not active_cue.words:
                # Should fallback to standard text, handled elsewhere or robust here?
                # For now, assuming words exist. If not, this logic will produce empty lines.
                pass

            # Optimization for Single Line (max_lines=1)
            if self.max_lines == 1 and active_cue.words:
                    try:
                        base_font = ImageFont.truetype(self.font_path, self.base_font_size)
                    except:
                        base_font = ImageFont.load_default()

                    measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
                    full_text_width = 0
                    space_w = measure_draw.textlength(" ", font=base_font)

                    for i_w, w in enumerate(active_cue.words):
                        full_text_width += measure_draw.textlength(w.text, font=base_font)
                        if i_w < len(active_cue.words) - 1:
                            full_text_width += space_w

                    if full_text_width > max_text_width:
                        scale = max_text_width / full_text_width
                        current_font_size = int(self.base_font_size * scale * 0.95)
                        current_font_size = max(current_font_size, 10)

            # Dynamic Scaler Loop if words available
            if active_cue.words:
                min_font_size = int(self.base_font_size * 0.4)
                if self.max_lines == 1: min_font_size = 10

                while current_font_size >= min_font_size:
                    try:
                        pil_font = ImageFont.truetype(self.font_path, current_font_size)
                    except Exception:
                        pil_font = ImageFont.load_default()

                    measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
                    space_width = measure_draw.textlength(" ", font=pil_font)

                    lines_struct = []
                    current_line = []
                    current_line_width = 0

                    for word in active_cue.words:
                        word_w = measure_draw.textlength(word.text, font=pil_font)
                        added_width = word_w
                        if current_line:
                            added_width += space_width

                        if current_line and (current_line_width + added_width > max_text_width):
                            lines_struct.append(current_line)
                            current_line = [word]
                            current_line_width = word_w
                        else:
                            current_line.append(word)
                            current_line_width += added_width

                    if current_line:
                        lines_struct.append(current_line)

                    if len(lines_struct) <= self.max_lines:
                        break

                    current_font_size = int(current_font_size * 0.9)
                    if current_font_size < min_font_size:
                        break

            # Pre-calculate widths for the chosen layout
            if pil_font and lines_struct:
                measure_draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
                for line in lines_struct:
                    w_list = []
                    for w in line:
                         w_list.append(measure_draw.textlength(w.text, font=pil_font))
                    cached_widths.append(w_list)

            # Store to cache
            self.cached_layout = (lines_struct, pil_font, space_width, cached_widths)

        # Drawing
        if pil_font:
            ascent, descent = pil_font.getmetrics()
            line_height = ascent + descent + 10 # 10px spacing
            text_block_height = len(lines_struct) * line_height
            start_y = self.height - self.margin_bottom - text_block_height
            current_y = start_y

            active_word_ref = None
            if active_word_idx is not None and active_cue.words:
                active_word_ref = active_cue.words[active_word_idx]

            for i_line, line_words in enumerate(lines_struct):
                # Use cached widths if available
                widths = cached_widths[i_line] if i_line < len(cached_widths) else []
                if not widths: # Fallback should not happen if logic correct
                     widths = [draw.textlength(w.text, font=pil_font) for w in line_words]

                # Center line
                line_w_total = sum(widths) + (len(widths) - 1) * space_width if widths else 0
                current_x = (self.width - line_w_total) // 2

                for i_w, w in enumerate(line_words):
                    is_active = (w is active_word_ref)
                    if not self.enable_highlight:
                         # Force primary color for all words if highlight disabled (static look)
                         fill_color = self.primary_color
                    else:
                         fill_color = self.primary_color if is_active else self.secondary_color

                    draw.text(
                        (current_x, current_y),
                        w.text,
                        font=pil_font,
                        fill=fill_color,
                        stroke_width=self.stroke_width,
                        stroke_fill=self.stroke_color,
                        anchor="lt"
                    )

                    current_x += widths[i_w]
                    if i_w < len(line_words) - 1:
                        current_x += space_width

                current_y += line_height

        active_frame = np.array(img)
        self.cached_frame = active_frame
        self.last_active_cue_idx = idx
        self.last_active_word_idx = active_word_idx

        return active_frame
