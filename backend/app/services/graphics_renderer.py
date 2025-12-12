from pathlib import Path
from typing import List

from moviepy import CompositeVideoClip, VideoClip, VideoFileClip

from backend.app.core import config
from backend.app.services.renderers.active_word import ActiveWordRenderer
from backend.app.services.renderers.karaoke import KaraokeRenderer
from backend.app.services.renderers.utils import resize_and_pad_video
from backend.app.services.subtitles import Cue

# Constants for positioning
SAFE_MARGIN_X = config.DEFAULT_SUB_MARGIN_L
SAFE_MARGIN_Y_BOTTOM = config.DEFAULT_SUB_MARGIN_V # Approx 320 from bottom

def render_active_word_video(
    input_path: Path,
    output_path: Path,
    cues: List[Cue],
    font: str = "Arial",
    font_size: int = config.DEFAULT_SUB_FONT_SIZE,
    primary_color: str = "#FFFF00", # Yellow
    secondary_color: str = "#FFFFFF", # White
    stroke_color: str = "black",
    stroke_width: int = 2,
    target_width: int = config.DEFAULT_WIDTH,
    target_height: int = config.DEFAULT_HEIGHT,
    max_lines: int = 2,
    karaoke_enabled: bool = True
) -> Path:
    """
    Renders video with 'Active Word' (pop) or 'Karaoke' style using MoviePy & PIL.
    Optimized to use a single VideoClip with a frame generator to avoid
    performance bottlenecks with thousands of clips.

    Delegates actual frame rendering to the appropriate Renderer strategy.
    """

    video = VideoFileClip(str(input_path))

    # 1. Resize & Pad (Normalize)
    video = resize_and_pad_video(video, target_width, target_height)

    W, H = video.size

    # 2. Select Renderer Strategy
    renderer = None
    if max_lines == 0:
        renderer = ActiveWordRenderer(
            cues=cues,
            font=font,
            font_size=font_size,
            primary_color=primary_color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            width=W,
            height=H,
            margin_bottom=SAFE_MARGIN_Y_BOTTOM
        )
    else:
        renderer = KaraokeRenderer(
            cues=cues,
            max_lines=max_lines,
            font=font,
            font_size=font_size,
            primary_color=primary_color,
            secondary_color=secondary_color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            width=W,
            height=H,
            margin_bottom=SAFE_MARGIN_Y_BOTTOM,
            margin_x=SAFE_MARGIN_X,
            enable_highlight=karaoke_enabled
        )

    def make_frame(t):
        return renderer.render_frame(t)

    # Create the subtitle clip
    subtitle_clip = VideoClip(make_frame, duration=video.duration)

    # 3. Write
    final = CompositeVideoClip([video, subtitle_clip])
    final.write_videofile(
        str(output_path),
        fps=video.fps or 30,
        codec="libx264",
        audio_codec="aac",
        logger=None # Silent
    )

    return output_path
