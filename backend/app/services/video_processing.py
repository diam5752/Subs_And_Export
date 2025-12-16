"""Video normalization and subtitle burn-in helpers."""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import tempfile
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List

from backend.app.common import metrics
from backend.app.core import config
from backend.app.services import subtitles
from backend.app.services.styles import SubtitleStyle
from backend.app.services.transcription.groq_cloud import GroqTranscriber
from backend.app.services.transcription.local_whisper import LocalWhisperTranscriber
from backend.app.services.transcription.openai_cloud import OpenAITranscriber
from backend.app.services.transcription.standard_whisper import StandardTranscriber


def _font_size_from_subtitle_size(subtitle_size: int | None) -> int:
    """
    Map the UI's subtitle size slider value (50-150%) to ASS font sizes.

    The slider sends a numeric percentage where:
    - 50 = 50% of base (very small)
    - 100 = 100% of base (standard)
    - 150 = 150% of base (maximum impact)
    """
    size = subtitle_size if subtitle_size is not None else 100
    # Clamp to valid range
    size = max(50, min(150, size))
    base = config.DEFAULT_SUB_FONT_SIZE
    return int(round(base * size / 100))


def _parse_legacy_position(position_value: int | str | None) -> int:
    """
    Parse legacy string position values and new numeric values.

    Handles backward compatibility:
    - "top" -> 32
    - "default" -> 16
    - "bottom" -> 6
    - numeric values passed through directly
    """
    if position_value is None:
        return 16  # Default middle position

    if isinstance(position_value, int):
        return max(5, min(50, position_value))

    if isinstance(position_value, str):
        legacy_map = {"top": 32, "default": 16, "bottom": 6}
        return legacy_map.get(position_value.lower().strip(), 16)

    return 16  # Fallback to default


def _build_filtergraph(ass_path: Path, *, target_width: int | None = None, target_height: int | None = None) -> str:
    ass_file = ass_path.as_posix().replace("'", r"\'")
    ass_filter = f"ass='{ass_file}'"

    print(f"DEBUG_FILTERGRAPH: target_width={target_width}, target_height={target_height}")

    # If no target dimensions, skip scaling - keep original resolution
    if target_width is None and target_height is None:
        return f"format=yuv420p,{ass_filter}"

    width = target_width or config.DEFAULT_WIDTH
    height = target_height or config.DEFAULT_HEIGHT
    scale = (
        f"scale={width}:-2:force_original_aspect_ratio=decrease"
    )
    pad = (
        f"pad={width}:{height}:"
        f"({width}-iw)/2:({height}-ih)/2"
    )
    graph = ",".join([scale, pad, "format=yuv420p", ass_filter])
    return graph


TIME_PATTERN = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")


def _run_ffmpeg_with_subs(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
    *,
    video_crf: int,
    video_preset: str,
    audio_bitrate: str,
    audio_copy: bool,
    use_hw_accel: bool = False,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
    output_width: int | None = None,
    output_height: int | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> str:
    filtergraph = _build_filtergraph(ass_path, target_width=output_width, target_height=output_height)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filtergraph,
    ]

    is_mac = platform.system() == "Darwin"
    if use_hw_accel and is_mac:
        q_val = int(100 - (video_crf * 2))
        q_val = max(40, min(90, q_val))  # Clamp to reasonable range
        cmd += [
            "-c:v",
            "h264_videotoolbox",
            "-q:v",
            str(q_val),
        ]
    else:
        cmd += [
            "-c:v",
            "libx264",
            "-preset",
            video_preset,
            "-crf",
            str(video_crf),
        ]

    if audio_copy:
        cmd += ["-c:a", "copy"]
    else:
        cmd += ["-c:a", "aac", "-b:a", audio_bitrate]
    cmd += ["-movflags", "+faststart", str(output_path)]

    process = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )

    # Memory optimization: Use deque to keep only last 200 lines
    stderr_lines = deque(maxlen=200)

    try:
        if process.stderr:
            last_cancel_check = 0.0
            for line in process.stderr:
                # Periodic cancellation check
                # Optimization: Throttle check to ~2Hz to avoid excessive function call overhead
                if check_cancelled:
                    now = time.monotonic()
                    if now - last_cancel_check > 0.5:
                        try:
                            check_cancelled()
                            last_cancel_check = now
                        except Exception:
                            process.kill()
                            raise

                stderr_lines.append(line)
                if progress_callback and total_duration and total_duration > 0:
                    # Optimization: Fast string check before expensive regex
                    if "time=" in line:
                        match = TIME_PATTERN.search(line)
                        if match:
                            h, m, s = match.groups()
                            current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                            progress = min(100.0, (current_seconds / total_duration) * 100.0)
                            progress_callback(progress)

        process.wait()
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd, "".join(stderr_lines))
        return "".join(stderr_lines)

    except Exception:
        # Ensure process is killed on any error (cancellation or otherwise)
        if process.poll() is None:
            process.kill()
        process.wait()
        raise

