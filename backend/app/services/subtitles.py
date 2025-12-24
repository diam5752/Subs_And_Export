"""Subtitle generation and styling helpers."""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, Iterable, List, Tuple

import stable_whisper

from backend.app.core.config import settings
from backend.app.services import (
    fact_checking,
    llm_utils,
    social_intelligence,
    subtitle_renderer,
)
from backend.app.services.subtitle_types import Cue, TimeRange

logger = logging.getLogger(__name__)

# Re-export key types and classes for backward compatibility
SocialContent = social_intelligence.SocialContent
SocialCopy = social_intelligence.SocialCopy
ViralMetadata = social_intelligence.ViralMetadata
FactCheckResult = fact_checking.FactCheckResult
FactCheckItem = fact_checking.FactCheckItem

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


def _write_srt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines: List[str] = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        start_ts = subtitle_renderer.format_timestamp(start)
        end_ts = subtitle_renderer.format_timestamp(end)
        lines.append(str(idx))
        lines.append(f"{start_ts.replace('.', ',')} --> {end_ts.replace('.', ',')}")
        # Security: Sanitize text to prevent SRT injection via double newlines
        # Replace 2+ newlines with a single newline to maintain multiline but prevent cue splitting
        clean_text = re.sub(r'(\r?\n){2,}', '\n', text.strip())
        lines.append(clean_text)
        lines.append("")  # blank line separator
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
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30.0)
    return float(result.stdout.strip())


# Define type alias for the wrapped model
StableWhisperModel = stable_whisper.WhisperResult

def _get_whisper_model(
    model_size: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
) -> stable_whisper.WhisperResult:  # pragma: no cover
    """
    Load a Stable-Whisper wrapped Faster-Whisper model.
    """
    # Map "turbo" alias to the config constant (which might be large-v3 now)
    logger.debug("Runtime whisper model config: WHISPER_MODEL=%s", settings.whisper_model)
    if model_size == "turbo":
        model_size = settings.whisper_model

    logger.debug("Loading Whisper model: model=%s device=%s", model_size, device)

    # stable-ts wrapper for faster-whisper
    # It internally loads FasterWhisperModel and wraps it.
    model = stable_whisper.load_faster_whisper(
        model_size_or_path=model_size,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )
    return model


def generate_subtitles_from_audio(
    audio_path: Path,
    model_size: str = settings.whisper_model,
    language: str | None = settings.whisper_language,
    device: str = settings.whisper_device,
    compute_type: str = settings.whisper_compute_type,
    beam_size: int | None = None,
    best_of: int | None = 1,
    output_dir: Path | None = None,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
    temperature: float | None = None,
    chunk_length: int | None = settings.whisper_chunk_length,
    condition_on_previous_text: bool = False,
    initial_prompt: str | None = None,
    vad_filter: bool = True,
    vad_parameters: dict | None = None,
    provider: str = "local",
    openai_api_key: str | None = None,
) -> Tuple[Path, List[Cue]]:  # pragma: no cover
    """
    DEPRECATED: Use the Transcriber classes directly.
    Legacy wrapper to maintain backward compatibility during refactoring.
    """
    from backend.app.services.transcription.groq_cloud import GroqTranscriber
    from backend.app.services.transcription.local_whisper import LocalWhisperTranscriber
    from backend.app.services.transcription.openai_cloud import OpenAITranscriber
    from backend.app.services.transcription.standard_whisper import StandardTranscriber

    if not language or language.lower() == "auto":
        language = settings.whisper_language

    wants_openai = provider == "openai" or llm_utils.model_uses_openai(model_size)
    output_dir = output_dir or Path(tempfile.mkdtemp())
    output_dir.mkdir(parents=True, exist_ok=True)

    if wants_openai:
        transcriber = OpenAITranscriber(api_key=openai_api_key)
        return transcriber.transcribe(
            audio_path,
            output_dir,
            language=language,
            model=model_size or settings.openai_transcribe_model,
            initial_prompt=initial_prompt,
            progress_callback=progress_callback,
        )

    if provider == "groq":
        transcriber = GroqTranscriber(api_key=openai_api_key)
        return transcriber.transcribe(
            audio_path, output_dir, language=language, model=settings.groq_transcribe_model,
            initial_prompt=initial_prompt, progress_callback=progress_callback
        )

    if provider == "local":
        resolved_model = model_size
        if resolved_model == "turbo":
            resolved_model = settings.whisper_model

        transcriber = LocalWhisperTranscriber(
            device=device,
            compute_type=compute_type,
            beam_size=beam_size or 5,
        )
        return transcriber.transcribe(
            audio_path,
            output_dir,
            language=language,
            model=resolved_model,
            progress_callback=progress_callback,
            best_of=best_of,
            temperature=temperature,
            initial_prompt=initial_prompt,
            vad_filter=vad_filter,
            condition_on_previous_text=condition_on_previous_text,
        )

    if provider == "whispercpp":
        transcriber = StandardTranscriber()
        return transcriber.transcribe(
            audio_path,
            output_dir,
            language=language,
            model=settings.whispercpp_model,
            progress_callback=progress_callback,
        )

    raise ValueError(f"Unknown or removed provider: {provider}")


def cues_to_text(cues: Sequence[Cue]) -> str:
    """Collapse cue text into a single transcript string."""
    return " ".join(cue.text.strip() for cue in cues if cue.text).strip()


# =============================================================================
# FACADES / ALIASES
# Use these definitions to maintain backward compatibility while delegating
# to the new service modules.
# =============================================================================

should_use_openai = llm_utils.should_use_openai
create_styled_subtitle_file = subtitle_renderer.create_styled_subtitle_file
build_social_copy = social_intelligence.build_social_copy
build_social_copy_llm = social_intelligence.build_social_copy_llm
generate_fact_check = fact_checking.generate_fact_check
