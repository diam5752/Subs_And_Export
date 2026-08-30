"""Subtitle generation and styling helpers."""

from __future__ import annotations

import logging
import math
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

from backend.app.core.config import settings
from backend.app.core.media_capacity import lock_audio_extraction
from backend.app.services.ffmpeg_utils import (
    lower_media_process_priority,
    resolve_ffmpeg_thread_count,
    terminate_process_tree,
)
from backend.app.services.media_process_monitor import monitor_media_process
from backend.app.services.media_process_monitor import select as select
from backend.app.services.subtitle_types import Cue, TimeRange

logger = logging.getLogger(__name__)

TIME_PATTERN = re.compile(
    r"(?:time|out_time)=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)",
)


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


def _audio_extraction_command(
    *,
    input_video: Path,
    audio_path: Path,
    threads: int,
) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-nostats",
        "-progress",
        "pipe:2",
        "-threads",
        str(threads),
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


def _run_audio_extraction_process(
    *,
    command: list[str],
    resolved_timeout: float,
    check_cancelled: Callable[[], None] | None,
    progress_callback: Callable[[float], None] | None,
    total_duration: float | None,
) -> None:
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
        start_new_session=True,
    )
    lower_media_process_priority(process)
    try:
        monitor_media_process(
            process,
            deadline=time.monotonic() + resolved_timeout,
            timeout_message=(f"Audio extraction exceeded timeout of {resolved_timeout:.1f}s"),
            progress_pattern=TIME_PATTERN,
            check_cancelled=check_cancelled,
            progress_callback=progress_callback,
            total_duration=total_duration,
        )
        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode,
                command,
                output=None,
            )
    except Exception:
        terminate_process_tree(process)
        _wait_after_termination(process)
        raise


def extract_audio(
    input_video: Path,
    output_dir: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
    timeout_seconds: float | None = None,
    thread_count: int | None = None,
) -> Path:
    """Extract one mono WAV under the shared-host FFmpeg capacity guard."""
    output_dir = output_dir or Path(tempfile.mkdtemp())
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{input_video.stem}.wav"
    resolved_timeout = resolve_audio_extraction_timeout_seconds(
        total_duration=total_duration,
        timeout_seconds=timeout_seconds,
    )
    requested_threads = thread_count if thread_count is not None else settings.media_extraction_threads_per_slot
    threads = resolve_ffmpeg_thread_count(requested_threads)

    command = _audio_extraction_command(
        input_video=input_video,
        audio_path=audio_path,
        threads=threads,
    )

    with lock_audio_extraction():
        _run_audio_extraction_process(
            command=command,
            resolved_timeout=resolved_timeout,
            check_cancelled=check_cancelled,
            progress_callback=progress_callback,
            total_duration=total_duration,
        )

    return audio_path


def write_srt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines: list[str] = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        lines.append(str(idx))
        start_time = _format_subtitle_timestamp(start, separator=",")
        end_time = _format_subtitle_timestamp(end, separator=",")
        lines.append(f"{start_time} --> {end_time}")
        # Security: Sanitize text to prevent SRT injection via double newlines
        # Replace 2+ newlines with a single newline to maintain multiline but prevent cue splitting
        clean_text = re.sub(r"(\r?\n){2,}", "\n", text.strip())
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
        start_time = _format_subtitle_timestamp(start, separator=".")
        end_time = _format_subtitle_timestamp(end, separator=".")
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
