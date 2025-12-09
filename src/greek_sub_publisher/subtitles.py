"""Subtitle generation and styling helpers."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence, Tuple
import unicodedata
import textwrap
import functools

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


@functools.lru_cache(maxsize=8)
def _get_whisper_model_cached(
    model_size: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
) -> WhisperModel:  # pragma: no cover
    """Cache Whisper models across runs to avoid reload overhead."""
    model = WhisperModel(
        model_size,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )
    setattr(model, "_compute_type", compute_type)
    return model


def _get_whisper_model(
    model_size: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
) -> WhisperModel:  # pragma: no cover
    """
    Load a Whisper model with graceful fallback when fp16 is unsupported.
    """
    # Try the requested compute_type first, then fall back for fp16 issues.
    candidates: list[str] = [compute_type]
    if compute_type in ("float16", "auto", "int8_float16"):
        for ct in ("int8_float16", "int8", "float32"):
            if ct not in candidates:
                candidates.append(ct)
    else:
        for ct in ("int8", "float32"):
            if ct not in candidates:
                candidates.append(ct)

    last_exc: Exception | None = None
    for ct in candidates:
        try:
            return _get_whisper_model_cached(model_size, device, ct, cpu_threads)
        except (RuntimeError, ValueError) as exc:
            last_exc = exc
            # Only continue on fp16-related failures; otherwise surface error.
            msg = str(exc).lower()
            if "float16" in msg or "fp16" in msg or "int8_float16" in msg or "compute type" in msg:
                continue
            raise

    assert last_exc is not None
    raise last_exc


def generate_subtitles_from_audio(
    audio_path: Path,
    model_size: str = config.WHISPER_MODEL_SIZE,
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
    Transcribe Greek speech to an SRT subtitle file using faster-whisper.

    Returns the path to the SRT file and the structured cues (with word timings
    when available) to support karaoke-style highlighting.
    """
    if not language or language.lower() == "auto":
        language = config.WHISPER_LANGUAGE

    wants_openai = provider == "openai" or _model_uses_openai(model_size)
    output_dir = output_dir or Path(tempfile.mkdtemp())
    output_dir.mkdir(parents=True, exist_ok=True)

    if wants_openai:
        return _transcribe_with_openai(
            audio_path,
            model_name=model_size or config.OPENAI_TRANSCRIBE_MODEL,
            language=language,
            prompt=initial_prompt,
            output_dir=output_dir,
            progress_callback=progress_callback,
            api_key=openai_api_key,
        )
    
    # Optimize CPU threads: Use all available cores (capped at 8 to avoid overhead)
    threads = min(8, os.cpu_count() or 4)
    
    # Cache models to avoid reloads between runs
    model = _get_whisper_model(
        model_size,
        device=device,
        compute_type=compute_type,
        cpu_threads=threads,
    )
    
    transcribe_kwargs = {
        "language": language or config.WHISPER_LANGUAGE,
        "task": "transcribe",
        "word_timestamps": True,
        "vad_filter": vad_filter,
        "vad_parameters": vad_parameters or dict(min_silence_duration_ms=700),
        "condition_on_previous_text": condition_on_previous_text,
    }
    if beam_size is not None:
        transcribe_kwargs["beam_size"] = beam_size
    if best_of is not None:
        transcribe_kwargs["best_of"] = best_of
    if temperature is not None:
        transcribe_kwargs["temperature"] = temperature
    if chunk_length is not None:
        transcribe_kwargs["chunk_length"] = chunk_length
    if initial_prompt:
        transcribe_kwargs["initial_prompt"] = initial_prompt

    segments_iter, _ = model.transcribe(str(audio_path), **transcribe_kwargs)

    cues: List[Cue] = []
    timed_text: List[TimeRange] = []
    
    # Iterate over segments to track progress
    for seg in segments_iter:
        timed_text.append((seg.start, seg.end, seg.text))
        words: Optional[List[WordTiming]] = None
        if getattr(seg, "words", None):
            words = [
                WordTiming(start=w.start, end=w.end, text=_normalize_text(w.word))
                for w in seg.words
            ]
        cue_text = _normalize_text(seg.text)
        cues.append(Cue(start=seg.start, end=seg.end, text=cue_text, words=words))
        
        if progress_callback and total_duration and total_duration > 0:
            # Calculate progress based on the end time of the current segment
            progress = min(100.0, (seg.end / total_duration) * 100.0)
            progress_callback(progress)

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


def _wrap_lines(words: List[str], max_chars: int = config.MAX_SUB_LINE_CHARS) -> List[List[str]]:
    """
    Wrap words into multiple lines without overflowing the safe width.

    Returns a list of lines (each line is a list of words). The number of lines
    is flexible (2-3 typical) but each line stays within the configured width.
    """
    if not words:
        return []

    text = " ".join(words)
    wrapped = textwrap.wrap(
        text,
        width=max_chars,
        break_long_words=True,
        break_on_hyphens=False,
        drop_whitespace=True,
    )
    if not wrapped:
        return [words]
    return [line.split() for line in wrapped]


