"""Subtitle generation and styling helpers."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence, Tuple

from backend.app.core import config

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


@dataclass(frozen=True)
class PlatformCopy:
    title: str
    description: str


@dataclass(frozen=True)
class SocialCopy:
    tiktok: PlatformCopy
    youtube_shorts: PlatformCopy
    instagram: PlatformCopy


@dataclass
class ViralMetadata:
    hooks: List[str]
    caption_hook: str
    caption_body: str
    cta: str
    hashtags: List[str]


def _normalize_text(text: str) -> str:
    """
    Uppercase + strip accents for consistent, bold subtitle styling.
    """
    # Remove diacritics
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.upper()


def extract_audio(
    input_video: Path,
    output_dir: Path | None = None,
    check_cancelled: Callable[[], None] | None = None
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
        config.AUDIO_CODEC,
        "-ar",
        str(config.AUDIO_SAMPLE_RATE),
        "-ac",
        str(config.AUDIO_CHANNELS),
        str(audio_path),
    ]

    # Use Popen to allow interruption if check_cancelled is provided
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    try:
        # We need to read output to prevent buffer filling (deadlock)
        # process.communicate(timeout=...) reads pipes until timeout or completion

        while True:
            if check_cancelled:
                check_cancelled()

            try:
                # Read output with timeout
                # This drains the pipes so ffmpeg won't block
                _, stderr_data = process.communicate(timeout=0.2)

                # If communicate returns, the process has finished
                if process.returncode != 0:
                    err_msg = stderr_data.decode("utf-8") if stderr_data else "Unknown error"
                    raise subprocess.CalledProcessError(process.returncode, cmd, output=None, stderr=err_msg)
                break

            except subprocess.TimeoutExpired:
                # Process still running, loop again to check_cancelled
                continue

    except Exception:
        process.kill()
        process.wait()
        raise

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
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return float(result.stdout.strip())






import stable_whisper

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
    print(f"DEBUG_RUNTIME_CONFIG: config.WHISPER_MODEL_TURBO is '{config.WHISPER_MODEL_TURBO}'")
    if model_size == "turbo":
        model_size = config.WHISPER_MODEL_TURBO

    print(f"DEBUG: Loading Whisper model '{model_size}' (Device: {device})")

    # stable-ts wrapper for faster-whisper
    # It internally loads FasterWhisperModel and wraps it.
    model = stable_whisper.load_faster_whisper(
        model_size_or_path=model_size,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )
    return model


def should_use_openai(model_name: str | None) -> bool:
    """Check if the model name implies using OpenAI's API."""
    return model_name is not None and "openai" in model_name.lower()


def _model_uses_openai(model_name: str | None) -> bool:
    """Helper for internal use (alias of should_use_openai)."""
    return should_use_openai(model_name)




def _resolve_openai_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve OpenAI API key from arguments, env, or secrets file."""
    if explicit_key:
        return explicit_key

    # 1. Environment variable
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key

    # 2. Config/Secrets file
    secrets_path = config.PROJECT_ROOT / "config" / "secrets.toml"
    if secrets_path.exists():
        try:
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
                return secrets.get("OPENAI_API_KEY")
        except Exception:
            pass

    return None


def _resolve_groq_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve Groq API key from arguments, env, or secrets file."""
    if explicit_key:
        return explicit_key

    # 1. Environment variable
    env_key = os.getenv("GROQ_API_KEY")
    if env_key:
        return env_key

    # 2. Config/Secrets file
    secrets_path = config.PROJECT_ROOT / "config" / "secrets.toml"
    if secrets_path.exists():
        try:
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
                return secrets.get("GROQ_API_KEY")
        except Exception:
            pass

    return None







    if progress_callback:
        progress_callback(90.0)

    # Convert results
    cues: List[Cue] = []
    timed_text: List[TimeRange] = []

    for seg in result.segments:
        seg_start = seg.start
        seg_end = seg.end
        seg_text = seg.text

        timed_text.append((seg_start, seg_end, seg_text))

        words: Optional[List[WordTiming]] = None
        if seg.words:
            words = [
                WordTiming(start=w.start, end=w.end, text=_normalize_text(w.word))
                for w in seg.words
            ]

        cue_text = _normalize_text(seg_text)
        cues.append(Cue(start=seg_start, end=seg_end, text=cue_text, words=words))

    srt_path = output_dir / f"{audio_path.stem}.srt"
    _write_srt_from_segments(timed_text, srt_path)

    if progress_callback:
        progress_callback(100.0)

    return srt_path, cues



