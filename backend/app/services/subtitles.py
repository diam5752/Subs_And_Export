"""Subtitle generation and styling helpers."""

from __future__ import annotations

import logging
import math
import re
import select
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

from backend.app.core.config import settings
from backend.app.core.media_capacity import lock_media_cpu
from backend.app.services.ffmpeg_utils import terminate_process_tree
from backend.app.services.subtitle_types import Cue, TimeRange

logger = logging.getLogger(__name__)

TIME_PATTERN = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")


def resolve_audio_extraction_timeout_seconds(
    *,
    total_duration: float | None,
    timeout_seconds: float | None = None,
) -> float:
    """Return a strict extraction deadline with a slow-host safety margin."""
    if timeout_seconds is not None:
        resolved = float(timeout_seconds)
        if not math.isfinite(resolved) or resolved <= 0:
            raise ValueError("Audio extraction timeout must be a positive finite number")
        return resolved
    if total_duration is not None:
        duration = float(total_duration)
        if math.isfinite(duration) and duration > 0:
            return max(300.0, duration * 2.0)
    return 600.0


def _wait_after_termination(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        process.wait()
        return
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def extract_audio(
    input_video: Path,
    output_dir: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
    timeout_seconds: float | None = None,
) -> Path:
    """Extract one mono WAV under the shared-host FFmpeg capacity guard."""
    output_dir = output_dir or Path(tempfile.mkdtemp())
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{input_video.stem}.wav"
    resolved_timeout = resolve_audio_extraction_timeout_seconds(
        total_duration=total_duration,
        timeout_seconds=timeout_seconds,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_video),
        "-vn",
        "-acodec",
        settings.audio_codec,
        "-ar",
        str(settings.audio_sample_rate),
        "-ac",
        str(settings.audio_channels),
        str(audio_path),
    ]

    with lock_media_cpu():
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1,
            start_new_session=True,
        )
        deadline = time.monotonic() + resolved_timeout

        try:
            last_cancel_check = 0.0

            while True:
                now = time.monotonic()
                if now >= deadline:
                    raise TimeoutError(
                        "Audio extraction exceeded timeout of "
                        f"{resolved_timeout:.1f}s",
                    )

                # Periodic cancellation check
                if check_cancelled and now - last_cancel_check > 0.5:
                    check_cancelled()
                    last_cancel_check = now

                # Non-blocking read keeps cancellation and timeout responsive.
                if process.stderr:
                    reads, _, _ = select.select(
                        [process.stderr],
                        [],
                        [],
                        min(0.1, max(0.0, deadline - now)),
                    )
                    if reads:
                        line = process.stderr.readline()
                        if line and progress_callback and total_duration and total_duration > 0:
                            if "time=" in line:
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
                    "Audio extraction exceeded timeout of "
                    f"{resolved_timeout:.1f}s",
                )
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode,
                    cmd,
                    output=None,
                )

        except Exception:
            terminate_process_tree(process)
            _wait_after_termination(process)
            raise

    return audio_path


def write_srt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines: list[str] = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        lines.append(str(idx))
        start_time = _format_subtitle_timestamp(start, separator=',')
        end_time = _format_subtitle_timestamp(end, separator=',')
        lines.append(f"{start_time} --> {end_time}")
        # Security: Sanitize text to prevent SRT injection via double newlines
        # Replace 2+ newlines with a single newline to maintain multiline but prevent cue splitting
        clean_text = re.sub(r'(\r?\n){2,}', '\n', text.strip())
        lines.append(clean_text)
        lines.append("")  # blank line separator
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def _format_subtitle_timestamp(seconds: float, *, separator: str) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def write_vtt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines: list[str] = ["WEBVTT", ""]
    for idx, (start, end, text) in enumerate(segments, start=1):
        lines.append(str(idx))
        start_time = _format_subtitle_timestamp(start, separator='.')
        end_time = _format_subtitle_timestamp(end, separator='.')
        lines.append(f"{start_time} --> {end_time}")
        clean_text = re.sub(r"(\r?\n){2,}", "\n", text.strip())
        lines.append(clean_text)
        lines.append("")
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def write_txt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines = []
    for _, _, text in segments:
        clean_text = re.sub(r"(\r?\n){2,}", "\n", text.strip())
        if clean_text:
            lines.append(clean_text)
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def get_video_duration(path: Path) -> float:
    """Get the duration of a video/audio file in seconds using ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    # Security: Timeout enforced to prevent hangs
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30.0)
    return float(result.stdout.strip())


def cues_to_text(cues: Sequence[Cue]) -> str:
    """Collapse cue text into a single transcript string."""
    return " ".join(cue.text.strip() for cue in cues if cue.text).strip()