def _format_karaoke_text(cue: Cue) -> str:
    """
    Build ASS karaoke text with per-word highlighting. If word timings are not
    available, falls back to plain text with simple 2-line wrapping.
    """
    if cue.words:
        word_texts = [w.text for w in cue.words]
        wrapped_lines = _wrap_lines(word_texts, max_chars=config.MAX_SUB_LINE_CHARS)
        break_indices: List[int] = []
        running_total = 0
        for line_words in wrapped_lines[:-1]:
            running_total += len(line_words)
            break_indices.append(running_total)
        words = cue.words
        segments = []
        for idx, word in enumerate(words):
            duration_cs = max(1, round((word.end - word.start) * 100))
            # Standard ASS karaoke: \k fills from Secondary to Primary color
            token = f"{{\\k{duration_cs}}}{word.text}"
            # insert line break before second line
            if break_indices and idx == break_indices[0]:
                segments.append("\\N")
                break_indices.pop(0)
            segments.append(token)
            if idx != len(words) - 1:
                segments.append(" ")
        return "".join(segments)

    # Fallback: no word timings, static text wrapped to two lines
    raw_words = cue.text.split()
    wrapped_lines = _wrap_lines(raw_words, max_chars=config.MAX_SUB_LINE_CHARS)
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
                hooks=parsed.get("hooks", []),
                caption_hook=parsed.get("caption_hook", ""),
                caption_body=parsed.get("caption_body", ""),
                cta=parsed.get("cta", ""),
                hashtags=parsed.get("hashtags", []),
            )
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            last_exc = exc
            if attempt < max_retries:
                continue
    
    raise ValueError("Failed to generate viral metadata") from last_exc


def _resolve_openai_api_key(explicit: str | None = None) -> str | None:
    """
    Resolve an OpenAI key from (in order):
    1. Explicit argument
    2. Environment variable
    3. secrets.toml (unless GSP_USE_FILE_SECRETS=0)
    """
    if explicit:
        return explicit

    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key

    if os.getenv("GSP_USE_FILE_SECRETS", "1") == "0":
        return None

    search_paths: list[Path] = []
    override = os.getenv("GSP_SECRETS_FILE")
    if override:
        search_paths.append(Path(override))
    
    # 1. Project root (source)
    search_paths.append(config.PROJECT_ROOT.parent.parent / "config" / "secrets.toml")
    # 2. Current working directory (deployment/venv)
    search_paths.append(Path.cwd() / "config" / "secrets.toml")

    for path in search_paths:
        try:
            if not path.exists():
                continue
            data = tomllib.loads(path.read_text())
            if "OPENAI_API_KEY" in data:
                return str(data["OPENAI_API_KEY"])
        except Exception:
            continue
    return None


def _model_uses_openai(model_size: str | None) -> bool:
    """Detect whether the requested model should use hosted OpenAI STT."""
    if not model_size:
        return False
    lowered = model_size.lower()
    return (
        lowered.startswith("openai/")
        or lowered.startswith("gpt-4o")
        or lowered == "whisper-1"
        or "transcribe" in lowered
    )


def should_use_openai(model_size: str | None) -> bool:
    """Public helper for deciding whether to route STT through OpenAI."""
    return _model_uses_openai(model_size)