def generate_subtitles_from_audio(
    audio_path: Path,
    model_size: str = config.WHISPER_MODEL_TURBO,
    language: str | None = config.WHISPER_LANGUAGE,
    device: str = config.WHISPER_DEVICE,
    compute_type: str = config.WHISPER_COMPUTE_TYPE,
    beam_size: int | None = None,
    best_of: int | None = 1,
    output_dir: Path | None = None,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
    temperature: float | None = None,
    chunk_length: int | None = config.WHISPER_CHUNK_LENGTH,
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
        language = config.WHISPER_LANGUAGE

    wants_openai = provider == "openai" or _model_uses_openai(model_size)
    output_dir = output_dir or Path(tempfile.mkdtemp())
    output_dir.mkdir(parents=True, exist_ok=True)

    if wants_openai:
        transcriber = OpenAITranscriber(api_key=openai_api_key)
        return transcriber.transcribe(
            audio_path, output_dir, language=language, model=model_size or config.OPENAI_TRANSCRIBE_MODEL,
            initial_prompt=initial_prompt, progress_callback=progress_callback
        )

    if provider == "groq":
        transcriber = GroqTranscriber(api_key=openai_api_key)
        return transcriber.transcribe(
            audio_path, output_dir, language=language, model=config.GROQ_TRANSCRIBE_MODEL,
            initial_prompt=initial_prompt, progress_callback=progress_callback
        )

    if provider == "whispercpp":
        transcriber = StandardTranscriber()
        return transcriber.transcribe(
            audio_path, output_dir, language=language, model=config.WHISPERCPP_MODEL,
            progress_callback=progress_callback
        )

    # Default: Local Whisper
    transcriber = LocalWhisperTranscriber(device=device, compute_type=compute_type, beam_size=beam_size or 5)
    return transcriber.transcribe(
        audio_path, output_dir, language=language, model=model_size,
        best_of=best_of, temperature=temperature, initial_prompt=initial_prompt,
        vad_filter=vad_filter, condition_on_previous_text=condition_on_previous_text,
        progress_callback=progress_callback
    )


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
    shadow_strength: int = 4,
    play_res_x: int = config.DEFAULT_WIDTH,
    play_res_y: int = config.DEFAULT_HEIGHT,
) -> str:
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


def _format_ass_dialogue(start: float, end: float, text: str, layer: int = 0) -> str:
    return f"Dialogue: {layer},{_format_timestamp(start)},{_format_timestamp(end)},Default,,0,0,0,,{text}"

def _generate_active_word_ass(cue: Cue, max_lines: int, primary_color: str, secondary_color: str) -> List[str]:
    """
    Generates ASS dialogue lines for 'active word' highlighting.
    Each word gets its own dialogue event, appearing for its duration.
    """
    if not cue.words:
        # Fallback to standard dialogue if no word timings
        return [_format_ass_dialogue(cue.start, cue.end, cue.text)]

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
    lines.append(_format_ass_dialogue(cue.start, cue.end, full_text_dim, layer=0))

    # 2. Active Layers (Layer 1): One event per word, Highlighting that word
    for word in cue.words:
        # Render ONLY the active word on this layer; base layer provides the rest.
        active_text = build_text(active_word=word, hide_inactive=True)
        # Layer 1 stands ON TOP of Layer 0
        lines.append(_format_ass_dialogue(word.start, word.end, active_text, layer=1))

    return lines


