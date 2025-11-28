"""Subtitle generation and styling helpers."""

from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple
import unicodedata
import textwrap

from faster_whisper import WhisperModel

from . import config

TimeRange = Tuple[float, float, str]


@dataclass
class WordTiming:
    start: float
    end: float
    text: str


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: Optional[List[WordTiming]] = None


def _normalize_text(text: str) -> str:
    """
    Uppercase + strip accents for consistent, bold subtitle styling.
    """
    # Remove diacritics
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.upper()


def extract_audio(input_video: Path, output_dir: Path | None = None) -> Path:
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
        config.AUDIO_CODEC,
        "-ar",
        str(config.AUDIO_SAMPLE_RATE),
        "-ac",
        str(config.AUDIO_CHANNELS),
        str(audio_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return audio_path


def _format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:01d}:{minutes:02d}:{secs:05.2f}"


def _write_srt_from_segments(segments: Iterable[TimeRange], dest: Path) -> Path:
    lines: List[str] = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        start_ts = _format_timestamp(start)
        end_ts = _format_timestamp(end)
        lines.append(str(idx))
        lines.append(f"{start_ts.replace('.', ',')} --> {end_ts.replace('.', ',')}")
        lines.append(text.strip())
        lines.append("")  # blank line separator
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def generate_subtitles_from_audio(
    audio_path: Path,
    model_size: str = config.WHISPER_MODEL_SIZE,
    language: str = config.WHISPER_LANGUAGE,
    device: str = config.WHISPER_DEVICE,
    compute_type: str = config.WHISPER_COMPUTE_TYPE,
    output_dir: Path | None = None,
) -> Tuple[Path, List[Cue]]:
    """
    Transcribe Greek speech to an SRT subtitle file using faster-whisper.

    Returns the path to the SRT file and the structured cues (with word timings
    when available) to support karaoke-style highlighting.
    """
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
    segments, _ = model.transcribe(str(audio_path), language=language, word_timestamps=True)

    cues: List[Cue] = []
    timed_text: List[TimeRange] = []
    for seg in segments:
        timed_text.append((seg.start, seg.end, seg.text))
        words: Optional[List[WordTiming]] = None
        if getattr(seg, "words", None):
            words = [
                WordTiming(start=w.start, end=w.end, text=_normalize_text(w.word))
                for w in seg.words
            ]
        cue_text = _normalize_text(seg.text)
        cues.append(Cue(start=seg.start, end=seg.end, text=cue_text, words=words))

    output_dir = output_dir or Path(tempfile.mkdtemp())
    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / f"{audio_path.stem}.srt"
    _write_srt_from_segments(timed_text, srt_path)
    return srt_path, cues


def _parse_srt(transcript_path: Path) -> List[TimeRange]:
    raw = transcript_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", raw.strip())
    parsed: List[TimeRange] = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        # second line expected to be timecode
        time_line = lines[1]
        match = re.match(
            r"(\d+:\d{2}:\d{2}[,.]\d+)\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d+)", time_line
        )
        if not match:
            continue
        start_raw, end_raw = match.groups()
        text = " ".join(lines[2:]).strip()
        parsed.append((_srt_time_to_seconds(start_raw), _srt_time_to_seconds(end_raw), text))
    return parsed


def _srt_time_to_seconds(ts: str) -> float:
    ts = ts.replace(",", ".")
    hours, minutes, seconds = ts.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _ass_header(
    font: str,
    font_size: int,
    primary_color: str,
    secondary_color: str,
    outline_color: str,
    back_color: str,
    outline: int,
    alignment: int,
    margin_v: int,
    margin_l: int,
    margin_r: int,
) -> str:
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {config.DEFAULT_WIDTH}\n"
        f"PlayResY: {config.DEFAULT_HEIGHT}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,"
        "Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{font_size},{primary_color},{secondary_color},"
        f"{outline_color},{back_color},1,0,0,0,100,100,0,0,1,{outline},2,{alignment},{margin_l},{margin_r},{margin_v},0\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _format_ass_dialogue(start: float, end: float, text: str) -> str:
    return f"Dialogue: 0,{_format_timestamp(start)},{_format_timestamp(end)},Default,,0,0,0,,{text}"


