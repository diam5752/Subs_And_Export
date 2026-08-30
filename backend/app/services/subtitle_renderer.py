"""Subtitle rendering and styling service."""

from __future__ import annotations

import functools
import logging
import re
import unicodedata
from pathlib import Path
from typing import List, Sequence

from backend.app.core.config import settings
from backend.app.services import settings_utils
from backend.app.services.subtitle_layout import SOFT_BREAK_PUNCTUATION as SOFT_BREAK_PUNCTUATION
from backend.app.services.subtitle_layout import STRONG_BREAK_PUNCTUATION as STRONG_BREAK_PUNCTUATION
from backend.app.services.subtitle_layout import chunk_items as chunk_items
from backend.app.services.subtitle_layout import effective_max_chars as effective_max_chars
from backend.app.services.subtitle_layout import format_active_word_text as format_active_word_text
from backend.app.services.subtitle_layout import format_karaoke_text as format_karaoke_text
from backend.app.services.subtitle_layout import split_long_cues as split_long_cues
from backend.app.services.subtitle_layout import wrap_lines as wrap_lines
from backend.app.services.subtitle_layout import wrap_word_timings as wrap_word_timings
from backend.app.services.subtitle_types import Cue, TimeRange, WordTiming

logger = logging.getLogger(__name__)

TIME_PATTERN = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")


@functools.lru_cache(maxsize=4096)
def normalize_text(text: str) -> str:
    """
    Uppercase + strip accents for consistent, bold subtitle styling.
    """
    # Remove diacritics
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.upper()


def get_text_width(text: str, font_size: int) -> int:
    """
    Estimate text width in pixels.
    Used primarily for testing text wrapping logic.
    Assumes average character aspect ratio of 0.5 (typical for sans-serif fonts).
    """
    return int(len(text) * font_size * 0.5)


@functools.lru_cache(maxsize=8192)
def sanitize_ass_text(text: str) -> str:
    """
    Sanitize text to prevent ASS injection.
    Replaces special characters '{', '}' and '\\' to prevent tag injection.

    Cached to optimize performance for repetitive words in subtitles.
    """
    if not text:
        return text
    # Replace curlies with parenthesis to prevent tag injection
    text = text.replace("{", "(").replace("}", ")")
    # Replace backslashes with forward slashes to prevent escape sequences (like \N)
    # or tag starts.
    text = text.replace("\\", "/")
    # Replace newlines (which are event delimiters in ASS) with spaces
    text = text.replace("\n", " ").replace("\r", " ")
    return text


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:01d}:{minutes:02d}:{secs:05.2f}"


def srt_time_to_seconds(ts: str) -> float:
    ts = ts.replace(",", ".")
    hours, minutes, seconds = ts.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def parse_srt(transcript_path: Path) -> List[TimeRange]:
    raw = transcript_path.read_text(encoding="utf-8")
    blocks = re.split(r"\n\s*\n", raw.strip())
    parsed: List[TimeRange] = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        # second line expected to be timecode
        time_line = lines[1]
        match = re.match(r"(\d+:\d{2}:\d{2}[,.]\d+)\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d+)", time_line)
        if not match:
            continue
        start_raw, end_raw = match.groups()
        text = " ".join(lines[2:]).strip()
        parsed.append((srt_time_to_seconds(start_raw), srt_time_to_seconds(end_raw), text))
    return parsed


def ass_header(
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
    shadow_strength: int = 4,
    play_res_x: int = settings.default_width,
    play_res_y: int = settings.default_height,
) -> str:
    # Security: Validate inputs to prevent ASS format injection
    # Colors and font names must not contain commas or newlines which are delimiters in ASS
    for name, val in [
        ("primary_color", primary_color),
        ("secondary_color", secondary_color),
        ("outline_color", outline_color),
        ("back_color", back_color),
        ("font", font),
    ]:
        if any(c in val for c in ",\n\r"):
            raise ValueError(f"Invalid character in ASS field {name}: {val!r}")

    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
        "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,"
        "Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{font_size},{primary_color},{secondary_color},"
        f"{outline_color},{back_color},1,0,0,0,100,100,0,0,1,{outline},{shadow_strength},{alignment},{margin_l},{margin_r},{margin_v},0\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def format_ass_dialogue(start: float, end: float, text: str, layer: int = 0) -> str:
    return f"Dialogue: {layer},{format_timestamp(start)},{format_timestamp(end)},Default,,0,0,0,,{text}"