def _transcribe_with_openai(
    audio_path: Path,
    *,
    model_name: str | None = None,
    language: str | None = None,
    prompt: str | None = None,
    output_dir: Path,
    progress_callback: Callable[[float], None] | None = None,
    api_key: str | None = None,
) -> tuple[Path, List[Cue]]:
    """
    Transcribe audio using OpenAI's hosted models and return SRT + cues.
    """
    client = _load_openai_client(api_key)
    resolved_model = model_name or config.OPENAI_TRANSCRIBE_MODEL
    lang = language or config.WHISPER_LANGUAGE

    if progress_callback:
        progress_callback(10.0)

    guard_prompt = (
        "Transcribe only Greek speech. Do not translate to English. "
        "Keep original Greek words and casing; no summaries."
    )
    composed_prompt = f"{(prompt or '').strip()}\n{guard_prompt}".strip()

    # Determine response format based on model capabilities
    # Only whisper-1 is known to support verbose_json for timing information
    # Newer gpt-4o-transcribe models only support json/text
    # For OpenAI, only whisper-1 supports verbose format for karaoke
    models_supporting_verbose = {"whisper-1"}
    
    # Strip namespace prefix if present (e.g. "openai/whisper-1" -> "whisper-1")
    if resolved_model and resolved_model.startswith("openai/"):
        resolved_model = resolved_model.replace("openai/", "")
        
    use_verbose_format = resolved_model in models_supporting_verbose
    response_format = "verbose_json" if use_verbose_format else "json"

    with audio_path.open("rb") as audio_file:
        transcription_kwargs = {
            "model": resolved_model,
            "file": audio_file,
            "language": lang,
            "response_format": response_format,
            "temperature": 0.0,
            "prompt": composed_prompt or None,
        }
        
        # Explicitly request word-level timestamps for karaoke support
        # This is required for whisper-1 to return "words" in verbose_json
        if use_verbose_format:
            transcription_kwargs["timestamp_granularities"] = ["word"]
        
        # DEBUG: Write call details to file
        try:
             debug_path = config.PROJECT_ROOT.parent / "debug_openai.txt"
             with debug_path.open("w") as f:
                 f.write(f"Model: {resolved_model}\nFormat: {response_format}\nVerbose: {use_verbose_format}\n")
                 f.write(f"Kwargs: {transcription_kwargs}\n")
        except Exception:
             pass

        response = client.audio.transcriptions.create(**transcription_kwargs)

    # Handle different response formats
    timed_text: list[TimeRange] = []
    cues: list[Cue] = []

    if use_verbose_format:
        # verbose_json format provides segments with timing
        segments = getattr(response, "segments", None) or []
        
        # Also try to get words directly if available (granular timestamps)
        all_words = getattr(response, "words", None) or []
        
        if segments:
            for seg in segments:
                # Handle both dict and object attribute access
                if hasattr(seg, 'get'):  # dict-like
                    start = float(seg.get("start", 0.0))
                    end = float(seg.get("end", start + 0.6))
                    text = _normalize_text(seg.get("text", ""))
                else:  # object with attributes
                    start = float(getattr(seg, "start", 0.0))
                    end = float(getattr(seg, "end", start + 0.6))
                    text = _normalize_text(getattr(seg, "text", ""))
                
                # Assign words to this segment if available
                segment_words = None
                if all_words:
                    # Filter words that fall within this segment's time range
                    current_words = []
                    for w in all_words:
                        w_start = float(w.get("start", 0.0) if hasattr(w, "get") else getattr(w, "start", 0.0))
                        w_end = float(w.get("end", 0.0) if hasattr(w, "get") else getattr(w, "end", 0.0))
                        w_text = _normalize_text(w.get("word", "") if hasattr(w, "get") else getattr(w, "word", ""))
                        
                        # Match word to segment with slight tolerance
                        if w_start >= start - 0.1 and w_end <= end + 0.1:
                            current_words.append(WordTiming(start=w_start, end=w_end, text=w_text))
                    
                    if current_words:
                        segment_words = current_words

                timed_text.append((start, end, text))
                cues.append(Cue(start=start, end=end, text=text, words=segment_words))
        else:
            # Fallback if no segments despite verbose format
            # If we have words (e.g. valid OpenAI response for short audio), use them!
            text = _normalize_text(getattr(response, "text", ""))
            
            if all_words:
                 converted_words = []
                 for w in all_words:
                      w_start = float(w.get("start", 0.0) if hasattr(w, "get") else getattr(w, "start", 0.0))
                      w_end = float(w.get("end", 0.0) if hasattr(w, "get") else getattr(w, "end", 0.0))
                      w_text = _normalize_text(w.get("word", "") if hasattr(w, "get") else getattr(w, "word", ""))
                      converted_words.append(WordTiming(start=w_start, end=w_end, text=w_text))
                 
                 if converted_words:
                     start_time = converted_words[0].start
                     end_time = converted_words[-1].end
                     # Ensure meaningful duration
                     if end_time <= start_time:
                         end_time = start_time + max(1.0, len(text.split()) * 0.45)
                     
                     cues.append(Cue(start=start_time, end=end_time, text=text, words=converted_words))
                     timed_text.append((start_time, end_time, text))
            else:
                 duration = max(1.0, len(text.split()) * 0.45)
                 timed_text.append((0.0, duration, text))
                 cues.append(Cue(start=0.0, end=duration, text=text, words=None))
    else:
        # json/text format - no word-level timing available, karaoke disabled
        text = _normalize_text(getattr(response, "text", ""))
        if text:
            # Simple timing estimation: ~150 words per minute = ~0.4 seconds per word
            words = text.split()
            duration = max(1.0, len(words) * 0.4)
            timed_text.append((0.0, duration, text))
            # No karaoke timing available - words=None disables karaoke highlighting
            cues.append(Cue(start=0.0, end=duration, text=text, words=None))
        else:  # pragma: no cover - defensive guard
            raise ValueError("OpenAI transcription returned no text")

    output_dir.mkdir(parents=True, exist_ok=True)
    srt_path = output_dir / f"{audio_path.stem}.srt"
    _write_srt_from_segments(timed_text, srt_path)

    if progress_callback:
        progress_callback(100.0)

    return srt_path, cues