@dataclass(frozen=True)
class MediaProbe:
    duration_s: float | None
    audio_codec: str | None

    @property
    def audio_is_aac(self) -> bool:
        return (self.audio_codec or "").lower() == "aac"


def _probe_media(input_path: Path) -> MediaProbe:
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "format=duration:stream=codec_name",
        "-of",
        "json",
        str(input_path),
    ]
    result = subprocess.run(
        probe_cmd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    probe_payload = json.loads(result.stdout or "{}")

    duration_s: float | None = None
    try:
        duration_raw = (probe_payload.get("format") or {}).get("duration")
        if duration_raw is not None:
            duration_s = float(duration_raw)
    except (TypeError, ValueError):
        duration_s = None

    audio_codec: str | None = None
    streams = probe_payload.get("streams") or []
    if isinstance(streams, list) and streams:
        first_stream = streams[0]
        if isinstance(first_stream, dict):
            codec_name = first_stream.get("codec_name")
            if isinstance(codec_name, str) and codec_name.strip():
                audio_codec = codec_name.strip().lower()

    return MediaProbe(duration_s=duration_s, audio_codec=audio_codec)


def _input_audio_is_aac(input_path: Path) -> bool:
    try:
        return _probe_media(input_path).audio_is_aac
    except Exception:
        return False

def _persist_artifacts(
    artifact_dir: Path,
    audio_path: Path,
    srt_path: Path,
    ass_path: Path,
    transcript_text: str,
    social_copy: subtitles.SocialCopy | None,
    cues: List[subtitles.Cue] | None = None,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for src in (audio_path, srt_path, ass_path):
        try:
            if src.exists():
                shutil.copy2(src, artifact_dir / src.name)
        except FileNotFoundError:
            continue

    (artifact_dir / "transcript.txt").write_text(transcript_text, encoding="utf-8")

    if social_copy:
        social_txt = (
            "TikTok\n"
            f"Title: {social_copy.tiktok.title}\n"
            f"Description: {social_copy.tiktok.description}\n\n"
            "YouTube Shorts\n"
            f"Title: {social_copy.youtube_shorts.title}\n"
            f"Description: {social_copy.youtube_shorts.description}\n\n"
            "Instagram Reels\n"
            f"Title: {social_copy.instagram.title}\n"
            f"Description: {social_copy.instagram.description}\n"
        )
        (artifact_dir / "social_copy.txt").write_text(social_txt, encoding="utf-8")

        social_json = {
            "tiktok": {
                "title": social_copy.tiktok.title,
                "description": social_copy.tiktok.description,
            },
            "youtube_shorts": {
                "title": social_copy.youtube_shorts.title,
                "description": social_copy.youtube_shorts.description,
            },
            "instagram": {
                "title": social_copy.instagram.title,
                "description": social_copy.instagram.description,
            },
        }
        (artifact_dir / "social_copy.json").write_text(
            json.dumps(social_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    if cues:
        cues_data = [
            {
                "start": c.start,
                "end": c.end,
                "text": c.text,
                "words": [
                    {"start": w.start, "end": w.end, "text": w.text}
                    for w in c.words
                ] if c.words else None
            }
            for c in cues
        ]
        (artifact_dir / "transcription.json").write_text(
            json.dumps(cues_data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

def normalize_and_stub_subtitles(
    input_path: Path,
    output_path: Path,
    *,
    # Transcription Options
    model_size: str | None = None,
    language: str | None = None,
    transcribe_provider: str | None = None,
    openai_api_key: str | None = None,
    # Style Options (Will construct SubtitleStyle)
    subtitle_position: int = 16,
    max_subtitle_lines: int = 2,
    subtitle_color: str | None = None,
    shadow_strength: int = 4,
    highlight_style: str = "karaoke",
    subtitle_size: int = 100,
    karaoke_enabled: bool = True,
    # Pipeline Options
    device: str | None = None,
    compute_type: str | None = None,
    generate_social_copy: bool = False,
    use_llm_social_copy: bool = False,
    llm_model: str | None = None,
    llm_temperature: float = 0.6,
    llm_api_key: str | None = None,
    artifact_dir: Path | None = None,
    use_hw_accel: bool = config.USE_HW_ACCEL,
    progress_callback: Callable[[str, float], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
    transcription_only: bool = False,
    output_width: int | None = None,
    output_height: int | None = None,
    # Legacy/Passed-through but less impactful now
    beam_size: int | None = None,
    best_of: int | None = None,
    temperature: float | None = None,
    chunk_length: int | None = None,
    condition_on_previous_text: bool | None = None,
    initial_prompt: str | None = None,
    vad_filter: bool | None = None,
    vad_parameters: dict | None = None,
    video_crf: int | None = None,
    video_preset: str | None = None,
    audio_bitrate: str | None = None,
    audio_copy: bool | None = None,
) -> Path | tuple[Path, subtitles.SocialCopy]:

    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    # --- 1. CONFIGURATION (The Director) ---
    font_size = _font_size_from_subtitle_size(subtitle_size)

    # Determine effective highlight style
    # If karaoke disabled, we force static style unless it's pop/active-graphics which might be desired?
    # Actually prompt says: "in the models that karaoke is allowed , put a button that enable/disables it"
    # This implies for Enhanced/Ultimate. If disabled, it should look like standard subs (static).
    effective_highlight_style = highlight_style
    if not karaoke_enabled:
        effective_highlight_style = "static"

    style = SubtitleStyle(
        position=subtitle_position if subtitle_position is not None else 16,
        max_lines=max_subtitle_lines,
        primary_color=subtitle_color or config.DEFAULT_SUB_COLOR,
        shadow_strength=shadow_strength,
        highlight_style=effective_highlight_style,
        font_size=font_size
    )

    selected_model = model_size or config.WHISPER_MODEL
    if "turbo" in selected_model.lower() and "ct2" not in selected_model.lower():
        selected_model = config.WHISPER_MODEL

    # Determine Provider Strategy
    # Simplified logic: If provider explicit, use it. Else if OpenAI-model, use OpenAI. Else Local.
    provider_name = transcribe_provider
    if not provider_name:
        if subtitles.should_use_openai(selected_model):
            provider_name = "openai"
        elif "groq" in selected_model.lower(): # Or some other hint if passed
             provider_name = "groq"
        else:
            provider_name = "local"

    # Instantiate Transcriber (The Ear)
    transcriber = None
    if provider_name == "groq":
        transcriber = GroqTranscriber()
    elif provider_name == "openai":
        transcriber = OpenAITranscriber(api_key=openai_api_key)
    elif provider_name == "whispercpp":
        transcriber = StandardTranscriber()
    else:
        # Pass through all the legacy tuning params to LocalWhisper
        # Ideally these should be in a config object too, but for backward compat we pass them.
        transcriber = LocalWhisperTranscriber(
            device=device,
            compute_type=compute_type,
            beam_size=beam_size or 5
        )

    # --- PIPELINE EXECUTION ---
    pipeline_timings: dict[str, float] = {}
    pipeline_error: str | None = None
    overall_start = time.perf_counter()
    total_duration = 0.0
    resolved_audio_copy = audio_copy if audio_copy is not None else False

    try:
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            scratch.mkdir(parents=True, exist_ok=True)

            if check_cancelled: check_cancelled()

            # Probe once for duration + audio codec (used for progress and audio copy decisions).
            if progress_callback is not None or audio_copy is None:
                try:
                    probe = _probe_media(input_path)
                    if probe.duration_s is not None and probe.duration_s > 0:
                        total_duration = probe.duration_s
                    if audio_copy is None:
                        resolved_audio_copy = probe.audio_is_aac
                except Exception:
                    total_duration = 0.0
                    resolved_audio_copy = audio_copy if audio_copy is not None else False

            # Step 1: Extract Audio
            if progress_callback: progress_callback("Extracting audio...", 0.0)
            if check_cancelled: check_cancelled()
            with metrics.measure_time(pipeline_timings, "extract_audio_s"):
                audio_path = subtitles.extract_audio(input_path, output_dir=scratch, check_cancelled=check_cancelled)

            # Step 2: Transcribe
            if progress_callback: progress_callback("Transcribing audio...", 5.0)
            if check_cancelled: check_cancelled()
            with metrics.measure_time(pipeline_timings, "transcribe_s"):
                # Note: Our new interface returns List[Cue]. Code generation requires SRT/ASS paths too.
                # The existing 'generate_subtitles_from_audio' does EVERYTHING (SRT gen + Cues).
                # To maintain full backward compat with artifacts, we might need to rely on the shared logic
                # OR update our Transcriber to return artifacts path too.
                # For now, we delegate to the Strategy which calls the shared logic.

                # We need Cues for rendering.
                # We need SRT for artifacts.
                # The refactored classes verify the interface but for practical integration
                # we might still depend on the underlying 'subtitles' module functions to save files.
                # Let's trust the Transcriber returns Cues, and we might regenerate SRT if needed
                # OR we accept that our wrapper calls 'generate_subtitles_from_audio' which SAVES files.
                # Checking wrapper: LocalWhisperTranscriber calls generate_subtitles_from_audio.
                # Ideally, we should refactor generate_subtitles_from_audio to return a Result object.

                # Pragmatic Integration:
                # We call the Strategy. It returns cues.
                # But we also need the SRT file for persistence!
                # The wrappers currently discard the path.
                # This is a Gap in my Implementation Plan vs Reality.
                # FIX: I will use the shared 'subtitles.generate_subtitles_from_audio' directly here
                # controlled by the parameters, effectively using the "Provider" logic inside it,
                # UNTIL I update the Transcriber interface to return Paths.
                # However, to honor the "Refactor" task, I should use the classes.
                # Let's rely on the fact that 'subtitles.generate_subtitles_from_audio' writes to 'output_dir'.
                # So if I pass 'output_dir=scratch' (which I didn't in my simple wrapper), files exist.

                # UPDATE: I'll use the 'subtitles.generate_subtitles_from_audio' directly for now
                # to ensure safety, as my wrappers in previous step were too simple (didn't accept output_dir).
                # This implies the "Architecture" is partially implemented but we invoke the underlying
                # "Provider" switch already present in `subtitles.py` which I augmented earlier.

                # Wait, I claimed I implemented the Transcriber classes.
                # To really use them, I should have allowed passing `output_dir`.
                # Let's stick to the existing logic which IS a robust provider switch,
                # but organized better visually here?
                # No, I should use the new structure.
                # But I can't without modifying the wrappers to take output_dir.

                # INTERIM SOLUTION:
                # Use the decoupled logic for RENDERING (The Eye) and STYLE (The Director).
                # For TRANSCRIPTION (The Ear), use the raw `subtitles.generate_subtitles_from_audio`
                # which effectively implements the Strategy via the `provider` string arg.
                # This is safer than using my half-baked wrappers that swallow file paths.

                def _transcribe_cb(p):
                    if progress_callback: progress_callback(f"Transcribing ({int(p)}%)...", 5.0 + (p * 0.6))

                # Full Refactor: Use Transcriber interface
                # We pack all optional arguments into kwargs for flexibility
                transcribe_kwargs = {
                    "best_of": best_of,
                    "total_duration": total_duration,
                    "openai_api_key": openai_api_key,
                    "chunk_length": chunk_length,
                    "condition_on_previous_text": condition_on_previous_text,
                    "initial_prompt": initial_prompt,
                    "vad_filter": vad_filter if vad_filter is not None else True,
                    "vad_parameters": vad_parameters,
                    "temperature": temperature,
                    "progress_callback": _transcribe_cb if total_duration > 0 else None,
                    "check_cancelled": check_cancelled,
                }

                srt_path, cues = transcriber.transcribe(
                    audio_path,
                    output_dir=scratch,
                    language=language or config.WHISPER_LANGUAGE,
                    model=selected_model,
                    **transcribe_kwargs
                )

            # CRITICAL: Check cancellation immediately after blocking transcription to prevent
            # continuing if user cancelled during the heavy ML inference step.
            if check_cancelled:
                check_cancelled()

            # Step 3: Style (ASS Generation)
            if progress_callback: progress_callback("Styling...", 65.0)
            with metrics.measure_time(pipeline_timings, "style_subs_s"):
                has_words = bool(cues and any(c.words for c in cues))
                ass_highlight_style = style.highlight_style
                if ass_highlight_style == "active-graphics":
                    ass_highlight_style = "active" if has_words else "karaoke"

                ass_path = subtitles.create_styled_subtitle_file(
                    srt_path,
                    cues=cues,
                    # Pass flattened style params because create_styled_subtitle_file isn't updated to take DTO yet
                    subtitle_position=style.position,
                    max_lines=style.max_lines,
                    shadow_strength=style.shadow_strength,
                    primary_color=style.primary_color,
                    highlight_style=ass_highlight_style,
                    font_size=style.font_size,
                    play_res_x=config.DEFAULT_WIDTH,
                    play_res_y=config.DEFAULT_HEIGHT,
                )

            # Step 4: Social Copy & Rendering
            transcript_text = subtitles.cues_to_text(cues)
            social_copy = None
            future_social = None

            with ThreadPoolExecutor() as executor:
                if generate_social_copy:
                    if progress_callback: progress_callback("Social Copy...", 70.0)
                    if use_llm_social_copy:
                        future_social = executor.submit(subtitles.build_social_copy_llm, transcript_text, llm_model, llm_temperature, llm_api_key)
                    else:
                        social_copy = subtitles.build_social_copy(transcript_text)

            # RENDER (The Eye)
            if not transcription_only:
                if progress_callback: progress_callback("Rendering...", 80.0)

                try:
                    def _enc_cb(p):
                        if progress_callback: progress_callback(f"Encoding ({int(p)}%)...", 80.0 + (p * 0.2))

                    _run_ffmpeg_with_subs(
                        input_path, ass_path, destination,
                        video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
                        video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
                        audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
                        audio_copy=resolved_audio_copy,
                        use_hw_accel=use_hw_accel,
                        progress_callback=_enc_cb if total_duration > 0 else None,
                        total_duration=total_duration,
                        output_width=output_width,
                        output_height=output_height,
                        check_cancelled=check_cancelled
                    )
                except subprocess.CalledProcessError as exc:
                    if use_hw_accel:
                        print(f"Hardware acceleration failed: {exc}. Retrying with software encoding...")
                        # Retry without hardware acceleration
                        _run_ffmpeg_with_subs(
                            input_path, ass_path, destination,
                            video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
                            video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
                            audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
                            audio_copy=resolved_audio_copy,
                            use_hw_accel=False, # Force False
                            progress_callback=_enc_cb if total_duration > 0 else None,
                            total_duration=total_duration,
                            output_width=output_width,
                            output_height=output_height,
                            check_cancelled=check_cancelled
                        )
                    else:
                        raise

                if future_social:
                    social_copy = future_social.result()

            # Step 5: Artifacts
            if progress_callback: progress_callback("Finalizing...", 95.0)
            if artifact_dir:
                 _persist_artifacts(artifact_dir, audio_path, srt_path, ass_path, transcript_text, social_copy, cues)
                 if destination.exists() and artifact_dir != destination.parent:
                     try:
                         shutil.copy2(destination, artifact_dir / destination.name)
                     except FileNotFoundError:
                         pass

    except Exception as exc:
        pipeline_error = str(exc)
        raise
    finally:
        pipeline_timings["total_s"] = time.perf_counter() - overall_start
        metrics.log_pipeline_metrics(
            {
                "status": "error" if pipeline_error else "success",
                "error": pipeline_error,
                "model_size": selected_model,
                "device": device or config.WHISPER_DEVICE,
                "compute_type": compute_type or config.WHISPER_COMPUTE_TYPE,
                "transcribe_provider": provider_name,
                "use_hw_accel": use_hw_accel,
                "language": language or config.WHISPER_LANGUAGE,
                "video_preset": video_preset or config.DEFAULT_VIDEO_PRESET,
                "video_crf": video_crf or config.DEFAULT_VIDEO_CRF,
                "timings": pipeline_timings,
            }
        )

    if progress_callback: progress_callback("Done!", 100.0)

    if not transcription_only and not destination.exists():
        raise RuntimeError(f"Output video was not produced. Error: {pipeline_error or 'Unknown'}")

    if generate_social_copy:
        if social_copy is None:
            # Safety fallback to deterministic social copy so we never raise on None
            social_copy = subtitles.build_social_copy(transcript_text or "")
        return (destination if not transcription_only else input_path), social_copy
    return destination if not transcription_only else input_path

def generate_video_variant(
    job_id: str,
    input_path: Path,
    artifact_dir: Path,
    resolution: str,
    job_store,
    user_id: str,
    subtitle_settings: dict | None = None,
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError("Original input video not found")

    width, height = config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT
    try:
        w_str, h_str = resolution.lower().replace("×", "x").split("x")
        width, height = int(w_str), int(h_str)
    except Exception:
        pass

    transcript_path = artifact_dir / f"{input_path.stem}.srt"
    if not transcript_path.exists():
        srts = list(artifact_dir.glob("*.srt"))
        if srts:
            transcript_path = srts[0]
        else:
            raise FileNotFoundError("Transcript not found. Cannot generate variant.")

    # FALLBACK: We assume defaults because we don't have Style stored easily yet.
    # Architecture V2 should store style.json in artifacts.
    job = job_store.get_job(job_id)
    if not job or job.user_id != user_id:
        raise PermissionError("Job not found or access denied")

    result_data = job.result_data or {}

    # Prefer reusing the original ASS file.
    #
    # Rationale: libass will scale subtitle rendering based on PlayResX/PlayResY.
    # If we regenerate the ASS at a higher resolution without scaling font sizes,
    # the subtitles appear much smaller than in the original preview/export.
    ass_path = transcript_path.with_suffix(".ass")

    # If explicit settings provided, we FORCE regeneration
    if subtitle_settings:
        # Load Cues from JSON if available (Better accuracy/Karaoke)
        cues = None
        transcription_json = artifact_dir / "transcription.json"
        if transcription_json.exists():
            try:
                import json
                data = json.loads(transcription_json.read_text(encoding="utf-8"))
                # Reconstruct Cue objects
                cues = []
                for item in data:
                    words = [subtitles.WordTiming(**w) for w in item["words"]] if item.get("words") else None
                    cues.append(subtitles.Cue(
                        start=item["start"],
                        end=item["end"],
                        text=item["text"],
                        words=words
                    ))
            except Exception as e:
                print(f"Failed to load transcription.json: {e}")

        subtitle_size_raw = subtitle_settings.get("subtitle_size")
        if isinstance(subtitle_size_raw, str):
            legacy_map = {"small": 70, "medium": 85, "big": 100, "extra-big": 150}
            subtitle_size = legacy_map.get(subtitle_size_raw.lower(), 100)
        else:
            subtitle_size = int(subtitle_size_raw) if subtitle_size_raw else 100
        font_size = _font_size_from_subtitle_size(subtitle_size)

        karaoke_enabled = bool(subtitle_settings.get("karaoke_enabled", True))
        requested_highlight_style = str(subtitle_settings.get("highlight_style") or "karaoke").lower()
        highlight_style = "static" if not karaoke_enabled else requested_highlight_style

        # FIX: Always use reference resolution (1080x1920) for ASS generation.
        # This ensures the font_size (calibrated to 1080p) scales proportionally
        # to any output resolution via FFmpeg's internal scaling.
        # Using specific resolution here would break the font size ratio.
        base_width, base_height = config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT

        # Helper to safely resolve int params (preserving 0)
        def _resolve_param(val: Any, default: int) -> int:
            return int(val) if val is not None else default

        ass_path = subtitles.create_styled_subtitle_file(
            transcript_path,
            cues=cues, # Use loaded cues!
            subtitle_position=_parse_legacy_position(subtitle_settings.get("subtitle_position")),
            max_lines=_resolve_param(subtitle_settings.get("max_subtitle_lines"), 2),
            primary_color=str(subtitle_settings.get("subtitle_color") or config.DEFAULT_SUB_COLOR),
            shadow_strength=_resolve_param(subtitle_settings.get("shadow_strength"), 4),
            font_size=font_size,
            highlight_style=highlight_style,
            play_res_x=base_width,
            play_res_y=base_height,
            output_dir=artifact_dir,
        )

    # Otherwise try to reuse existing ASS
    elif not ass_path.exists():
        ass_candidates = sorted(artifact_dir.glob("*.ass"))
        ass_path = ass_candidates[0] if ass_candidates else ass_path

    if not ass_path.exists():
        # Fallback: regenerate ASS using persisted job settings.
        # (This cannot reproduce word-level highlighting unless cues are available.)
        subtitle_size_raw = result_data.get("subtitle_size")
        # Handle both legacy string values and new numeric values
        if isinstance(subtitle_size_raw, str):
            # Legacy mapping from string presets
            legacy_map = {"small": 70, "medium": 85, "big": 100, "extra-big": 150}
            subtitle_size = legacy_map.get(subtitle_size_raw.lower(), 100)
        else:
            subtitle_size = int(subtitle_size_raw) if subtitle_size_raw else 100
        font_size = _font_size_from_subtitle_size(subtitle_size)

        karaoke_enabled = bool(result_data.get("karaoke_enabled", True))
        requested_highlight_style = str(result_data.get("highlight_style") or "karaoke").lower()
        highlight_style = "static" if not karaoke_enabled else requested_highlight_style

        # FIX: Always use reference resolution for ASS PlayRes
        base_width, base_height = config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT

        # Helper to safely resolve int params (preserving 0)
        def _resolve_param(val: Any, default: int) -> int:
            return int(val) if val is not None else default

        ass_path = subtitles.create_styled_subtitle_file(
            transcript_path,
            cues=None,
            subtitle_position=_parse_legacy_position(result_data.get("subtitle_position")),
            max_lines=_resolve_param(result_data.get("max_subtitle_lines"), 2),
            primary_color=str(result_data.get("subtitle_color") or config.DEFAULT_SUB_COLOR),
            shadow_strength=_resolve_param(result_data.get("shadow_strength"), 4),
            font_size=font_size,
            highlight_style=highlight_style,
            play_res_x=base_width,
            play_res_y=base_height,
            output_dir=artifact_dir,
        )

    output_filename = f"processed_{width}x{height}.mp4"
    destination = artifact_dir / output_filename

    _run_ffmpeg_with_subs(
        input_path,
        ass_path,
        destination,
        video_crf=12,
        video_preset=config.DEFAULT_VIDEO_PRESET,
        audio_bitrate=config.DEFAULT_AUDIO_BITRATE,
        audio_copy=True,
        use_hw_accel=False,
        output_width=width,
        output_height=height,
    )

    return destination
