"""Subtitle generation and styling helpers."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, Sequence

from backend.app.core.config import settings
from backend.app.services.subtitle_types import Cue, TimeRange

logger = logging.getLogger(__name__)

TIME_PATTERN = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")


def extract_audio(
    input_video: Path,
    output_dir: Path | None = None,
    check_cancelled: Callable[[], None] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
) -> Path:
    """
    Extract the audio track from a video file into a mono WAV for transcription.
    """
    output_dir = output_dir or Path(tempfile.mkdtemp())
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{input_video.stem}.wav"

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

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
    )

    try:
        import select

        last_cancel_check = 0.0

        while True:
            # 1. Periodic cancellation check
            if check_cancelled:
                now = time.monotonic()
                # Throttle check to avoid excessive DB overhead (every 0.5s)
                if now - last_cancel_check > 0.5:
                    check_cancelled()
                    last_cancel_check = now

            # 2. Non-blocking read of ffmpeg stderr
            if process.stderr:
                reads, _, _ = select.select([process.stderr], [], [], 0.1)
                if reads:
                    line = process.stderr.readline()
                    if not line:
                        break  # EOF

                    if progress_callback and total_duration and total_duration > 0:
                        if "time=" in line:
                            match = TIME_PATTERN.search(line)
                            if match:
                                h, m, s = match.groups()
                                current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                                progress = min(100.0, (current_seconds / total_duration) * 100.0)
                                progress_callback(progress)

            if process.poll() is not None:
                break

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, output=None)

    except Exception:
        if process.poll() is None:
            process.kill()
        process.wait()
        raise

    return audio_path


def write_srt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines: list[str] = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        lines.append(str(idx))
        lines.append(f"{_format_subtitle_timestamp(start, separator=',')} --> {_format_subtitle_timestamp(end, separator=',')}")
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
        lines.append(f"{_format_subtitle_timestamp(start, separator='.')} --> {_format_subtitle_timestamp(end, separator='.')}")
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
