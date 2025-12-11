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


def should_use_openai(model_name: str | None) -> bool:
    """Check if the model name implies using OpenAI's API."""
    return model_name is not None and "openai" in model_name.lower()


def _model_uses_openai(model_name: str | None) -> bool:
    """Helper for internal use (alias of should_use_openai)."""
    return should_use_openai(model_name)


def _transcribe_with_openai(
    audio_path: Path,
    model_name: str,
    language: str | None,
    prompt: str | None,
    output_dir: Path,
    progress_callback: Callable[[float], None] | None = None,
    api_key: str | None = None,
) -> Tuple[Path, List[Cue]]:
    """Transcribe audio using OpenAI's API."""
    
    if not api_key:
        api_key = _resolve_openai_api_key()
    
    if not api_key:
        raise RuntimeError(
            "OpenAI API key is required for transcription with 'openai' provider or models."
        )

    client = _load_openai_client(api_key)
    
    # We can't easily track progress with the simple transcription API
    if progress_callback:
        progress_callback(10.0)

    try:
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=model_name or "whisper-1",
                file=audio_file,
                language=language or "el",
                prompt=prompt,
                response_format="verbose_json",
                timestamp_granularities=["word"] # Get word-level timestamps
            )
    except Exception as exc:
        raise RuntimeError(f"OpenAI transcription failed: {exc}") from exc

    if progress_callback:
        progress_callback(90.0)

    # Convert OpenAI verbose_json response to our Cue/WordTiming format
    cues: List[Cue] = []
    timed_text: List[TimeRange] = []
    
    # OpenAI returns segments
    if hasattr(transcript, "segments"):
        for seg in transcript.segments:
            seg_text = seg.text or ""
            seg_start = seg.start
            seg_end = seg.end
            
            # Map words if available (requires timestamp_granularities=['word'])
            # Note: The structure of response depends on library version and params
            # Standard object access:
            current_words: List[WordTiming] = []
            
            # If the top-level transcript has 'words', we need to filter them for this segment
            # OR if the segment has 'words'. OpenAI's verbose_json puts words at top level usually.
            
            # Let's look at transcript.words if available
            all_words = getattr(transcript, "words", [])
            if all_words:
                 # Filter words belonging to this segment time range
                 seg_words_data = [
                     w for w in all_words 
                     if w.start >= seg_start and w.end <= seg_end
                 ]
                 current_words = [
                     WordTiming(start=w.start, end=w.end, text=_normalize_text(w.word))
                     for w in seg_words_data
                 ]
            
            processed_text = _normalize_text(seg_text)
            cues.append(Cue(start=seg_start, end=seg_end, text=processed_text, words=current_words))
            timed_text.append((seg_start, seg_end, seg_text))
            
    if progress_callback:
        progress_callback(100.0)

    srt_path = output_dir / f"{audio_path.stem}.srt"
    _write_srt_from_segments(timed_text, srt_path)
    
    return srt_path, cues


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


def _transcribe_with_groq(
    audio_path: Path,
    model_name: str | None,
    language: str | None,
    prompt: str | None,
    output_dir: Path,
    progress_callback: Callable[[float], None] | None = None,
    api_key: str | None = None,
) -> Tuple[Path, List[Cue]]:
    """Transcribe audio using Groq's Whisper API (OpenAI-compatible)."""
    
    if not api_key:
        api_key = _resolve_groq_api_key()
    
    if not api_key:
        raise RuntimeError(
            "Groq API key is required. Set GROQ_API_KEY env var or add to config/secrets.toml"
        )

    # Groq uses OpenAI-compatible API
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("openai package is required for Groq transcription")
    
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1"
    )
    
    if progress_callback:
        progress_callback(10.0)

    try:
        with open(audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model=model_name or config.GROQ_TRANSCRIBE_MODEL,
                file=audio_file,
                language=language or "el",
                prompt=prompt,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"]
            )
    except Exception as exc:
        raise RuntimeError(f"Groq transcription failed: {exc}") from exc

    if progress_callback:
        progress_callback(90.0)

    # Convert response to our Cue/WordTiming format (same as OpenAI)
    cues: List[Cue] = []
    timed_text: List[TimeRange] = []
    
    if hasattr(transcript, "segments"):
        for seg in transcript.segments:
            seg_text = seg.text or ""
            seg_start = seg.start
            seg_end = seg.end
            
            current_words: List[WordTiming] = []
            all_words = getattr(transcript, "words", [])
            if all_words:
                seg_words_data = [
                    w for w in all_words 
                    if w.start >= seg_start and w.end <= seg_end
                ]
                current_words = [
                    WordTiming(start=w.start, end=w.end, text=_normalize_text(w.word))
                    for w in seg_words_data
                ]
            
            processed_text = _normalize_text(seg_text)
            cues.append(Cue(start=seg_start, end=seg_end, text=processed_text, words=current_words))
            timed_text.append((seg_start, seg_end, seg_text))
            
    if progress_callback:
        progress_callback(100.0)

    srt_path = output_dir / f"{audio_path.stem}.srt"
    _write_srt_from_segments(timed_text, srt_path)
    
    return srt_path, cues


