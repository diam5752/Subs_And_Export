"""Subtitle rendering and styling service."""

from __future__ import annotations

import functools
import logging
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable, List, Sequence

from backend.app.core.config import settings
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
        match = re.match(
            r"(\d+:\d{2}:\d{2}[,.]\d+)\s*-->\s*(\d+:\d{2}:\d{2}[,.]\d+)", time_line
        )
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


def generate_active_word_ass(cue: Cue, max_lines: int, primary_color: str, secondary_color: str) -> List[str]:
    """
    Generates ASS dialogue lines for 'active word' highlighting.
    Each word gets its own dialogue event, appearing for its duration.
    """
    if not cue.words:
        # Fallback to standard dialogue if no word timings
        return [format_ass_dialogue(cue.start, cue.end, cue.text)]

    lines = []

    # Reconstruct the line structure from cue.text (which handles max_lines wrapping)
    # cue.text contains "\N" for line breaks. We must preserve this structure.
    # We map the flattened cue.words list into a nested structure based on cue.text lines.

    line_struct: List[List[WordTiming]] = []
    raw_lines = cue.text.split("\\N")

    word_iter = iter(cue.words)
    try:
        for raw_line in raw_lines:
            line_words = []
            tokens = raw_line.split()
            for _ in tokens:
                line_words.append(next(word_iter))
            line_struct.append(line_words)
    except StopIteration:
        # Fallback if text/words desync (should not happen with normal flow)
        line_struct = [cue.words]

    # Helper to build text for a specific active word (or None for all dim)
    def build_text(active_word: WordTiming | None, *, hide_inactive: bool = False) -> str:
        built_lines = []
        for line_words in line_struct:
            colored_tokens = []
            for w in line_words:
                is_active = w == active_word
                if hide_inactive and not is_active:
                    alpha = "&HFF&"
                    color = secondary_color
                else:
                    alpha = "&H00&"
                    color = primary_color if is_active else secondary_color
                colored_tokens.append(f"{{\\alpha{alpha}\\c{color}&}}{w.text}")
            built_lines.append(" ".join(colored_tokens))
        return "\\N".join(built_lines)

    # 1. Base Layer (Layer 0): All Dim (Secondary Color)
    # We render this for the FULL DURATION to provide the background.
    full_text_dim = build_text(active_word=None)
    lines.append(format_ass_dialogue(cue.start, cue.end, full_text_dim, layer=0))

    # 2. Active Layers (Layer 1): One event per word, Highlighting that word
    for word in cue.words:
        # Render ONLY the active word on this layer; base layer provides the rest.
        active_text = build_text(active_word=word, hide_inactive=True)
        # Layer 1 stands ON TOP of Layer 0
        lines.append(format_ass_dialogue(word.start, word.end, active_text, layer=1))

    return lines


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

    cloned: List[Cue] = []
    for cue in cues:
        cloned_words: List[WordTiming] | None = None
        if cue.words:
            cloned_words = [
                WordTiming(start=w.start, end=w.end, text=w.text)
                for w in cue.words
                if w.text
            ]
        cloned.append(Cue(start=cue.start, end=cue.end, text=cue.text, words=cloned_words))

    cloned.sort(key=lambda c: (c.start, c.end))

    # ASS timestamps are emitted with 2 decimal places.
    # Use a small gap to avoid rounding artifacts that can create visible overlaps.
    min_gap_s = 0.01

    for idx in range(len(cloned) - 1):
        current = cloned[idx]
        next_cue = cloned[idx + 1]

        if current.end <= current.start:
            logger.warning("Dropping invalid cue before overlap check: %s - %s", current.start, current.end)
            continue

        # If overlapping, clamp current to (next.start - gap) when possible.
        # Rationale: We prefer to show the next subtitle accurately as it's often
        # a fresh sentence or thought.
        desired_end = next_cue.start - min_gap_s

        # If segments strictly overlap (current.end > next.start)
        if current.end > next_cue.start:
            logger.info("Overlap detected: Current(%s-%s) meets Next(%s-%s). Desired End: %s",
                        current.start, current.end, next_cue.start, next_cue.end, desired_end)

            # Check if clamping would destroy the segment
            if desired_end <= current.start:
                # DANGER: next cue starts before or at the same time as current.
                # If they start at the same time, we'll keep both but they might overprint.
                # If 'current' is already very short, don't clamp further.
                if next_cue.start <= current.start:
                    # Keep current end, let them overlap (better than losing text)
                    if next_cue.start < current.start:
                         logger.warning("Weird overlap: Next starts BEFORE current? Current:%s Next:%s", current.start, next_cue.start)
                    continue
                else:
                    # Clamp to next.start exactly if gap is too large
                    current.end = next_cue.start
                    logger.info("Clamped current end to next start: %s", current.end)
            else:
                current.end = desired_end
                logger.info("Clamped current end to desired end: %s", current.end)

            # Update words text if they were clipped
            if current.words:
                trimmed_words: List[WordTiming] = []
                for w in current.words:
                    if w.start >= current.end:
                        continue
                    w_end = min(w.end, current.end)
                    if w_end <= w.start:
                        # If word is entirely after the new end, skip it
                        continue
                    trimmed_words.append(WordTiming(start=w.start, end=w_end, text=w.text))

                if trimmed_words:
                    current.words = trimmed_words
                    current.text = " ".join(w.text for w in trimmed_words)
                else:
                    # If all words were clipped, text becomes empty and it will be dropped below
                    current.words = None
                    current.text = ""
                    logger.warning("All words clipped for cue at %s due to overlap", current.start)

    # Drop empty/zero-length cues (libass can behave oddly on them).
    final_cues = []
    for c in cloned:
        if c.end > c.start and c.text.strip():
            final_cues.append(c)
        else:
            logger.warning("Dropping cue from ASS normalization (zero duration or empty text): start=%s end=%s text=%r", c.start, c.end, c.text)

    logger.info("Exiting normalize_cues_for_ass with %d cues", len(final_cues))
    return final_cues


