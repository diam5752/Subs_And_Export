"""FFMPEG wrappers and media probing utilities."""

from __future__ import annotations

import json
import logging
import math
import os
import platform
import re
import select
import signal
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.app.core.config import settings
from backend.app.core.media_capacity import lock_media_cpu

logger = logging.getLogger(__name__)

# Support both legacy human-readable stats and FFmpeg's newline-delimited
# programmatic progress output. The latter uses microsecond precision.
TIME_PATTERN = re.compile(
    r"(?:time|out_time)=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)",
)
_FFMPEG_MAX_THREADS = 2


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
        timeout=30.0,  # Security: Prevent infinite hang if ffprobe stalls
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
    except Exception as exc:
        logger.warning("Failed to probe audio codec: %s", exc)
        return False


def build_filtergraph(
    ass_path: Path,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
    watermark_enabled: bool = False,
) -> str:
    ass_file = ass_path.as_posix().replace("'", r"\'")
    ass_filter = f"ass='{ass_file}'"

    logger.debug(
        "FFmpeg filtergraph target dimensions: width=%s height=%s",
        target_width,
        target_height,
    )

    # If no target dimensions, skip scaling - keep original resolution
    if target_width is None and target_height is None:
        return f"format=yuv420p,{ass_filter}"

    width = target_width or settings.default_width
    height = target_height or settings.default_height
    scale = f"scale={width}:-2:force_original_aspect_ratio=decrease"
    pad = f"pad={width}:{height}:({width}-iw)/2:({height}-ih)/2"
    graph = ",".join([scale, pad, "format=yuv420p"])

    if watermark_enabled and settings.watermark_path.exists():
        # Clean path for FFmpeg
        wm_path = settings.watermark_path.as_posix().replace("'", r"\'")
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


def resolve_ffmpeg_thread_count(requested_threads: int | None = None) -> int:
    """Bound one encoder to at most two host CPUs on the shared VM."""
    available_threads = max(1, os.cpu_count() or 1)
    if requested_threads is None:
        return min(available_threads, _FFMPEG_MAX_THREADS)
    if (
        isinstance(requested_threads, bool)
        or not isinstance(requested_threads, int)
        or requested_threads <= 0
    ):
        raise ValueError("FFmpeg thread count must be a positive integer")
    return min(
        requested_threads,
        available_threads,
        _FFMPEG_MAX_THREADS,
    )


def resolve_ffmpeg_timeout_seconds(
    *,
    total_duration: float | None,
    timeout_seconds: float | None = None,
) -> float:
    """Return a strict render deadline with a generous slow-host allowance."""
    if timeout_seconds is not None:
        resolved = float(timeout_seconds)
        if not math.isfinite(resolved) or resolved <= 0:
            raise ValueError("FFmpeg timeout must be a positive finite number")
        return resolved
    if total_duration is not None:
        duration = float(total_duration)
        if math.isfinite(duration) and duration > 0:
            return max(1800.0, duration * 20.0)
    return 3600.0


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Kill the isolated FFmpeg process group without touching unrelated work."""
    if process.poll() is not None:
        return
    pid = getattr(process, "pid", None)
    if isinstance(pid, int) and pid > 0 and platform.system() != "Windows":
        try:
            os.killpg(pid, signal.SIGKILL)
            return
        except OSError:
            pass
    process.kill()


def _wait_after_termination(process: subprocess.Popen[str]) -> None:
    # A completed process has already crossed the monitored poll boundary, so
    # a plain wait is immediate and also keeps lightweight test doubles valid.
    if process.poll() is not None:
        process.wait()
        return
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


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
    timeout_seconds: float | None = None,
    thread_count: int | None = None,
) -> str:
    resolved_timeout = resolve_ffmpeg_timeout_seconds(
        total_duration=total_duration,
        timeout_seconds=timeout_seconds,
    )
    filtergraph = build_filtergraph(
        ass_path,
        target_width=output_width,
        target_height=output_height,
        watermark_enabled=watermark_enabled,
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-nostats",
        "-progress",
        "pipe:2",
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
        # Keep one render from consuming the complete shared MizAI VM.
        threads = resolve_ffmpeg_thread_count(thread_count)
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

    # The single-host launch lane intentionally serializes every local encoder,
    # including user-requested exports, so gsubs cannot starve MizAI.
    with lock_media_cpu():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,  # Line buffered
            start_new_session=True,
        )

        # Memory optimization: Use deque to keep only last 200 lines
        stderr_lines: deque[str] = deque(maxlen=200)
        deadline = time.monotonic() + resolved_timeout

        try:
            last_cancel_check = 0.0
            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise TimeoutError(
                        f"FFmpeg process exceeded timeout of {resolved_timeout:.1f}s",
                    )

                # Periodic cancellation check
                if check_cancelled and now - last_cancel_check > 0.5:
                    check_cancelled()
                    last_cancel_check = now

                if process.stderr:
                    reads, _, _ = select.select(
                        [process.stderr],
                        [],
                        [],
                        min(0.1, max(0.0, deadline - now)),
                    )
                    if reads:
                        line = process.stderr.readline()
                        if line:
                            stderr_lines.append(line)
                            if progress_callback and total_duration and total_duration > 0:
                                match = TIME_PATTERN.search(line)
                                if match:
                                    h, m, s = match.groups()
                                    current_seconds = (
                                        int(h) * 3600
                                        + int(m) * 60
                                        + float(s)
                                    )
                                    progress = min(
                                        100.0,
                                        (current_seconds / total_duration) * 100.0,
                                    )
                                    progress_callback(progress)
                else:
                    time.sleep(min(0.1, max(0.0, deadline - now)))

                if process.poll() is not None:
                    break

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"FFmpeg process exceeded timeout of {resolved_timeout:.1f}s",
                )
            # poll() above already proved termination; this is immediate and
            # simply finalizes the subprocess object / return code.
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode,
                    cmd,
                    "".join(stderr_lines),
                )
            return "".join(stderr_lines)

        except Exception:
            # Ensure the complete isolated process group is killed on timeout,
            # cancellation, malformed input or any other failure.
            terminate_process_tree(process)
            _wait_after_termination(process)
            raise