def create_styled_subtitle_file(
    transcript_path: Path,
    cues: Optional[Sequence[Cue]] = None,
    font: str = config.DEFAULT_SUB_FONT,
    font_size: int = config.DEFAULT_SUB_FONT_SIZE,
    primary_color: str = config.DEFAULT_SUB_COLOR,
    secondary_color: str = config.DEFAULT_SUB_SECONDARY_COLOR,
    outline_color: str = config.DEFAULT_SUB_OUTLINE_COLOR,
    back_color: str = config.DEFAULT_SUB_BACK_COLOR,
    outline: int = config.DEFAULT_SUB_STROKE_WIDTH,
    alignment: int = config.DEFAULT_SUB_ALIGNMENT,
    margin_v: int = config.DEFAULT_SUB_MARGIN_V,
    margin_l: int = config.DEFAULT_SUB_MARGIN_L,
    margin_r: int = config.DEFAULT_SUB_MARGIN_R,
    output_dir: Path | None = None,
) -> Path:
    """
    Convert an SRT transcript to an ASS file with styling for vertical video,
    applying per-word karaoke highlighting when word timings are available.
    """
    parsed_cues: List[Cue]
    if cues:
        parsed_cues = list(cues)
    else:
        parsed_cues = [
            Cue(start=s, end=e, text=_normalize_text(t))
            for s, e, t in _parse_srt(transcript_path)
        ]

    output_dir = output_dir or transcript_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    ass_path = output_dir / f"{transcript_path.stem}.ass"

    header = _ass_header(
        font=font,
        font_size=font_size,
        primary_color=primary_color,
        secondary_color=secondary_color,
        outline_color=outline_color,
        back_color=back_color,
        outline=outline,
        alignment=alignment,
        margin_v=margin_v,
        margin_l=margin_l,
        margin_r=margin_r,
    )
    lines = [header]
    for cue in parsed_cues:
        text = _format_karaoke_text(cue)
        lines.append(_format_ass_dialogue(cue.start, cue.end, text))
    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


def _wrap_two_lines(words: List[str], max_chars: int = config.MAX_SUB_LINE_CHARS) -> Tuple[List[str], List[str]]:
    """
    Wrap into up to two lines, trying to balance lengths and avoid overflow.
    """
    def line_len(ws: List[str]) -> int:
        if not ws:
            return 0
        return sum(len(w) for w in ws) + (len(ws) - 1)

    # Try all splits; choose minimal overflow, then best balance.
    best_split = None
    best_score = None  # (overflow, balance)
    for i in range(1, len(words)):
        left = words[:i]
        right = words[i:]
        len_left = line_len(left)
        len_right = line_len(right)
        overflow = max(0, len_left - max_chars) + max(0, len_right - max_chars)
        balance = abs(len_left - len_right)
        score = (overflow, balance)
        if best_score is None or score < best_score:
            best_score = score
            best_split = (left, right)
    if best_split:
        return best_split

    # Fallback: textwrap with word breaking for long words
    text = " ".join(words)
    wrapped = textwrap.wrap(
        text,
        width=max_chars,
        break_long_words=True,
        break_on_hyphens=False,
        drop_whitespace=True,
    )
    if not wrapped:
        return [], []
    if len(wrapped) == 1:
        return wrapped[0].split(), []
    if len(wrapped) > 2:
        wrapped = [wrapped[0], " ".join(wrapped[1:])]
    return wrapped[0].split(), wrapped[1].split()


def _format_karaoke_text(
    cue: Cue,
    highlight_color: str = config.DEFAULT_HIGHLIGHT_COLOR,
    secondary_color: str = config.DEFAULT_SUB_SECONDARY_COLOR,
) -> str:
    """
    Build ASS karaoke text with per-word highlighting. If word timings are not
    available, falls back to plain text with simple 2-line wrapping.
    """
    if cue.words:
        first_line_words, second_line_words = _wrap_two_lines(
            [w.text for w in cue.words], max_chars=config.MAX_SUB_LINE_CHARS
        )
        words = cue.words
        segments = []
        for idx, word in enumerate(words):
            duration_cs = max(1, round((word.end - word.start) * 100))
            token = f"{{\\k{duration_cs}}}{{\\c{highlight_color}}}{word.text}{{\\c{secondary_color}}}"
            # insert line break before the first word of the second line
            if idx == len(first_line_words):
                segments.append("\\N")
            segments.append(token)
            if idx != len(words) - 1:
                segments.append(" ")
        return "".join(segments)

    # Fallback: no word timings, static text wrapped to two lines
    raw_words = cue.text.split()
    first, second = _wrap_two_lines(raw_words, max_chars=config.MAX_SUB_LINE_CHARS)
    if second:
        return " ".join(first) + "\\N" + " ".join(second)
    return " ".join(first)
