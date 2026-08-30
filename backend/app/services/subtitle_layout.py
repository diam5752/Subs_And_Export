"""Balanced subtitle wrapping, chunking, and timed-text layout."""

from __future__ import annotations

import functools
from typing import Any, Callable, List, Sequence

from backend.app.core.config import settings
from backend.app.services.subtitle_types import Cue, WordTiming

STRONG_BREAK_PUNCTUATION = frozenset(".!?;:…")
SOFT_BREAK_PUNCTUATION = frozenset(",")


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


def _line_text_length(texts: Sequence[str]) -> int:
    if not texts:
        return 0
    return sum(len(text) for text in texts) + max(0, len(texts) - 1)


def _line_break_bonus(last_text: str) -> float:
    stripped = last_text.rstrip()
    if not stripped:
        return 0.0
    tail = stripped[-1]
    if tail in STRONG_BREAK_PUNCTUATION:
        return 0.45
    if tail in SOFT_BREAK_PUNCTUATION:
        return 0.18
    return 0.0


def _balanced_line_cost(*, text: str, running_length: int, safe_max_chars: int, is_last_line: bool) -> float:
    overflow = max(0, running_length - safe_max_chars)
    visible_length = min(running_length, safe_max_chars)
    slack = max(0, safe_max_chars - visible_length)
    gap_weight = 0.35 if is_last_line else 1.0
    cost = (overflow**2) * 1000.0 + (slack**2) * gap_weight
    return cost if is_last_line else cost - _line_break_bonus(text)


def _prefer_balanced_layout(
    current: tuple[float, tuple[int, ...]] | None,
    candidate: tuple[float, tuple[int, ...]],
) -> tuple[float, tuple[int, ...]]:
    if current is None or candidate[0] < current[0]:
        return candidate
    return current


class _BalancedLayoutSolver:
    def __init__(self, texts: Sequence[str], safe_max_chars: int) -> None:
        self.texts = texts
        self.safe_max_chars = safe_max_chars
        self._cache: dict[int, tuple[float, tuple[int, ...]]] = {}

    def best_layout(self, start_index: int) -> tuple[float, tuple[int, ...]]:
        cached = self._cache.get(start_index)
        if cached is not None:
            return cached
        if start_index >= len(self.texts):
            return 0.0, ()

        best: tuple[float, tuple[int, ...]] | None = None
        running_length = 0
        for end_index in range(start_index, len(self.texts)):
            text = self.texts[end_index]
            running_length = len(text) if end_index == start_index else running_length + 1 + len(text)
            if running_length > self.safe_max_chars and end_index > start_index:
                break

            line_cost = _balanced_line_cost(
                text=text,
                running_length=running_length,
                safe_max_chars=self.safe_max_chars,
                is_last_line=end_index == len(self.texts) - 1,
            )
            next_cost, next_breaks = self.best_layout(end_index + 1)
            candidate = (line_cost + next_cost, (end_index + 1, *next_breaks))
            best = _prefer_balanced_layout(best, candidate)

        fallback_break = min(start_index + 1, len(self.texts))
        resolved = best if best is not None else (0.0, (fallback_break,))
        self._cache[start_index] = resolved
        return resolved


def _items_from_breakpoints(items: Sequence[Any], breakpoints: Sequence[int]) -> List[List[Any]]:
    lines: List[List[Any]] = []
    start_index = 0
    for end_index in breakpoints:
        lines.append(list(items[start_index:end_index]))
        start_index = end_index
    return lines or [list(items)]


def _wrap_items_balanced(
    items: Sequence[Any],
    get_text: Callable[[Any], str],
    max_chars: int,
) -> List[List[Any]]:
    if not items:
        return []

    safe_max_chars = max(1, max_chars)
    texts = [get_text(item) for item in items]
    _, breakpoints = _BalancedLayoutSolver(texts, safe_max_chars).best_layout(0)
    return _items_from_breakpoints(items, breakpoints)


def _unused_wrapped_line_penalty(
    *,
    line_count: int,
    remaining_items: int,
    safe_max_lines: int,
) -> float:
    if remaining_items <= 0 or line_count >= safe_max_lines:
        return 0.0
    return ((safe_max_lines - line_count) / safe_max_lines) * 0.25


def _remaining_tail_penalty(remaining_items: int) -> float:
    if remaining_items == 1:
        return 0.6
    if remaining_items == 2:
        return 0.18
    return 0.0


def _wrapped_punctuation_bonus(wrapped_lines: Sequence[Sequence[str]]) -> float:
    last_line = wrapped_lines[-1]
    last_token = str(last_line[-1]) if last_line else ""
    return _line_break_bonus(last_token)