def position_ass_dialogue_events(
    events: Sequence[str],
    *,
    subtitle_position: int,
    font_size: int,
    play_res_x: int,
    play_res_y: int,
) -> List[str]:
    r"""Position each ASS text block continuously inside the 5% vertical safe area.

    ``\an8`` anchors the event at its top-center. The computed y coordinate
    mirrors the browser preview: low positions anchor the block's bottom, the
    midpoint centers it, and the maximum anchors its top at the safe edge.
    """
    position = settings_utils.normalize_subtitle_position(subtitle_position)
    progress = (position - settings_utils.SUBTITLE_POSITION_MIN) / (
        settings_utils.SUBTITLE_POSITION_MAX - settings_utils.SUBTITLE_POSITION_MIN
    )
    safe_margin = play_res_y * (settings_utils.SUBTITLE_POSITION_MIN / 100)
    usable_height = play_res_y - (2 * safe_margin)
    positioned: List[str] = []

    for event in events:
        if not event.startswith("Dialogue:"):
            positioned.append(event)
            continue

        fields = event.split(",", 9)
        if len(fields) != 10:
            positioned.append(event)
            continue

        text = fields[9]
        line_count = max(1, text.count(r"\N") + 1)
        block_height = min(usable_height, font_size * 1.2 * line_count)
        top_y = safe_margin + ((1 - progress) * (usable_height - block_height))
        fields[9] = f"{{\\an8\\pos({play_res_x // 2},{int(round(top_y))})}}{text}"
        positioned.append(",".join(fields))

    return positioned


def _active_events_without_word_timings(
    cue: Cue,
    *,
    max_lines: int,
    primary_color: str,
) -> List[str]:
    if max_lines != 0:
        return [format_ass_dialogue(cue.start, cue.end, cue.text)]
    tokens = [token for token in cue.text.split() if token]
    if not tokens:
        return []
    step = max(0.01, cue.end - cue.start) / len(tokens)
    return [
        format_ass_dialogue(
            cue.start + (index * step),
            cue.end if index == len(tokens) - 1 else cue.start + ((index + 1) * step),
            f"{{\\c{primary_color}&}}{token}",
        )
        for index, token in enumerate(tokens)
    ]


def _active_word_line_structure(cue: Cue) -> List[List[WordTiming]]:
    if cue.words is None:
        return []
    line_structure: List[List[WordTiming]] = []
    word_iter = iter(cue.words)
    try:
        for raw_line in cue.text.split("\\N"):
            line_structure.append(
                [next(word_iter) for _ in raw_line.split()],
            )
    except StopIteration:
        return [cue.words]
    return line_structure


def _active_word_formats(
    line_structure: Sequence[Sequence[WordTiming]],
    *,
    primary_color: str,
    secondary_color: str,
) -> dict[int, tuple[str, str, str]]:
    templates = (
        f"{{\\alpha&H00&\\c{secondary_color}&}}",
        f"{{\\alpha&H00&\\c{primary_color}&}}",
        f"{{\\alpha&HFF&\\c{secondary_color}&}}",
    )
    formats: dict[int, tuple[str, str, str]] = {}
    for line_words in line_structure:
        for word in line_words:
            formats.setdefault(
                id(word),
                (
                    f"{templates[0]}{word.text}",
                    f"{templates[1]}{word.text}",
                    f"{templates[2]}{word.text}",
                ),
            )
    return formats


def _formatted_word_block(
    line_structure: Sequence[Sequence[WordTiming]],
    formats: dict[int, tuple[str, str, str]],
    *,
    active_word_id: int | None,
) -> str:
    rendered_lines: list[str] = []
    for line_words in line_structure:
        rendered_lines.append(
            " ".join(
                formats[id(word)][0 if active_word_id is None else (1 if id(word) == active_word_id else 2)]
                for word in line_words
            )
        )
    return "\\N".join(rendered_lines)


def _timed_active_word_events(
    cue: Cue,
    *,
    line_structure: Sequence[Sequence[WordTiming]],
    formats: dict[int, tuple[str, str, str]],
) -> List[str]:
    if cue.words is None:
        return []
    events = [
        format_ass_dialogue(
            cue.start,
            cue.end,
            _formatted_word_block(
                line_structure,
                formats,
                active_word_id=None,
            ),
            layer=0,
        )
    ]
    for word in cue.words:
        if id(word) not in formats:
            continue
        events.append(
            format_ass_dialogue(
                word.start,
                word.end,
                _formatted_word_block(
                    line_structure,
                    formats,
                    active_word_id=id(word),
                ),
                layer=1,
            )
        )
    return events