def _normalize_cues_for_ass(cues: Sequence[Cue]) -> List[Cue]:
    """
    Prepare cues for ASS rendering:
    - Clone inputs (avoid mutating callers)
    - Sort by start time
    - Clamp overlaps so only one subtitle block is visible at a time
    """
    if not cues:
        return []

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
            continue

        # If overlapping, clamp current to (next.start - gap) when possible.
        desired_end = next_cue.start - min_gap_s
        if desired_end <= current.start:
            desired_end = next_cue.start

        if current.end > desired_end:
            current.end = max(current.start, desired_end)

            if current.words:
                trimmed_words: List[WordTiming] = []
                for w in current.words:
                    if w.start >= current.end:
                        continue
                    w_end = min(w.end, current.end)
                    if w_end <= w.start:
                        continue
                    trimmed_words.append(WordTiming(start=w.start, end=w_end, text=w.text))

                if trimmed_words:
                    current.words = trimmed_words
                    current.text = " ".join(w.text for w in trimmed_words)
                else:
                    current.words = None

    # Drop empty/zero-length cues (libass can behave oddly on them).
    return [c for c in cloned if c.end > c.start and c.text.strip()]


def _effective_max_chars(*, max_chars: int, font_size: int, play_res_x: int) -> int:
    """
    Derive a safe character limit for line wrapping based on the intended font size.

    The splitter/wrapper uses character counts as a proxy for pixel width.
    When the font size increases, we must reduce the per-line char budget to
    avoid text spilling outside the safe area.
    """
    if max_chars <= 0:
        return 1
    if font_size <= 0:
        return max_chars

    base_font = config.DEFAULT_SUB_FONT_SIZE
    base_width = config.DEFAULT_WIDTH
    width_scale = (play_res_x / base_width) if base_width > 0 else 1.0
    font_scale = (base_font / font_size) if base_font > 0 else 1.0

    effective = int(round(max_chars * width_scale * font_scale))
    return max(10, min(40, effective))


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
    subtitle_position: str = "default",  # "default", "top", "bottom"
    max_lines: int = 2,
    shadow_strength: int = 4,
    play_res_x: int = config.DEFAULT_WIDTH,
    play_res_y: int = config.DEFAULT_HEIGHT,
    output_dir: Path | None = None,
    highlight_style: str = "karaoke", # "karaoke" (fill) or "active" (pop)
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

    effective_max_chars = _effective_max_chars(
        max_chars=config.MAX_SUB_LINE_CHARS,
        font_size=font_size,
        play_res_x=play_res_x,
    )

    # Pre-processing: If Single Line mode (max_lines=1) is active,
    # we must ensure segments are short enough to fit on one line without crazy scaling.
    # We split long cues into smaller ones.
    if max_lines == 1:
        target_cues = parsed_cues
        split_cues = []

        for cue in target_cues:
            # If no words, can't split accurately, just keep it (or forceful string split?)
            if not cue.words or len(cue.text) <= effective_max_chars:
                split_cues.append(cue)
                continue

            # Smart split based on words
            current_chunk_words: List[WordTiming] = []
            current_len = 0

            for word in cue.words:
                w_len = len(word.text) + 1 # +1 for space

                # Check if adding this word exceeds limit AND we have at least one word already
                if current_len + w_len > effective_max_chars and current_chunk_words:
                    # Flush current chunk
                    chunk_text = " ".join(w.text for w in current_chunk_words)
                    chunk_start = current_chunk_words[0].start
                    chunk_end = current_chunk_words[-1].end

                    # Ensure continuity: gap fill?
                    # Actually, let's just use first word start and last word end.
                    # It might leave small gaps if silence, but for subtitles it's safer visually.

                    split_cues.append(Cue(
                        start=chunk_start,
                        end=chunk_end,
                        text=chunk_text,
                        words=list(current_chunk_words)
                    ))

                    # Reset
                    current_chunk_words = [word]
                    current_len = w_len
                else:
                    current_chunk_words.append(word)
                    current_len += w_len

            # Flush final chunk
            if current_chunk_words:
                chunk_text = " ".join(w.text for w in current_chunk_words)
                chunk_start = current_chunk_words[0].start
                chunk_end = current_chunk_words[-1].end
                # Extend last chunk to original end time if it's the very last part
                # to cover trailing silence/punctuation duration
                if not split_cues or split_cues[-1].end < cue.end:
                    chunk_end = max(chunk_end, cue.end)

                split_cues.append(Cue(
                    start=chunk_start,
                    end=chunk_end,
                    text=chunk_text,
                    words=list(current_chunk_words)
                ))

        parsed_cues = split_cues


    # Resolve dynamic positioning based on subtitle_position alias
    # SUBTITLE SPLITTING MODES:
    # max_lines=0: "1 word at a time" mode - each word is a separate subtitle event
    # max_lines=1/2/3: Standard line-based mode - cues are split to fit in max_lines
    has_word_timings = any(cue.words for cue in parsed_cues)


    if max_lines == 0:
        # "1 WORD AT A TIME" MODE:
        # If words exist: Real Karaoke (per-word timing)
        # If no words (Standard model): Linear Interpolation fallback (1 word per cue approximation)
        # We pass max_chars=1 to force splitting at every word (or even char, but _split_long_cues handles words)
        parsed_cues = _split_long_cues(parsed_cues, max_chars=1, max_lines=1)
    elif max_lines > 0:
        # STANDARD LINE-BASED MODE:
        # Split cues to ensure they fit strictly within max_lines.
        parsed_cues = _split_long_cues(
            parsed_cues,
            max_chars=effective_max_chars,
            max_lines=max_lines
        )
    # For cues without word timings (Standard model), don't split regardless of max_lines
    parsed_cues = _normalize_cues_for_ass(parsed_cues)

    output_dir = output_dir or transcript_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    ass_path = output_dir / f"{transcript_path.stem}.ass"

    # Map position to margin_v and alignment
    # ASS alignment: 2 = bottom center (MarginV from bottom), 8 = top center (MarginV from top)
    final_margin_v = margin_v
    final_alignment = alignment  # Default alignment (2 = bottom center)

    if subtitle_position == "top":
        # Middle area - just above default, still using bottom center alignment
        final_alignment = 2  # Bottom center
        final_margin_v = int(play_res_y * 0.32)  # ~32% from bottom
    elif subtitle_position == "bottom":
        # Movie style (low) - keep bottom center alignment
        final_alignment = 2  # Bottom center
        final_margin_v = int(play_res_y * 0.0625)  # ~6.25% from bottom (120/1920)
    # else "default" uses the passed margin_v (defaulting to config.DEFAULT_SUB_MARGIN_V = 320)
    # with bottom center alignment (2)

    header = _ass_header(
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
    # The header already includes "[Events]" and "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    # So we don't need to append them again here.

    for cue in parsed_cues:
        if highlight_style == "active" and (max_lines == 0 or cue.words):
            # ACTIVE WORD MODE (Pop effect)
            # Generate multiple events per cue, one for each word's duration
            active_cue = cue
            if max_lines > 0:
                active_text = _format_active_word_text(
                    cue,
                    max_lines=max_lines,
                    max_chars=effective_max_chars,
                )
                active_cue = Cue(
                    start=cue.start,
                    end=cue.end,
                    text=active_text,
                    words=cue.words,
                )

            active_events = _generate_active_word_ass(
                active_cue,
                max_lines=max_lines,
                primary_color=primary_color,
                secondary_color=secondary_color,
            )
            lines.extend(active_events)
        else:
            # STANDARD / KARAOKE FILL MODE
            text = _format_karaoke_text(cue, max_lines=max_lines, max_chars=effective_max_chars)
            lines.append(_format_ass_dialogue(cue.start, cue.end, text))

    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


def _chunk_items(
    items: List[Any],
    get_text: Callable[[Any], str],
    max_chars: int,
    max_lines: int
) -> List[List[Any]]:
    """
    Greedily chunks items (strings or WordTiming objects) into groups that fit
    within max_lines x max_chars.
    Avoids using textwrap inside the loop for O(N) performance instead of O(N^2).
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


def _split_long_cues(
    cues: Sequence[Cue],
    max_chars: int = config.MAX_SUB_LINE_CHARS,
    max_lines: int = 2
) -> List[Cue]:
    """
    Split long cues into multiple shorter cues to ensure they fit within max_lines.

    Args:
        cues: List of input cues
        max_chars: Maximum characters per line (e.g., 32)
        max_lines: Maximum number of lines allowed (e.g., 2)
    """
    new_cues = []

    for cue in cues:
        # 1. First check if the WHOLE cue fits (optimization)
        # using the same wrapping logic we'll use for display
        cues_text_words = cue.text.split()
        full_wrapped = _wrap_lines(cues_text_words, max_chars=max_chars, max_lines=max_lines)
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
            word_chunks = _chunk_items(all_words, lambda w: w.text, max_chars, max_lines)

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
            text_chunks = _chunk_items(cues_text_words, lambda s: s, max_chars, max_lines)

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


def _wrap_lines(
    words: List[str],
    max_chars: int = config.MAX_SUB_LINE_CHARS,
    max_lines: int = 2,
) -> List[List[str]]:
    """
    Wrap words into multiple lines without overflowing the safe width.

    Returns a list of lines (each line is a list of words).

    IMPORTANT: This function fills lines up to max_chars width, NOT balanced wrapping.
    The cue splitting logic ensures cues are small enough to fit in max_lines.

    Optimized to avoid overhead of textwrap.wrap (O(N) vs O(N^2) behavior in loops).
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


def _format_karaoke_text(
    cue: Cue, max_lines: int = 2, max_chars: int = config.MAX_SUB_LINE_CHARS
) -> str:
    """
    Format text for ASS subtitles.
    Formerly handled karaoke highlighting; currently only performs line wrapping.
    """
    # Use existing cues text splitting or wrapping
    text = cue.text
    if not text and cue.words:
        text = " ".join(w.text for w in cue.words)

    raw_words = text.split()
    wrapped_lines = _wrap_lines(raw_words, max_chars=max_chars, max_lines=max_lines)

    if not wrapped_lines:
        return ""

    joined = [" ".join(line) for line in wrapped_lines]
    return "\\N".join(joined)


def _format_active_word_text(
    cue: Cue, max_lines: int, max_chars: int = config.MAX_SUB_LINE_CHARS
) -> str:
    """
    Wrap cue text for active-word rendering while preserving word/token alignment.

    Active-word rendering relies on ``\\N`` line breaks to reconstruct the line
    structure and match words to their timed tokens.
    """
    if max_lines <= 1:
        return cue.text

    if cue.words:
        words = [w.text for w in cue.words if w.text]
    else:
        words = [w for w in cue.text.split() if w]

    wrapped_lines = _wrap_lines(words, max_chars=max_chars, max_lines=max_lines)
    if not wrapped_lines:
        return ""

    joined = [" ".join(line) for line in wrapped_lines]
    return "\\N".join(joined)







_STOPWORDS = {
    "και",
    "για",
    "στο",
    "στη",
    "the",
    "this",
    "that",
    "and",
    "for",
    "with",
    "your",
    "from",
    "about",
    "στον",
    "μια",
    "είναι",
    "που",
    "τους",
}


def cues_to_text(cues: Sequence[Cue]) -> str:
    """Collapse cue text into a single transcript string."""

    return " ".join(cue.text.strip() for cue in cues if cue.text).strip()


def _extract_keywords(text: str, limit: int = 5) -> List[str]:
    tokens = re.findall(r"[\wάέίόύήώϊϋΐΰ]+", text.lower())
    ranked: dict[str, tuple[int, int]] = {}
    for idx, tok in enumerate(tokens):
        if tok in _STOPWORDS or len(tok) <= 3:
            continue
        count, first_idx = ranked.get(tok, (0, idx))
        ranked[tok] = (count + 1, first_idx)
    ordered = sorted(ranked.items(), key=lambda item: (-item[1][0], item[1][1]))
    return [kw for kw, _ in ordered[:limit]]


def _summarize_text(text: str, max_words: int = 45) -> str:
    words = text.split()
    summary_words = words[:max_words]
    return " ".join(summary_words).strip()


def _compose_title(keywords: Sequence[str]) -> str:
    if not keywords:
        return "Greek Highlights"
    if len(keywords) == 1:
        return f"{keywords[0].title()} Highlights"
    return f"{keywords[0].title()} & {keywords[1].title()} Moments"


def _build_hashtags(keywords: Sequence[str], extra: Sequence[str]) -> List[str]:
    raw_tags = [f"#{kw.replace(' ', '')}" for kw in keywords]
    raw_tags.extend(f"#{tag}" if not tag.startswith("#") else tag for tag in extra)
    deduped = list(dict.fromkeys(raw_tags))
    return deduped[:10]


def _platform_copy(
    base_title: str,
    summary: str,
    hashtags: Sequence[str],
    *,
    title_suffix: str,
    call_to_action: str,
    extra_tags: Sequence[str],
) -> PlatformCopy:
    platform_title = f"{base_title} | {title_suffix}"
    all_tags = list(dict.fromkeys([*hashtags, *extra_tags]))
    formatted_tags = " ".join(f"#{tag.lstrip('#')}" for tag in all_tags)
    description = f"{summary}\n{call_to_action}\n{formatted_tags}".strip()
    return PlatformCopy(title=platform_title.strip(), description=description)


def build_social_copy(transcript_text: str) -> SocialCopy:
    """
    Create platform-optimized titles and descriptions from transcript text.

    The output stays deterministic and avoids external API calls so it can be
    used in CI environments.
    """

    clean_text = transcript_text.strip()
    keywords = _extract_keywords(clean_text)
    base_title = _compose_title(keywords)
    summary = _summarize_text(clean_text)
    shared_tags = _build_hashtags(keywords, ["greek", "subtitles", "verticalvideo"])

    tiktok_copy = _platform_copy(
        base_title,
        summary,
        shared_tags,
        title_suffix="TikTok",
        call_to_action="Follow for daily Greek clips.",
        extra_tags=["tiktok", "fyp", "viral"],
    )

    shorts_copy = _platform_copy(
        base_title,
        summary,
        shared_tags,
        title_suffix="YouTube Shorts",
        call_to_action="Subscribe for more Shorts-ready stories.",
        extra_tags=["shorts", "ytshorts", "greektalk"],
    )

    instagram_copy = _platform_copy(
        base_title,
        summary,
        shared_tags,
        title_suffix="Instagram Reels",
        call_to_action="Save & share if this inspired you!",
        extra_tags=["reels", "instagood", "greeklife"],
    )

    return SocialCopy(
        tiktok=tiktok_copy, youtube_shorts=shorts_copy, instagram=instagram_copy
    )


def _load_openai_client(api_key: str):
    """
    Load OpenAI client with secure API key.

    Args:
        api_key: OpenAI API key for authentication

    Returns:
        Configured OpenAI client instance

    Raises:
        RuntimeError: If openai package is not installed
    """
    api_key = _resolve_openai_api_key(api_key)
    if not api_key:
        raise RuntimeError(
            "OpenAI API key is required for AI enrichment. Please set it via:\n"
            "  1. Environment variable: export OPENAI_API_KEY='your-key'\n"
            "  2. secrets file: config/secrets.toml with OPENAI_API_KEY\n"
            "  3. Pass explicitly via api_key parameter"
        )
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - exercised in tests via monkeypatch
        raise RuntimeError(
            "openai package is required for LLM social copy generation. "
            "Install with: pip install openai"
        ) from exc

    return OpenAI(api_key=api_key)


def _clean_json_response(content: str) -> str:  # pragma: no cover - simple string clean helper
    """
    Strip markdown code fences from LLM response to ensure valid JSON.
    """
    content = content.strip()
    # Remove ```json ... ``` or just ``` ... ```
    if content.startswith("```"):
        # Find the first newline to skip the language identifier (e.g. "json")
        newline_idx = content.find("\n")
        if newline_idx != -1:
            content = content[newline_idx + 1 :]
        # Remove the trailing ```
        if content.endswith("```"):
            content = content[:-3]
    return content.strip()


def build_social_copy_llm(
    transcript_text: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.6,
) -> SocialCopy:
    """
    Generate professional social copy using OpenAI's GPT models.

    Securely handles API key from multiple sources (in priority order):
    1. Explicit api_key parameter
    2. OPENAI_API_KEY environment variable

    Args:
        transcript_text: Video transcript to generate social copy from
        api_key: Optional explicit API key (overrides env)
        model: Model name (defaults to gpt-4o-mini)
        temperature: Sampling temperature (0.0-2.0, default 0.6)

    Returns:
        SocialCopy with platform-specific titles and descriptions

    Raises:
        RuntimeError: If no API key is found in any source
        ValueError: If LLM response is invalid
    """
    # Try to get API key from multiple sources
    if not api_key:
        # Try environment variable
        api_key = os.getenv("OPENAI_API_KEY")

    # Validate API key is present
    if not api_key:
        raise RuntimeError(
            "OpenAI API key is required for AI enrichment. Please set it via:\n"
            "  1. Environment variable: export OPENAI_API_KEY='your-key'\n"
            "  2. Pass explicitly via api_key parameter"
        )

    model_name = model or config.SOCIAL_LLM_MODEL
    client = _load_openai_client(api_key)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a concise, creative copywriter for TikTok, YouTube Shorts, "
                "and Instagram Reels. Given a transcript, produce engaging titles "
                "and descriptions. Keep titles punchy, include up to 8 hashtags in "
                "descriptions, and respond ONLY with JSON matching this schema:\n"
                '{ "tiktok": {"title": "...", "description": "..."}, '
                '"youtube_shorts": {"title": "...", "description": "..."}, '
                '"instagram": {"title": "...", "description": "..."} }'
            ),
        },
        {"role": "user", "content": transcript_text.strip()},
    ]

    # Simple retry mechanism (1 retry)
    max_retries = 1
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")

            cleaned_content = _clean_json_response(content)
            parsed = json.loads(cleaned_content)

            return SocialCopy(
                tiktok=PlatformCopy(
                    title=parsed["tiktok"]["title"], description=parsed["tiktok"]["description"]
                ),
                youtube_shorts=PlatformCopy(
                    title=parsed["youtube_shorts"]["title"],
                    description=parsed["youtube_shorts"]["description"],
                ),
                instagram=PlatformCopy(
                    title=parsed["instagram"]["title"],
                    description=parsed["instagram"]["description"],
                ),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            last_exc = exc
            if attempt < max_retries:
                continue

    raise ValueError("Failed to generate valid social copy after retries") from last_exc  # pragma: no cover


def generate_viral_metadata(
    transcript_text: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.7,
) -> ViralMetadata:
    """
    Generate viral TikTok metadata (hooks, caption, hashtags) using a specific Greek persona.
    """

    if not api_key:
        api_key = _resolve_openai_api_key()

    if not api_key:
        raise RuntimeError("OpenAI API key is required for Viral Intelligence.")

    model_name = model or config.SOCIAL_LLM_MODEL
    client = _load_openai_client(api_key)

    system_prompt = (
        "### ROLE\n"
        "You are an expert Greek Social Media Manager and Content Creator specialized in TikTok growth. "
        "You understand the Greek digital landscape, current slang, and the TikTok algorithm's preference for high-retention \"hooks.\"\n\n"
        "### INPUT\n"
        "You will receive a raw text transcription (from OpenAI Whisper) of a video in Greek.\n"
        "Note: The text may lack punctuation, contain run-on sentences, or have minor transcription errors.\n\n"
        "### TASK\n"
        "Your goal is to analyze the transcript and generate the perfect TikTok metadata to maximize views and engagement.\n\n"
        "### OUTPUT FORMAT\n"
        "You must respond ONLY with a VALID JSON object using the following structure:\n"
        "{\n"
        '  "hooks": ["Option 1", "Option 2", "Option 3"],\n'
        '  "caption_hook": "Strong hook expanding on title",\n'
        '  "caption_body": "Brief summary with emojis",\n'
        '  "cta": "Call to action question",\n'
        '  "hashtags": ["#tag1", "#tag2", ...]\n'
        "}\n\n"
        "### TONE GUIDELINES\n"
        "* Language: Modern Greek (Demotic).\n"
        "* Style: Casual, energetic, and authentic to TikTok. Avoid formal/robotic Greek.\n"
        "* Formatting: Use line breaks in the body if needed (encoded as \\n)."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript_text.strip()},
    ]

    max_retries = 1
    last_exc = None

    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from LLM")

            parsed = json.loads(content)

            return ViralMetadata(
                hooks=parsed["hooks"],
                caption_hook=parsed["caption_hook"],
                caption_body=parsed["caption_body"],
                cta=parsed["cta"],
                hashtags=parsed["hashtags"],
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            last_exc = exc
            if attempt < max_retries:
                continue

    raise ValueError("Failed to generate viral metadata after retries") from last_exc
