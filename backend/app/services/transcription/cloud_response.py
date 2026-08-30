"""Shared conversion helpers for OpenAI-compatible transcription responses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.app.services.subtitle_types import Cue, TimeRange, WordTiming
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments


def call_callback(callback: object, *args: object) -> None:
    """Invoke an optional provider callback without duplicating branches."""
    if callable(callback):
        callback(*args)


def _segment_words(
    all_words: list[Any],
    *,
    start: float,
    end: float,
) -> list[WordTiming]:
    return [
        WordTiming(start=word.start, end=word.end, text=normalize_text(word.word))
        for word in all_words
        if word.start >= start and word.start < end
    ]


def convert_verbose_transcript(
    transcript: Any,
) -> tuple[list[Cue], list[TimeRange]]:
    """Convert one OpenAI-compatible verbose transcript to local cue data."""
    cues: list[Cue] = []
    timed_text: list[TimeRange] = []
    segments = getattr(transcript, "segments", None)
    if segments is None:
        return cues, timed_text

    all_words = list(getattr(transcript, "words", []) or [])
    for segment in segments:
        segment_text = segment.text or ""
        segment_words = _segment_words(
            all_words,
            start=segment.start,
            end=segment.end,
        )
        cues.append(
            Cue(
                start=segment.start,
                end=segment.end,
                text=normalize_text(segment_text),
                words=segment_words,
            )
        )
        timed_text.append((segment.start, segment.end, segment_text))
    return cues, timed_text


def write_cloud_transcript(
    *,
    audio_path: Path,
    output_dir: Path,
    transcript: Any,
) -> tuple[Path, list[Cue]]:
    """Persist SRT output and return the corresponding local cues."""
    cues, timed_text = convert_verbose_transcript(transcript)
    srt_path = output_dir / f"{audio_path.stem}.srt"
    write_srt_from_segments(timed_text, srt_path)
    return srt_path, cues