def _transcribe_with_whispercpp(
    audio_path: Path,
    model_name: str | None,
    language: str | None,
    output_dir: Path,
    progress_callback: Callable[[float], None] | None = None,
) -> Tuple[Path, List[Cue]]:
    """Transcribe audio using whisper.cpp with Metal/CoreML acceleration (Apple Silicon optimized).
    
    Uses split_on_word mode to get word-level timing for karaoke effect.
    """
    try:
        from pywhispercpp.model import Model as WhisperCppModel
    except ImportError:
        raise RuntimeError(
            "pywhispercpp not installed. For best performance on Apple Silicon, install with CoreML:\n"
            "WHISPER_COREML=1 pip install git+https://github.com/absadiki/pywhispercpp\n"
            "Or for basic install: pip install pywhispercpp"
        )

    model_size = model_name or config.WHISPERCPP_MODEL
    
    if progress_callback:
        progress_callback(5.0)
    
    # Initialize whisper.cpp model - use normal segment mode for better base timing
    model = WhisperCppModel(
        model_size,
        print_realtime=False,
        print_progress=False,
    )
    
    if progress_callback:
        progress_callback(15.0)

    # Transcribe to get segments with accurate segment-level timing
    segments = model.transcribe(
        str(audio_path),
        language=language or config.WHISPERCPP_LANGUAGE,
        n_threads=min(8, os.cpu_count() or 4),  # Use available threads up to 8
    )

    if progress_callback:
        progress_callback(85.0)

    # Convert segments to Cues WITHOUT word-level timing (Standard model = No Karaoke)
    cues: List[Cue] = []
    timed_text: List[TimeRange] = []
    
    for seg in segments:
        seg_start = seg.t0 / 100.0  # centiseconds to seconds
        seg_end = seg.t1 / 100.0
        seg_text = seg.text.strip()
        
        if not seg_text:
            continue
        
        # Normalize the full segment text
        normalized_text = _normalize_text(seg_text)
        if not normalized_text:
            continue
        
        # Standard model: No word columns, just block text
        cues.append(Cue(start=seg_start, end=seg_end, text=normalized_text, words=None))
        timed_text.append((seg_start, seg_end, seg_text))

    if progress_callback:
        progress_callback(100.0)

    srt_path = output_dir / f"{audio_path.stem}.srt"
    _write_srt_from_segments(timed_text, srt_path)

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
    
    # Route to Groq API
    if provider == "groq":
        return _transcribe_with_groq(
            audio_path,
            model_name=config.GROQ_TRANSCRIBE_MODEL,
            language=language,
            prompt=initial_prompt,
            output_dir=output_dir,
            progress_callback=progress_callback,
            api_key=openai_api_key,
        )
    
    # Route to whisper.cpp (Metal accelerated for Apple Silicon)
    if provider == "whispercpp":
        return _transcribe_with_whispercpp(
            audio_path,
            model_name=config.WHISPERCPP_MODEL,
            language=language,
            output_dir=output_dir,
            progress_callback=progress_callback,
        )
    
    # Default: Local faster-whisper with Turbo model
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
    subtitle_position: str = "default",  # "default", "top", "bottom"
    max_lines: int = 2,
    shadow_strength: int = 4,
    play_res_x: int = config.DEFAULT_WIDTH,
    play_res_y: int = config.DEFAULT_HEIGHT,
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

    # SPLIT LONG CUES FOR ALL MAX_LINES VALUES:
    # If text doesn't fit within max_lines, split into separate subtitle events
    # rather than overflowing to more lines than user selected.
    # 
    # IMPORTANT: _wrap_lines uses "balanced wrapping" which calculates
    # target_width = total_len / max_lines. This can produce MORE lines than
    # expected when textwrap doesn't fill lines optimally.
    # 
    # Example: 54-char cue with max_lines=2 → target_width=27 → but textwrap
    # might produce 3 lines if words don't break evenly.
    #
    # Solution: Use 70% efficiency factor to ensure cues are small enough
    # that balanced wrapping always fits in max_lines.
    # For max_lines=2 and MAX_SUB_LINE_CHARS=32: 32 * 2 * 0.70 = 44.8 ≈ 44 chars
    wrap_efficiency = 0.70  # Aggressive factor to handle balanced wrapping edge cases
    max_chars_per_cue = int(config.MAX_SUB_LINE_CHARS * max_lines * wrap_efficiency)
    parsed_cues = _split_long_cues(parsed_cues, max_chars=max_chars_per_cue)

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
    for cue in parsed_cues:
        text = _format_karaoke_text(cue, max_lines=max_lines)
        lines.append(_format_ass_dialogue(cue.start, cue.end, text))
    ass_path.write_text("\n".join(lines), encoding="utf-8")
    return ass_path