def effective_max_chars(*, max_chars: int, font_size: int, play_res_x: int) -> int:
    """
    Derive a safe character limit for line wrapping based on the intended font size.
    """
    if max_chars <= 0:
        return 1
    if font_size <= 0:
        return max_chars

    base_font = settings.default_sub_font_size
    base_width = settings.default_width
    width_scale = (play_res_x / base_width) if base_width > 0 else 1.0
    font_scale = (base_font / font_size) if base_font > 0 else 1.0

    effective = int(round(max_chars * width_scale * font_scale))
    return max(10, min(40, effective))


def wrap_lines(
    words: List[str],
    max_chars: int = settings.max_sub_line_chars,
    max_lines: int = 2,
) -> List[List[str]]:
    """
    Wrap words into multiple lines without overflowing the safe width.
    """
    if not words:
        return []

    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_len = len(word)
        space_needed = 1 if current_length > 0 else 0

        # Case 1: Word fits on current line
        if current_length + space_needed + word_len <= max_chars:
            current_line.append(word)
            current_length += space_needed + word_len
            continue

        # Case 2: Word does not fit
        if word_len > max_chars:
             # Try to fill current line with part of the word
             remaining = word
             if current_length > 0:
                 space_left = max_chars - current_length - space_needed
                 if space_left >= 1:
                     chunk = remaining[:space_left]
                     current_line.append(chunk)
                     lines.append(current_line)
                     current_line = []
                     current_length = 0
                     remaining = remaining[space_left:]
                     space_needed = 0
                 else:
                     lines.append(current_line)
                     current_line = []
                     current_length = 0
                     space_needed = 0

             # Now process remaining as new lines
             while len(remaining) > max_chars:
                 lines.append([remaining[:max_chars]])
                 remaining = remaining[max_chars:]

             if remaining:
                 current_line = [remaining]
                 current_length = len(remaining)

        else:
             # Word fits on a NEW line
             if current_line:
                 lines.append(current_line)

             current_line = [word]
             current_length = word_len

    if current_line:
        lines.append(current_line)

    return lines


