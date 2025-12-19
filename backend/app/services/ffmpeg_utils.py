"""FFMPEG wrappers and media probing utilities."""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import select
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.app.core import config

logger = logging.getLogger(__name__)

TIME_PATTERN = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")


@dataclass(frozen=True)
class MediaProbe:
    duration_s: float | None
    audio_codec: str | None

    @property
    def audio_is_aac(self) -> bool:
        return (self.audio_codec or "").lower() == "aac"


def probe_media(input_path: Path) -> MediaProbe:
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "format=duration:stream=codec_name",
        "-of",
        "json",
        str(input_path),
    ]
    result = subprocess.run(
        probe_cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    probe_payload = json.loads(result.stdout or "{}")

    duration_s: float | None = None
    try:
        duration_raw = (probe_payload.get("format") or {}).get("duration")
        if duration_raw is not None:
            duration_s = float(duration_raw)
    except (TypeError, ValueError):
        duration_s = None

    audio_codec: str | None = None
    streams = probe_payload.get("streams") or []
    if isinstance(streams, list) and streams:
        first_stream = streams[0]
        if isinstance(first_stream, dict):
            codec_name = first_stream.get("codec_name")
            if isinstance(codec_name, str) and codec_name.strip():
                audio_codec = codec_name.strip().lower()

    return MediaProbe(duration_s=duration_s, audio_codec=audio_codec)


def input_audio_is_aac(input_path: Path) -> bool:
    try:
        return probe_media(input_path).audio_is_aac
    except Exception as e:
        logger.warning(f"Failed to probe audio codec: {e}")
        return False


def build_filtergraph(
    ass_path: Path,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
    watermark_enabled: bool = False
) -> str:
    ass_file = ass_path.as_posix().replace("'", r"\'")
    ass_filter = f"ass='{ass_file}'"

    logger.debug("FFmpeg filtergraph target dimensions: width=%s height=%s", target_width, target_height)

    # If no target dimensions, skip scaling - keep original resolution
    if target_width is None and target_height is None:
        return f"format=yuv420p,{ass_filter}"

    width = target_width or config.DEFAULT_WIDTH
    height = target_height or config.DEFAULT_HEIGHT
    scale = (
        f"scale={width}:-2:force_original_aspect_ratio=decrease"
    )
    pad = (
        f"pad={width}:{height}:"
        f"({width}-iw)/2:({height}-ih)/2"
    )
    graph = ",".join([scale, pad, "format=yuv420p"])

    if watermark_enabled and config.WATERMARK_PATH.exists():
        # Clean path for FFmpeg
        wm_path = config.WATERMARK_PATH.as_posix().replace("'", r"\'")
        # Dynamic watermark sizing (15% of video width)
        wm_w = int(width * 0.15)
        wm_overlay = (
            f"movie='{wm_path}',scale={wm_w}:-1:flags=lanczos,format=rgba[wm];"
            f"[base][wm]overlay=main_w-overlay_w-40:main_h-overlay_h-40"
        )
        graph = f"{graph} [base]; {wm_overlay}, {ass_filter}"
    else:
        graph = f"{graph}, {ass_filter}"

    return graph


def run_ffmpeg_with_subs(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
    *,
    video_crf: int,
    video_preset: str,
    audio_bitrate: str,
    audio_copy: bool,
    use_hw_accel: bool = False,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
    output_width: int | None = None,
    output_height: int | None = None,
    watermark_enabled: bool = False,
    check_cancelled: Callable[[], None] | None = None,
) -> str:
    filtergraph = build_filtergraph(
        ass_path,
        target_width=output_width,
        target_height=output_height,
        watermark_enabled=watermark_enabled
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filtergraph,
    ]

    is_mac = platform.system() == "Darwin"
    if use_hw_accel and is_mac:
        q_val = int(100 - (video_crf * 2))
        q_val = max(40, min(90, q_val))  # Clamp to reasonable range
        cmd += [
            "-c:v",
            "h264_videotoolbox",
            "-q:v",
            str(q_val),
        ]
    else:
        # Optimization: Limit threads to physical cores to prevent Serverless thrashing
        # and use 'film' tuning for better live-action quality retention.
        threads = os.cpu_count() or 1
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            video_preset,
            "-crf",
            str(video_crf),
            "-threads",
            str(threads),
            "-tune",
            "film",
        ]

    if audio_copy:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", audio_bitrate]
    cmd += ["-movflags", "+faststart", str(output_path)]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,  # Line buffered
    )

    # Memory optimization: Use deque to keep only last 200 lines
    stderr_lines = deque(maxlen=200)

    try:
        if process.stderr:
            last_cancel_check = 0.0
            while True:
                # Periodic cancellation check
                # Optimization: Throttle check to ~2Hz to avoid excessive function call overhead
                if check_cancelled:
                    now = time.monotonic()
                    if now - last_cancel_check > 0.5:
                        try:
                            check_cancelled()
                            last_cancel_check = now
                        except Exception:
                            process.kill()
                            raise

                # Non-blocking read to ensure we can cancel even if ffmpeg hangs
                reads, _, _ = select.select([process.stderr], [], [], 0.1)
                if reads:
                    line = process.stderr.readline()
                    if not line:
                        break

                    stderr_lines.append(line)
                    if progress_callback and total_duration and total_duration > 0:
                        # Optimization: Fast string check before expensive regex
                        if "time=" in line:
                            match = TIME_PATTERN.search(line)
                            if match:
                                h, m, s = match.groups()
                                current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                                progress = min(100.0, (current_seconds / total_duration) * 100.0)
                                progress_callback(progress)
                elif process.poll() is not None:
                    break

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, "".join(stderr_lines))
        return "".join(stderr_lines)

    except Exception:
        # Ensure process is killed on any error (cancellation or otherwise)
        if process.poll() is None:
            process.kill()
        process.wait()
        raise