def _split_long_cues(cues: Sequence[Cue], max_chars: int = 40) -> List[Cue]:
    """
    Split long cues into multiple shorter cues based on max_chars.
    Uses word-level timestamps to determine split points and maintain timing accuracy.
    """
    new_cues = []
    
    for cue in cues:
        # If short enough, keep it
        if len(cue.text) <= max_chars:
            new_cues.append(cue)
            continue
            
        # Strategy: Use word timings if available
        if cue.words:
            current_words = []
            current_len = 0
            
            # Group words into chunks <= max_chars
            for w in cue.words:
                w_len = len(w.text) + 1 # +space
                
                # If adding this word exceeds limit, push current chunk as new cue
                if current_words and (current_len + w_len > max_chars):
                    # Create cue from current_words
                    chunk_text = " ".join([cw.text for cw in current_words])
                    chunk_start = current_words[0].start
                    chunk_end = current_words[-1].end
                    
                    new_cues.append(Cue(
                        start=chunk_start,
                        end=chunk_end,
                        text=chunk_text,
                        words=list(current_words)
                    ))
                    
                    # Reset
                    current_words = [w]
                    current_len = w_len
                else:
                    current_words.append(w)
                    current_len += w_len
            
            # Flush final chunk
            if current_words:
                chunk_text = " ".join([cw.text for cw in current_words])
                chunk_start = current_words[0].start
                chunk_end = current_words[-1].end
                
                # Trust the original cue end for the final chunk primarily, 
                # but ensure we don't end before the last word
                chunk_end = max(chunk_end, cue.end)
                
                new_cues.append(Cue(
                    start=chunk_start,
                    end=chunk_end,
                    text=chunk_text,
                    words=list(current_words)
                ))

        else:
            # NO SPLITTING for cues without word timings (e.g., whisper.cpp)
            # Reason: Without word-level timestamps, we cannot accurately split
            # the timing. Any interpolation would be a guess and break audio sync.
            # 
            # Trade-off: Subtitle may exceed max_lines, but timing is accurate.
            # This is better than showing subtitles out of sync with audio.
            new_cues.append(cue)

    return new_cues


def _wrap_lines(
    words: List[str],
    max_chars: int = config.MAX_SUB_LINE_CHARS,
    max_lines: int = 2,
) -> List[List[str]]:
    """
    Wrap words into multiple lines without overflowing the safe width.

    Returns a list of lines (each line is a list of words).
    """
    if not words:
        return []

    # Balanced Wrapping Logic
    # Calculate ideal width to distribute text evenly across max_lines
    import math
    
    # Heuristic: roughly 15 chars min width seems reasonable to avoid single-word lines if possible
    MIN_WIDTH = 15  
    
    # Effective cap: 
    # If 1 line: we allow SLIGHTLY wider text (up to ~42 chars) to try and fit it, but not 60.
    # 60 chars causes overflow on vertical video with this font size.
    # If >1 lines: we strictly follow MAX_SUB_LINE_CHARS (40) to ensure safety.
    # If 1 line: we allow SLIGHTLY wider text (up to ~42 chars) to try and fit it, but not 60.
    # 60 chars causes overflow on vertical video with this font size.
    # If >1 lines: we strictly follow max_chars (40) to ensure safety.
    max_width_cap = int(max_chars * 1.05) if max_lines == 1 else max_chars
    
    # Define text variable early
    text = " ".join(words)
    total_len = len(text)
    
    # Target width per line
    target_width = math.ceil(total_len / max_lines)
    
    effective_width = max(MIN_WIDTH, target_width)
    effective_width = min(effective_width, max_width_cap)
    
    wrapped = textwrap.wrap(
        text,
        width=effective_width,
        break_long_words=True,
        break_on_hyphens=False,
        drop_whitespace=True,
    )

    if not wrapped:
        return [words]
    
    # NO TRUNCATION: We do not enforce max_lines by truncating.
    # For cues without word timings (whisper.cpp), we preserve all text
    # to maintain accurate audio sync. The subtitle may show more lines
    # than max_lines, but this is preferable to losing words or breaking sync.
    
    return [line.split() for line in wrapped]


def _format_karaoke_text(cue: Cue, max_lines: int = 2) -> str:
    """
    Build ASS karaoke text with per-word highlighting. If word timings are not
    available, falls back to plain text with simple multi-line wrapping.
    """
    if cue.words:
        word_texts = [w.text for w in cue.words]
        # Pass max_lines explicitly
        wrapped_lines = _wrap_lines(word_texts, max_chars=config.MAX_SUB_LINE_CHARS, max_lines=max_lines)
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

    # Fallback: no word timings, static text wrapped to max_lines
    raw_words = cue.text.split()
    wrapped_lines = _wrap_lines(raw_words, max_chars=config.MAX_SUB_LINE_CHARS, max_lines=max_lines)
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