def wrap_word_timings(
    words: List[WordTiming],
    max_chars: int = settings.max_sub_line_chars,
    max_lines: int = 2,
) -> List[List[WordTiming]]:
    """
    Wrap WordTiming objects into multiple lines without overflowing the safe width.
    """
    if not words:
        return []

    lines = []
    current_line = []
    current_length = 0

    for word in words:
        word_len = len(word.text)
        space_needed = 1 if current_length > 0 else 0

        # Case 1: Word fits on current line
        if current_length + space_needed + word_len <= max_chars:
            current_line.append(word)
            current_length += space_needed + word_len
            continue

        # Case 2: Word does not fit
        # For WordTiming, we generally avoid splitting active words mid-word
        # unless absolutely necessary because it complicates timing significantly.
        # Simple strategy: Move to next line.

        # If current line is not empty, push it and start new line
        if current_line:
            lines.append(current_line)
            current_line = []
            current_length = 0
            space_needed = 0

        # Now check if word alone exceeds max_chars (very long word)
        if word_len > max_chars:
             # Force it onto the line anyway (better than dropping it)
             lines.append([word])
        else:
             current_line = [word]
             current_length = word_len

    if current_line:
        lines.append(current_line)

    return lines


def format_karaoke_text(
    cue: Cue, max_lines: int = 2, max_chars: int = settings.max_sub_line_chars
) -> str:
    """
    Format text for ASS subtitles with karaoke tags (\\k).
    """
    if not cue.words:
        # Fallback to static wrapping if no timing data
        text = cue.text or ""
        raw_lines = wrap_lines(text.split(), max_chars=max_chars, max_lines=max_lines)
        return "\\N".join(" ".join(line) for line in raw_lines)

    # Use wrap_word_timings to splits WordTiming objects into LINES (not pages)
    lines_of_words = wrap_word_timings(cue.words, max_chars=max_chars, max_lines=max_lines)

    ass_lines = []
    current_time = cue.start

    for line_words in lines_of_words:
        line_parts = []
        for i, word in enumerate(line_words):
            # Calculate gap from previous event
            gap = word.start - current_time

            # Determine prefix (space or gap filler)
            # If not the very first word of the line, we usually want a space visual
            prefix = " " if i > 0 else ""

            if gap > 0.01:
                # Significant gap: assign it to the prefix
                gap_cs = int(round(gap * 100))
                line_parts.append(f"{{\\k{gap_cs}}}{prefix}")
            elif i > 0:
                # No significant gap, but we have a space.
                line_parts.append(prefix)

            # Duration of the word itself
            dur = word.end - word.start
            dur_cs = int(round(dur * 100))
            if dur_cs < 1: dur_cs = 1 # Minimal duration

            line_parts.append(f"{{\\k{dur_cs}}}{word.text}")

            current_time = word.end

        ass_lines.append("".join(line_parts))

    return "\\N".join(ass_lines)


def format_active_word_text(
    cue: Cue, max_lines: int, max_chars: int = settings.max_sub_line_chars
) -> str:
    """
    Wrap cue text for active-word rendering while preserving word/token alignment.
    """
    if max_lines <= 1:
        return cue.text

    if cue.words:
        words = [w.text for w in cue.words if w.text]
    else:
        words = [w for w in cue.text.split() if w]

    wrapped_lines = wrap_lines(words, max_chars=max_chars, max_lines=max_lines)
    if not wrapped_lines:
        return ""

    joined = [" ".join(line) for line in wrapped_lines]
    return "\\N".join(joined)