def _score_wrapped_chunk(
    wrapped_lines: Sequence[Sequence[str]],
    *,
    max_chars: int,
    max_lines: int,
    remaining_items: int,
) -> float:
    if not wrapped_lines:
        return float("-inf")

    lengths = [_line_text_length(line) for line in wrapped_lines]
    safe_max_chars = max(1, max_chars)
    safe_max_lines = max(1, max_lines)
    total_tokens = sum(len(line) for line in wrapped_lines)
    fill_ratio = sum(min(length, safe_max_chars) for length in lengths) / (safe_max_lines * safe_max_chars)
    imbalance = ((max(lengths) - min(lengths)) / safe_max_chars) if len(lengths) > 1 else 0.0
    unused_line_penalty = _unused_wrapped_line_penalty(
        line_count=len(wrapped_lines),
        remaining_items=remaining_items,
        safe_max_lines=safe_max_lines,
    )
    single_token_penalty = 0.45 if remaining_items > 0 and total_tokens == 1 else 0.0
    tail_penalty = _remaining_tail_penalty(remaining_items)
    punctuation_bonus = _wrapped_punctuation_bonus(wrapped_lines)

    return (
        fill_ratio - (imbalance * 0.35) - unused_line_penalty - single_token_penalty - tail_penalty + punctuation_bonus
    )


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
    return _wrap_items_balanced(words, lambda word: word, max_chars)


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
    return _wrap_items_balanced(words, lambda word: word.text, max_chars)


def _karaoke_prefix(*, word: WordTiming, word_index: int, current_time: float) -> str:
    prefix = " " if word_index > 0 else ""
    gap = word.start - current_time
    if gap > 0.01:
        return f"{{\\k{int(round(gap * 100))}}}{prefix}"
    return prefix


def _karaoke_word_tag(word: WordTiming) -> str:
    duration_centiseconds = max(1, int(round((word.end - word.start) * 100)))
    return f"{{\\k{duration_centiseconds}}}{word.text}"


def _format_karaoke_line(line_words: Sequence[WordTiming], current_time: float) -> tuple[str, float]:
    line_parts: List[str] = []
    for word_index, word in enumerate(line_words):
        line_parts.append(_karaoke_prefix(word=word, word_index=word_index, current_time=current_time))
        line_parts.append(_karaoke_word_tag(word))
        current_time = word.end
    return "".join(line_parts), current_time


def format_karaoke_text(cue: Cue, max_lines: int = 2, max_chars: int = settings.max_sub_line_chars) -> str:
    """
    Format text for ASS subtitles with karaoke tags (\\k).
    """
    if not cue.words:
        text = cue.text or ""
        raw_lines = wrap_lines(text.split(), max_chars=max_chars, max_lines=max_lines)
        return "\\N".join(" ".join(line) for line in raw_lines)

    lines_of_words = wrap_word_timings(cue.words, max_chars=max_chars, max_lines=max_lines)
    ass_lines: List[str] = []
    current_time = cue.start
    for line_words in lines_of_words:
        ass_line, current_time = _format_karaoke_line(line_words, current_time)
        ass_lines.append(ass_line)

    return "\\N".join(ass_lines)


def format_active_word_text(cue: Cue, max_lines: int, max_chars: int = settings.max_sub_line_chars) -> str:
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


def chunk_items(items: List[Any], get_text: Callable[[Any], str], max_chars: int, max_lines: int) -> List[List[Any]]:
    """
    Chunk items into groups that fit within max_lines while preferring
    balanced line lengths and natural breakpoints.
    """
    if not items:
        return []

    total_items = len(items)

    @functools.lru_cache(maxsize=None)
    def best_chunking(start_index: int) -> tuple[float, tuple[int, ...]]:
        if start_index >= total_items:
            return 0.0, ()

        best_score = float("-inf")
        best_breaks: tuple[int, ...] = (min(start_index + 1, total_items),)
        candidate_texts: List[str] = []

        for end_index in range(start_index, total_items):
            candidate_texts.append(get_text(items[end_index]))
            wrapped = wrap_lines(candidate_texts, max_chars=max_chars, max_lines=max_lines)
            wrapped_count = len(wrapped)

            if wrapped_count > max_lines and end_index > start_index:
                break

            chunk_score = _score_wrapped_chunk(
                wrapped,
                max_chars=max_chars,
                max_lines=max_lines,
                remaining_items=total_items - end_index - 1,
            )
            next_score, next_breaks = best_chunking(end_index + 1)
            total_score = chunk_score + next_score

            if total_score >= best_score:
                best_score = total_score
                best_breaks = (end_index + 1, *next_breaks)

        return best_score, best_breaks

    _, breakpoints = best_chunking(0)
    chunks: List[List[Any]] = []
    start_index = 0
    for end_index in breakpoints:
        chunks.append(list(items[start_index:end_index]))
        start_index = end_index
    return chunks


