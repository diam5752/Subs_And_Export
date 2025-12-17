from pathlib import Path

try:
    from moviepy.editor import VideoFileClip, vfx
except ModuleNotFoundError:  # MoviePy >= 2.0
    from moviepy import VideoFileClip, vfx
from PIL import ImageFont


def get_font_path(font_name: str) -> str:
    """Resolve font path - crude fallback for system fonts."""
    # This is a simplification. Ideally use matplotlib font manager or hardcoded paths.
    # For macOS/Arial Black:
    possible_paths = [
        "/Library/Fonts/Arial Black.ttf",
        "/System/Library/Fonts/Supplemental/Arial Black.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf"
    ]
    for p in possible_paths:
        if Path(p).exists():
            return p
    return "Arial" # PIL default fallback often fails, but let's hope.

def resize_and_pad_video(video: VideoFileClip, target_width: int, target_height: int) -> VideoFileClip:
    """
    Resize video to fit within target dimensions while preserving aspect ratio,
    then pad with black bars to fill the frame.
    """
    w, h = video.size
    target_ratio = target_width / target_height
    ratio = w / h

    if ratio > target_ratio:
        new_w = target_width
        new_h = int(target_width / ratio)
    else:
        new_h = target_height
        new_w = int(target_height * ratio)

    video = video.with_effects([vfx.Resize(new_size=(new_w, new_h))])

    # Pad to target size (centered)
    pad_left = (target_width - new_w) // 2
    pad_top = (target_height - new_h) // 2

    # color argument expects tuple (0,0,0) or similar
    video = video.with_effects([vfx.Margin(left=pad_left, top=pad_top, right=target_width-new_w-pad_left, bottom=target_height-new_h-pad_top, color=(0,0,0))])

    return video

def load_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()