def chunk_items(
    items: List[Any],
    get_text: Callable[[Any], str],
    max_chars: int,
    max_lines: int
) -> List[List[Any]]:
    """
    Greedily chunks items (strings or WordTiming objects) into groups that fit
    within max_lines x max_chars.
    """
    chunks = []
    current_chunk: List[Any] = []
    current_lines = 1
    current_line_chars = 0

    for item in items:
        text = get_text(item)
        w_len = len(text)

        space = 1 if current_line_chars > 0 else 0

        # Check fit on current line
        if current_line_chars + space + w_len <= max_chars:
            current_line_chars += space + w_len
        else:
            # Does not fit on current line.
            # Calculate lines needed for this word alone
            word_lines = math.ceil(w_len / max_chars) if w_len > max_chars else 1

            # Check if adding this word (possibly wrapping) exceeds max_lines
            # If current_chunk is empty, we must accept it to avoid infinite loop
            if current_chunk and (current_lines + word_lines > max_lines):
                # Chunk full
                chunks.append(current_chunk)
                current_chunk = []
                # Reset for new chunk
                current_lines = 1
                current_line_chars = 0

                # Note: If the word itself > max_lines, it will be added to the new chunk
                # and take > max_lines. This is acceptable fallback behavior.
                current_lines = word_lines

            else:
                # Add to current chunk, wrapping to new line
                if current_chunk:
                    current_lines += 1  # We wrapped to at least one new line
                else:
                    # Starting fresh (should be covered by reset above, but safety)
                    current_lines = 1

                if w_len > max_chars:
                    current_lines += (word_lines - 1)

            # Update chars for the last line of the word
            if w_len > max_chars:
                current_line_chars = w_len % max_chars
                if current_line_chars == 0:
                    current_line_chars = max_chars
            else:
                current_line_chars = w_len

        current_chunk.append(item)

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def split_long_cues(
    cues: Sequence[Cue],
    max_chars: int = settings.max_sub_line_chars,
    max_lines: int = 2
) -> List[Cue]:
    """
    Split long cues into multiple shorter cues to ensure they fit within max_lines.
    """
    new_cues = []

    for cue in cues:
        # 1. First check if the WHOLE cue fits (optimization)
        # using the same wrapping logic we'll use for display
        cues_text_words = cue.text.split()
        full_wrapped = wrap_lines(cues_text_words, max_chars=max_chars, max_lines=max_lines)
        if len(full_wrapped) <= max_lines:
            new_cues.append(cue)
            continue

        # 2. If it doesn't fit, we need to split it
        if cue.words:
            # Flatten words first (handling phrase expansion)
            all_words: List[WordTiming] = []
            for w in cue.words:
                if " " in w.text.strip():
                    # It's a phrase. Split it.
                    sub_texts = w.text.split()
                    if len(sub_texts) > 1:
                        # Linear interpolation for sub-words
                        total_dur = w.end - w.start
                        total_chars = len(w.text.replace(" ", ""))
                        current_sub_start = w.start

                        for i, sw_text in enumerate(sub_texts):
                            char_count = len(sw_text)
                            # avoid div by zero
                            frac = (char_count / total_chars) if total_chars > 0 else (1.0 / len(sub_texts))
                            dur = total_dur * frac

                            # Adjust end time
                            sub_end = min(current_sub_start + dur, w.end)
                            # Ensure last one aligns perfectly
                            if i == len(sub_texts) - 1:
                                sub_end = w.end

                            all_words.append(WordTiming(
                                start=current_sub_start,
                                end=sub_end,
                                text=sw_text
                            ))
                            current_sub_start = sub_end
                    else:
                        all_words.append(w)
                else:
                    all_words.append(w)

            # Use optimized chunking
            word_chunks = chunk_items(all_words, lambda w: w.text, max_chars, max_lines)

            for chunk_words in word_chunks:
                chunk_text = " ".join([cw.text for cw in chunk_words])
                chunk_start = chunk_words[0].start
                chunk_end = chunk_words[-1].end

                # Ensure we don't drop the official end time if it's longer
                # (unless we split, in which case the last chunk ends at cue.end)
                if chunk_words is word_chunks[-1]:
                     chunk_end = max(chunk_end, cue.end)

                new_cues.append(Cue(
                    start=chunk_start,
                    end=chunk_end,
                    text=chunk_text,
                    words=list(chunk_words)
                ))

        elif max_lines > 0:
            # Fallback for standard model (no words) - Use Linear Interpolation
            cues_text_words = cue.text.split()

            # Use optimized chunking on strings
            text_chunks = chunk_items(cues_text_words, lambda s: s, max_chars, max_lines)

            cue_duration = cue.end - cue.start
            total_chars = len(cue.text.replace(" ", "")) # Approximation
            if total_chars == 0: total_chars = 1

            current_start = cue.start

            for i, chunk_strs in enumerate(text_chunks):
                chunk_text = " ".join(chunk_strs)

                # Estimate duration
                chunk_chars = len(chunk_text.replace(" ", ""))
                duration = (chunk_chars / total_chars) * cue_duration
                chunk_end = current_start + duration

                # Clamp/Extend
                if i == len(text_chunks) - 1:
                    chunk_end = cue.end
                else:
                    chunk_end = min(chunk_end, cue.end)

                new_cues.append(Cue(
                    start=current_start,
                    end=chunk_end,
                    text=chunk_text,
                    words=None
                ))
                current_start = chunk_end

    return new_cues


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
    subtitle_position: int = 16,  # 5-35 (percentage from bottom)
    max_lines: int = 2,
    shadow_strength: int = 4,
    play_res_x: int = settings.default_width,
    play_res_y: int = settings.default_height,
    output_dir: Path | None = None,
    highlight_style: str = "karaoke", # "karaoke" (fill) or "active" (pop)
) -> Path:
    """
    Convert an SRT transcript to an ASS file with styling for vertical video.
    """
    parsed_cues: List[Cue]
    if cues:
        parsed_cues = list(cues)
    else:
        parsed_cues = [
            Cue(start=s, end=e, text=normalize_text(t))
            for s, e, t in parse_srt(transcript_path)
        ]

    effective_chars = effective_max_chars(
        max_chars=settings.max_sub_line_chars,
        font_size=font_size,
        play_res_x=play_res_x,
    )

    # Security: Sanitize all cues
    sanitized_cues = []
    for cue in parsed_cues:
        safe_text = sanitize_ass_text(cue.text)
        safe_words = None
        if cue.words:
            safe_words = [
                WordTiming(start=w.start, end=w.end, text=sanitize_ass_text(w.text))
                for w in cue.words
            ]
        sanitized_cues.append(Cue(start=cue.start, end=cue.end, text=safe_text, words=safe_words))
    parsed_cues = sanitized_cues

    # Pre-processing: If Single Line mode (max_lines=1), split long cues
    if max_lines == 1:
        # Reuse split_long_cues logic which handles max_lines=1 specifically
        parsed_cues = split_long_cues(parsed_cues, max_chars=effective_chars, max_lines=1)

    parsed_cues = normalize_cues_for_ass(parsed_cues)

    # Split for standard line wrapping if max_lines > 1
    if max_lines > 1:
        parsed_cues = split_long_cues(
            parsed_cues,
            max_chars=effective_chars,
            max_lines=max_lines
        )
        parsed_cues = normalize_cues_for_ass(parsed_cues)


    output_dir = output_dir or transcript_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    ass_path = output_dir / f"{transcript_path.stem}.ass"

    # Convert numeric subtitle_position (percentage) to margin_v
    position_pct = max(5, min(35, subtitle_position if subtitle_position is not None else 16))
    final_margin_v = int(play_res_y * position_pct / 100)
    final_alignment = alignment

    header = ass_header(
        font=font,
        font_size=font_size,
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
        if highlight_style == "active" and (max_lines == 0 or cue.words):
            # ACTIVE WORD MODE (Pop effect)
            active_cue = cue
            if max_lines > 0:
                active_text = format_active_word_text(
                    cue,
                    max_lines=max_lines,
                    max_chars=effective_chars,
                )
                active_cue = Cue(
                    start=cue.start,
                    end=cue.end,
                    text=active_text,
                    words=cue.words,
                )

            active_events = generate_active_word_ass(
                active_cue,
                max_lines=max_lines,
                primary_color=primary_color,
                secondary_color=secondary_color,
            )
            lines.extend(active_events)
        else:
            # STANDARD / KARAOKE FILL MODE
            text = format_karaoke_text(cue, max_lines=max_lines, max_chars=effective_chars)
            lines.append(format_ass_dialogue(cue.start, cue.end, text))

    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path