def _cue_fits(cue: Cue, *, max_chars: int, max_lines: int) -> bool:
    wrapped = wrap_lines(cue.text.split(), max_chars=max_chars, max_lines=max_lines)
    return len(wrapped) <= max_lines


def _expand_phrase_timing(word: WordTiming) -> List[WordTiming]:
    if " " not in word.text.strip():
        return [word]

    sub_texts = word.text.split()
    if len(sub_texts) <= 1:
        return [word]

    expanded: List[WordTiming] = []
    total_duration = word.end - word.start
    total_chars = len(word.text.replace(" ", ""))
    current_start = word.start
    for index, sub_text in enumerate(sub_texts):
        fraction = len(sub_text) / total_chars if total_chars > 0 else 1.0 / len(sub_texts)
        sub_end = min(current_start + total_duration * fraction, word.end)
        if index == len(sub_texts) - 1:
            sub_end = word.end
        expanded.append(WordTiming(start=current_start, end=sub_end, text=sub_text))
        current_start = sub_end
    return expanded


def _expand_timed_words(words: Sequence[WordTiming]) -> List[WordTiming]:
    expanded: List[WordTiming] = []
    for word in words:
        expanded.extend(_expand_phrase_timing(word))
    return expanded


def _timed_chunk_to_cue(chunk_words: Sequence[WordTiming], *, cue_end: float, is_last: bool) -> Cue:
    chunk_end = max(chunk_words[-1].end, cue_end) if is_last else chunk_words[-1].end
    return Cue(
        start=chunk_words[0].start,
        end=chunk_end,
        text=" ".join(word.text for word in chunk_words),
        words=list(chunk_words),
    )


def _split_timed_cue(cue: Cue, *, max_chars: int, max_lines: int) -> List[Cue]:
    assert cue.words is not None
    all_words = _expand_timed_words(cue.words)
    word_chunks = chunk_items(all_words, lambda word: word.text, max_chars, max_lines)
    return [
        _timed_chunk_to_cue(chunk, cue_end=cue.end, is_last=index == len(word_chunks) - 1)
        for index, chunk in enumerate(word_chunks)
    ]


def _untimed_chunk_end(
    *,
    chunk_text: str,
    current_start: float,
    cue: Cue,
    total_chars: int,
    is_last: bool,
) -> float:
    if is_last:
        return cue.end
    chunk_chars = len(chunk_text.replace(" ", ""))
    duration = (chunk_chars / total_chars) * (cue.end - cue.start)
    return min(current_start + duration, cue.end)


def _split_untimed_cue(cue: Cue, *, max_chars: int, max_lines: int) -> List[Cue]:
    text_chunks = chunk_items(cue.text.split(), lambda text: text, max_chars, max_lines)
    total_chars = max(1, len(cue.text.replace(" ", "")))
    split_cues: List[Cue] = []
    current_start = cue.start
    for index, chunk_words in enumerate(text_chunks):
        chunk_text = " ".join(chunk_words)
        chunk_end = _untimed_chunk_end(
            chunk_text=chunk_text,
            current_start=current_start,
            cue=cue,
            total_chars=total_chars,
            is_last=index == len(text_chunks) - 1,
        )
        split_cues.append(Cue(start=current_start, end=chunk_end, text=chunk_text, words=None))
        current_start = chunk_end
    return split_cues


def _split_overlong_cue(cue: Cue, *, max_chars: int, max_lines: int) -> List[Cue]:
    if cue.words:
        return _split_timed_cue(cue, max_chars=max_chars, max_lines=max_lines)
    if max_lines > 0:
        return _split_untimed_cue(cue, max_chars=max_chars, max_lines=max_lines)
    return []


def split_long_cues(cues: Sequence[Cue], max_chars: int = settings.max_sub_line_chars, max_lines: int = 2) -> List[Cue]:
    """Split long cues into multiple shorter cues that fit within ``max_lines``."""
    split_cues: List[Cue] = []
    for cue in cues:
        if _cue_fits(cue, max_chars=max_chars, max_lines=max_lines):
            split_cues.append(cue)
        else:
            split_cues.extend(_split_overlong_cue(cue, max_chars=max_chars, max_lines=max_lines))
    return split_cues