def generate_active_word_ass(
    cue: Cue,
    max_lines: int,
    primary_color: str,
    secondary_color: str,
) -> List[str]:
    """
    Generates ASS dialogue lines for 'active word' highlighting.
    Each word gets its own dialogue event, appearing for its duration.

    When max_lines=0 (single word mode): Show ONLY the active word, nothing else.
    When max_lines>0: Show all words with the active word highlighted.
    """
    if not cue.words:
        return _active_events_without_word_timings(
            cue,
            max_lines=max_lines,
            primary_color=primary_color,
        )
    if max_lines == 0:
        return [
            format_ass_dialogue(
                word.start,
                word.end,
                f"{{\\c{primary_color}&}}{word.text}",
            )
            for word in cue.words
            if word.text.strip()
        ]
    line_structure = _active_word_line_structure(cue)
    formats = _active_word_formats(
        line_structure,
        primary_color=primary_color,
        secondary_color=secondary_color,
    )
    return _timed_active_word_events(
        cue,
        line_structure=line_structure,
        formats=formats,
    )


def _clone_cues(cues: Sequence[Cue]) -> List[Cue]:
    return [
        Cue(
            start=cue.start,
            end=cue.end,
            text=cue.text,
            words=(
                [WordTiming(start=word.start, end=word.end, text=word.text) for word in cue.words if word.text]
                if cue.words
                else None
            ),
        )
        for cue in cues
    ]


def _trim_cue_words(cue: Cue) -> None:
    if not cue.words:
        return
    trimmed_words = [
        WordTiming(
            start=word.start,
            end=min(word.end, cue.end),
            text=word.text,
        )
        for word in cue.words
        if word.start < cue.end and min(word.end, cue.end) > word.start
    ]
    if trimmed_words:
        cue.words = trimmed_words
        cue.text = " ".join(word.text for word in trimmed_words)
        return
    cue.words = None
    cue.text = ""
    logger.warning("All words clipped for cue at %s due to overlap", cue.start)


def _clamp_overlapping_cue(current: Cue, next_cue: Cue, *, min_gap_s: float) -> None:
    if current.end <= current.start:
        logger.warning(
            "Dropping invalid cue before overlap check: %s - %s",
            current.start,
            current.end,
        )
        return
    if current.end <= next_cue.start:
        return

    desired_end = next_cue.start - min_gap_s
    logger.info(
        "Overlap detected: Current(%s-%s) meets Next(%s-%s). Desired End: %s",
        current.start,
        current.end,
        next_cue.start,
        next_cue.end,
        desired_end,
    )
    if desired_end > current.start:
        current.end = desired_end
    elif next_cue.start > current.start:
        current.end = next_cue.start
    else:
        if next_cue.start < current.start:
            logger.warning(
                "Weird overlap: Next starts BEFORE current? Current:%s Next:%s",
                current.start,
                next_cue.start,
            )
        return
    _trim_cue_words(current)


def _keep_normalized_cue(cue: Cue) -> bool:
    if cue.end > cue.start and cue.text.strip():
        return True
    logger.warning(
        "Dropping cue from ASS normalization (zero duration or empty text): start=%s end=%s text=%r",
        cue.start,
        cue.end,
        cue.text,
    )
    return False


def normalize_cues_for_ass(cues: Sequence[Cue]) -> List[Cue]:
    """
    Prepare cues for ASS rendering:
    - Clone inputs (avoid mutating callers)
    - Sort by start time
    - Clamp overlaps so only one subtitle block is visible at a time
    """
    logger.info("Entering normalize_cues_for_ass with %d cues", len(cues))
    if cues:
        logger.info("First cue: %s - %s, Last cue: %s - %s", cues[0].start, cues[0].end, cues[-1].start, cues[-1].end)

    cloned = _clone_cues(cues)
    cloned.sort(key=lambda c: (c.start, c.end))
    for index, current in enumerate(cloned[:-1]):
        _clamp_overlapping_cue(
            current,
            cloned[index + 1],
            min_gap_s=0.01,
        )
    final_cues = [cue for cue in cloned if _keep_normalized_cue(cue)]
    logger.info("Exiting normalize_cues_for_ass with %d cues", len(final_cues))
    return final_cues


def _load_render_cues(
    transcript_path: Path | None,
    cues: List[Cue] | None,
) -> List[Cue]:
    if cues is not None:
        return list(cues)
    if transcript_path is None:
        raise ValueError("Either transcript_path or cues must be provided")
    return [Cue(start=start, end=end, text=normalize_text(text)) for start, end, text in parse_srt(transcript_path)]


def _sanitize_render_cues(cues: Sequence[Cue]) -> List[Cue]:
    return [
        Cue(
            start=cue.start,
            end=cue.end,
            text=sanitize_ass_text(cue.text),
            words=(
                [
                    WordTiming(
                        start=word.start,
                        end=word.end,
                        text=sanitize_ass_text(word.text),
                    )
                    for word in cue.words
                ]
                if cue.words
                else None
            ),
        )
        for cue in cues
    ]


