"""Subtitle-file export helpers shared by API routes and tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Callable, Iterable

from backend.app.core.config import settings
from backend.app.services import settings_utils, subtitle_renderer, subtitles
from backend.app.services.subtitle_types import Cue, TimeRange, WordTiming

SUBTITLE_EXPORT_FORMATS = frozenset({"srt", "vtt", "txt"})

CONTENT_TYPE_BY_FORMAT = {
    "srt": "application/x-subrip",
    "vtt": "text/vtt",
    "txt": "text/plain",
}

_WRITER_BY_FORMAT: dict[str, Callable[[Iterable[TimeRange], Path], Path]] = {
    "srt": subtitles.write_srt_from_segments,
    "vtt": subtitles.write_vtt_from_segments,
    "txt": subtitles.write_txt_from_segments,
}


class MalformedTranscriptError(ValueError):
    """Raised when a persisted transcript cannot be exported safely."""


@dataclass(frozen=True)
class SubtitleExportResult:
    path: Path
    content_type: str
    cues: list[Cue]


def _coerce_float(value: Any, *, field: str, cue_index: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MalformedTranscriptError(f"Transcript cue {cue_index} has invalid {field}") from exc
    if not number >= 0:
        raise MalformedTranscriptError(f"Transcript cue {cue_index} has invalid {field}")
    return number


def _coerce_words(payload: Any, *, cue_index: int) -> list[WordTiming] | None:
    if payload is None:
        return None
    if not isinstance(payload, list):
        raise MalformedTranscriptError(f"Transcript cue {cue_index} has malformed words")

    words: list[WordTiming] = []
    for word_index, word_payload in enumerate(payload, start=1):
        if not isinstance(word_payload, dict):
            raise MalformedTranscriptError(f"Transcript cue {cue_index} word {word_index} is malformed")
        text = str(word_payload.get("text", "")).strip()
        if not text:
            continue
        start = _coerce_float(word_payload.get("start"), field="word start", cue_index=cue_index)
        end = _coerce_float(word_payload.get("end"), field="word end", cue_index=cue_index)
        if end <= start:
            raise MalformedTranscriptError(f"Transcript cue {cue_index} word {word_index} has invalid timing")
        words.append(WordTiming(start=start, end=end, text=text))

    return words or None


def cues_from_transcript_payload(payload: Any) -> list[Cue]:
    if not isinstance(payload, list):
        raise MalformedTranscriptError("Transcript JSON must be a list of cues")

    cues: list[Cue] = []
    for cue_index, cue_payload in enumerate(payload, start=1):
        if not isinstance(cue_payload, dict):
            raise MalformedTranscriptError(f"Transcript cue {cue_index} is malformed")

        text = str(cue_payload.get("text", "")).strip()
        if not text:
            continue

        start = _coerce_float(cue_payload.get("start"), field="start", cue_index=cue_index)
        end = _coerce_float(cue_payload.get("end"), field="end", cue_index=cue_index)
        if end <= start:
            raise MalformedTranscriptError(f"Transcript cue {cue_index} has invalid timing")

        cues.append(
            Cue(
                start=start,
                end=end,
                text=text,
                words=_coerce_words(cue_payload.get("words"), cue_index=cue_index),
            )
        )

    return cues


def read_transcript_cues(transcription_json: Path) -> list[Cue]:
    try:
        payload = json.loads(transcription_json.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise MalformedTranscriptError("Transcript JSON is malformed") from exc
    return cues_from_transcript_payload(payload)


def prepare_delivery_cues(
    cues: list[Cue],
    *,
    max_subtitle_lines: int,
    subtitle_size: int,
) -> list[Cue]:
    normalized = subtitle_renderer.normalize_cues_for_ass(cues)
    if max_subtitle_lines <= 0:
        return normalized

    font_size = settings_utils.font_size_from_subtitle_size(subtitle_size)
    effective_chars = subtitle_renderer.effective_max_chars(
        max_chars=settings.max_sub_line_chars,
        font_size=font_size,
        play_res_x=settings.default_width,
    )
    return subtitle_renderer.normalize_cues_for_ass(
        subtitle_renderer.split_long_cues(
            normalized,
            max_chars=effective_chars,
            max_lines=max_subtitle_lines,
        )
    )


def export_subtitle_file(
    *,
    transcription_json: Path,
    export_path: Path,
    export_format: str,
    max_subtitle_lines: int,
    subtitle_size: int,
) -> SubtitleExportResult:
    normalized_format = export_format.strip().lower()
    writer = _WRITER_BY_FORMAT.get(normalized_format)
    if writer is None:
        raise ValueError(f"Unsupported subtitle export format: {export_format}")

    cues = prepare_delivery_cues(
        read_transcript_cues(transcription_json),
        max_subtitle_lines=max_subtitle_lines,
        subtitle_size=subtitle_size,
    )
    segments = [(cue.start, cue.end, cue.text) for cue in cues]
    writer(segments, export_path)
    return SubtitleExportResult(
        path=export_path,
        content_type=CONTENT_TYPE_BY_FORMAT[normalized_format],
        cues=cues,
    )
