import json
import math
import subprocess
from pathlib import Path
from typing import List, Tuple

from backend.app.core import config
from backend.app.services.renderers.active_word import ActiveWordRenderer
from backend.app.services.renderers.karaoke import KaraokeRenderer
from backend.app.services.subtitles import Cue

# Constants for positioning
SAFE_MARGIN_X = config.DEFAULT_SUB_MARGIN_L
SAFE_MARGIN_Y_BOTTOM = config.DEFAULT_SUB_MARGIN_V  # Approx 320 from bottom


def _get_video_metadata(path: Path) -> Tuple[int, int, float, float, bool]:
    """
    Returns (width, height, fps, duration, has_audio).
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "stream=width,height,r_frame_rate,duration,codec_type",
        "-of", "json",
        str(path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)

    video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)

    if not video_stream:
        # Fallback if ffprobe fails to identify streams (rare)
        raise ValueError(f"No video stream found in {path}")

    width = int(video_stream.get("width", config.DEFAULT_WIDTH))
    height = int(video_stream.get("height", config.DEFAULT_HEIGHT))

    fps = 30.0
    if "r_frame_rate" in video_stream:
        try:
            num, den = map(int, video_stream["r_frame_rate"].split("/"))
            if den != 0:
                fps = num / den
        except Exception:
            pass

    duration = 0.0
    try:
        duration = float(video_stream.get("duration", 0))
    except (ValueError, TypeError):
        pass

    if duration == 0.0:
        # Try format duration
        cmd_fmt = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json",
            str(path)
        ]
        try:
            res_fmt = subprocess.run(cmd_fmt, capture_output=True, text=True, check=True)
            data_fmt = json.loads(res_fmt.stdout)
            duration = float(data_fmt.get("format", {}).get("duration", 0))
        except Exception:
            pass

    return width, height, fps, duration, (audio_stream is not None)


def render_active_word_video(
    input_path: Path,
    output_path: Path,
    cues: List[Cue],
    font: str = "Arial",
    font_size: int = config.DEFAULT_SUB_FONT_SIZE,
    primary_color: str = "#FFFF00",  # Yellow
    secondary_color: str = "#FFFFFF",  # White
    stroke_color: str = "black",
    stroke_width: int = 2,
    target_width: int = config.DEFAULT_WIDTH,
    target_height: int = config.DEFAULT_HEIGHT,
    max_lines: int = 2,
    karaoke_enabled: bool = True
) -> Path:
    """
    Renders video with 'Active Word' (pop) or 'Karaoke' style using FFmpeg overlay + Python frame generation.
    Optimized to avoid full video decoding in Python (MoviePy).
    """

    # 1. Probe Input
    src_width, src_height, fps, duration, has_audio = _get_video_metadata(input_path)

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
            width=target_width,
            height=target_height,
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
            width=target_width,
            height=target_height,
            margin_bottom=SAFE_MARGIN_Y_BOTTOM,
            margin_x=SAFE_MARGIN_X,
            enable_highlight=karaoke_enabled
        )

    # 3. Build FFmpeg Filtergraph
    # We rely on FFmpeg to handle the base video.
    # Input 0: Base Video
    # Input 1: Raw Stream from Pipe (RGBA)

    # Scale base video to target (fit logic)
    scale_filter = (
        f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease,"
        f"pad={target_width}:{target_height}:(ow-iw)/2:(oh-ih)/2"
    )

    filter_complex = f"[0:v]{scale_filter}[bg];[bg][1:v]overlay=0:0:format=auto[out]"

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(input_path),
        "-f", "rawvideo",
        "-pix_fmt", "rgba",
        "-s", f"{target_width}x{target_height}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-filter_complex", filter_complex,
        "-map", "[out]",
        # Audio handling
    ]

    if has_audio:
        cmd.extend(["-map", "0:a"])

    # Encoding settings
    cmd.extend([
        "-c:v", "libx264",
        "-preset", config.DEFAULT_VIDEO_PRESET,
        "-crf", "18",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path)
    ])

    # Check for Hardware Acceleration (Mac)
    import platform
    if platform.system() == "Darwin" and config.USE_HW_ACCEL:
        try:
            idx = cmd.index("libx264")
            cmd[idx] = "h264_videotoolbox"
            if "-crf" in cmd:
                c_idx = cmd.index("-crf")
                cmd.pop(c_idx)
                cmd.pop(c_idx)
                cmd.extend(["-q:v", "65"])
            if "-preset" in cmd:
                p_idx = cmd.index("-preset")
                cmd.pop(p_idx)
                cmd.pop(p_idx)
        except ValueError:
            pass

    # 4. Execute Pipeline
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        # Generate frames
        total_frames = int(math.ceil(duration * fps))

        for i in range(total_frames):
            t = i / fps
            frame = renderer.render_frame(t)  # Returns numpy array (H, W, 4) uint8

            # Verify frame size matches target (sanity check)
            # frame.shape is (height, width, 4)
            if frame.shape[0] != target_height or frame.shape[1] != target_width:
                # This should trigger if renderer is buggy.
                # Let's log or warn?
                pass

            try:
                process.stdin.write(frame.tobytes())
            except BrokenPipeError:
                # FFmpeg stopped reading (maybe error or finished)
                break

        process.stdin.close()
        process.wait()

        if process.returncode != 0:
            _, stderr = process.communicate()
            raise RuntimeError(f"FFmpeg failed: {stderr.decode('utf-8', errors='ignore')}")

    except Exception as e:
        process.kill()
        raise e

    return output_path