def _prepare_render_cues(
    cues: Sequence[Cue],
    *,
    effective_chars: int,
    max_lines: int,
) -> List[Cue]:
    prepared = _sanitize_render_cues(cues)
    if max_lines == 1:
        prepared = split_long_cues(
            prepared,
            max_chars=effective_chars,
            max_lines=1,
        )
    prepared = normalize_cues_for_ass(prepared)
    if max_lines > 1:
        prepared = split_long_cues(
            prepared,
            max_chars=effective_chars,
            max_lines=max_lines,
        )
        prepared = normalize_cues_for_ass(prepared)
    return prepared


def _resolve_ass_output(
    *,
    transcript_path: Path | None,
    output_dir: Path | None,
) -> Path:
    if output_dir is None:
        if transcript_path is None:
            raise ValueError("output_dir is required when transcript_path is omitted")
        output_dir = transcript_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = transcript_path.stem if transcript_path is not None else "subtitles"
    return output_dir / f"{output_stem}.ass"


def _render_cue_events(
    cue: Cue,
    *,
    highlight_style: str,
    max_lines: int,
    effective_chars: int,
    primary_color: str,
    secondary_color: str,
    subtitle_position: int,
    font_size: int,
    play_res_x: int,
    play_res_y: int,
) -> List[str]:
    if highlight_style == "active" and (max_lines == 0 or cue.words):
        active_text = cue.text
        if max_lines > 0:
            active_text = format_active_word_text(
                cue,
                max_lines=max_lines,
                max_chars=effective_chars,
            )
        active_events = generate_active_word_ass(
            Cue(
                start=cue.start,
                end=cue.end,
                text=active_text,
                words=cue.words,
            ),
            max_lines=max_lines,
            primary_color=primary_color,
            secondary_color=secondary_color,
        )
    else:
        text = format_karaoke_text(
            cue,
            max_lines=max_lines,
            max_chars=effective_chars,
        )
        active_events = [format_ass_dialogue(cue.start, cue.end, text)]
    return position_ass_dialogue_events(
        active_events,
        subtitle_position=subtitle_position,
        font_size=font_size,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
    )


def create_styled_subtitle_file(
    transcript_path: Path | None = None,
    cues: List[Cue] | None = None,
    font: str = settings.default_sub_font,
    font_size: int = settings.default_sub_font_size,
    primary_color: str = settings.default_sub_color,
    secondary_color: str = settings.default_sub_secondary_color,
    outline_color: str = settings.default_sub_outline_color,
    back_color: str = settings.default_sub_back_color,
    outline: int = settings.default_sub_stroke_width,
    alignment: int = settings.default_sub_alignment,
    margin_v: int = settings.default_sub_margin_v,
    margin_l: int = settings.default_sub_margin_l,
    margin_r: int = settings.default_sub_margin_r,
    subtitle_position: int = 16,  # 5-95 progression from safe bottom to safe top
    max_lines: int = 2,
    shadow_strength: int = 4,
    play_res_x: int = settings.default_width,
    play_res_y: int = settings.default_height,
    output_dir: Path | None = None,
    highlight_style: str = "karaoke",  # "karaoke" (fill) or "active" (pop)
) -> Path:
    """
    Convert an SRT transcript to an ASS file with styling for vertical video.
    """
    parsed_cues = _load_render_cues(transcript_path, cues)
    effective_chars = effective_max_chars(
        max_chars=settings.max_sub_line_chars,
        font_size=font_size,
        play_res_x=play_res_x,
    )

    parsed_cues = _prepare_render_cues(
        parsed_cues,
        effective_chars=effective_chars,
        max_lines=max_lines,
    )
    ass_path = _resolve_ass_output(
        transcript_path=transcript_path,
        output_dir=output_dir,
    )

    # Keep a valid fallback style margin; every event below receives an exact
    # top-center position so multi-line blocks remain inside the safe frame.
    position_pct = settings_utils.normalize_subtitle_position(subtitle_position)
    final_margin_v = int(play_res_y * position_pct / 100)
    final_alignment = alignment
    render_font_size = settings_utils.font_size_for_ass_rendering(font_size)

    header = ass_header(
        font=font,
        font_size=render_font_size,
        primary_color=primary_color,
        secondary_color=secondary_color,
        outline_color=outline_color,
        back_color=back_color,
        outline=outline,
        alignment=final_alignment,
        margin_v=final_margin_v,
        margin_l=margin_l,
        margin_r=margin_r,
        shadow_strength=shadow_strength,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
    )
    lines = [header]

    for cue in parsed_cues:
        lines.extend(
            _render_cue_events(
                cue,
                highlight_style=highlight_style,
                max_lines=max_lines,
                effective_chars=effective_chars,
                primary_color=primary_color,
                secondary_color=secondary_color,
                subtitle_position=position_pct,
                font_size=render_font_size,
                play_res_x=play_res_x,
                play_res_y=play_res_y,
            )
        )

    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path
