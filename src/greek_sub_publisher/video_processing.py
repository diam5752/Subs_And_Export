"""Video normalization and subtitle burn-in helpers."""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from . import config, subtitles
from . import metrics


def _build_filtergraph(ass_path: Path, *, target_width: int | None = None, target_height: int | None = None) -> str:
    ass_file = ass_path.as_posix().replace("'", r"\'")
    ass_filter = f"ass='{ass_file}'"
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
        # VideoToolbox hardware acceleration
        # Map CRF to roughly equivalent bitrate/quality control if needed.
        # For simplicity, we'll use a high bitrate target or -q:v if supported by the specific encoder wrapper.
        # h264_videotoolbox supports -q:v (0-100).
        # Mapping CRF (0-51, lower is better) to q (0-100, higher is better).
        # CRF 18 ~ q 80, CRF 23 ~ q 65, CRF 28 ~ q 50
        q_val = int(100 - (video_crf * 2))
        q_val = max(40, min(90, q_val))  # Clamp to reasonable range

        cmd += [
            "-c:v",
            "h264_videotoolbox",
            "-q:v",
            str(q_val),
            # -preset is not standard for videotoolbox, but some builds might ignore it.
            # We'll omit it to be safe.
        ]
    else:
        # Software encoding (libx264)
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
    
    # Use Popen to read stderr in real-time for progress
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    
    # Regex to extract time=HH:MM:SS.mm
    time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
    stderr_lines: list[str] = []

    if process.stderr:
        for line in process.stderr:
            stderr_lines.append(line)
            if progress_callback and total_duration and total_duration > 0:
                match = time_pattern.search(line)
                if match:
                    h, m, s = match.groups()
                    current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    progress = min(100.0, (current_seconds / total_duration) * 100.0)
                    progress_callback(progress)
    
    process.wait()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd, "".join(stderr_lines))
    return "".join(stderr_lines)


def _input_audio_is_aac(input_path: Path) -> bool:
    """Return True if the primary audio stream is already AAC."""
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=nokey=1:noprint_wrappers=1",
        str(input_path),
    ]
    try:
        result = subprocess.run(
            probe_cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return "aac" in result.stdout.strip().lower()
    except Exception:
        return False


def _persist_artifacts(
    artifact_dir: Path,
    audio_path: Path,
    srt_path: Path,
    ass_path: Path,
    transcript_text: str,
    social_copy: subtitles.SocialCopy | None,
) -> None:
    """Copy intermediate files and social copy text to a user-visible directory."""
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for src in (audio_path, srt_path, ass_path):
        if src.exists():
            shutil.copy2(src, artifact_dir / src.name)

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


def normalize_and_stub_subtitles(
    input_path: Path,
    output_path: Path,
    *,
    model_size: str | None = None,
    language: str | None = None,
    device: str | None = None,
    compute_type: str | None = None,
    beam_size: int | None = None,
    best_of: int | None = None,
    video_crf: int | None = None,
    video_preset: str | None = None,
    audio_bitrate: str | None = None,
    audio_copy: bool | None = None,
    generate_social_copy: bool = False,
    use_llm_social_copy: bool = False,
    llm_model: str | None = None,
    llm_temperature: float = 0.6,
    llm_api_key: str | None = None,
    artifact_dir: Path | None = None,
    use_hw_accel: bool = False,
    progress_callback: Callable[[str, float], None] | None = None,
    temperature: float | None = None,
    chunk_length: int | None = None,
    condition_on_previous_text: bool | None = None,
    initial_prompt: str | None = None,
    vad_filter: bool | None = None,
    vad_parameters: dict | None = None,
    transcribe_provider: str | None = None,
    openai_api_key: str | None = None,
    output_width: int | None = None,
    output_height: int | None = None,
) -> Path | tuple[Path, subtitles.SocialCopy]:
    """
    Normalize video to 9:16, generate Greek subs, and burn them into the output.
    """
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    social_copy: subtitles.SocialCopy | None = None
    pipeline_timings: dict[str, float] = {}
    pipeline_error: str | None = None
    overall_start = time.perf_counter()
    total_duration = 0.0
    audio_path: Path | None = None
    srt_path: Path | None = None
    ass_path: Path | None = None
    transcript_text: str | None = None
    scratch_dir_path: Path | None = None

    selected_model = model_size or config.WHISPER_MODEL_SIZE
    # Normalize common aliases so "turbo" routes to the CT2-quantized model
    if "turbo" in selected_model.lower() and "ct2" not in selected_model.lower():
        selected_model = config.WHISPER_MODEL_TURBO

    # Allow explicit provider override, but auto-route if the model hints at OpenAI
    effective_provider = (
        transcribe_provider or ("openai" if subtitles.should_use_openai(selected_model) else "local")
    )

    effective_device = device or config.WHISPER_DEVICE
    effective_compute = compute_type or config.WHISPER_COMPUTE_TYPE
    effective_chunk_length = chunk_length or config.WHISPER_CHUNK_LENGTH
    effective_vad_filter = True if vad_filter is None else vad_filter
    effective_vad_parameters = vad_parameters or {"min_silence_duration_ms": 400}
    effective_audio_copy = audio_copy
    if effective_audio_copy is None:
        effective_audio_copy = _input_audio_is_aac(input_path)

    try:
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            scratch_dir_path = scratch
            scratch.mkdir(parents=True, exist_ok=True)
            
            # Get total duration for smart progress tracking
            try:
                total_duration = subtitles.get_video_duration(input_path)
            except Exception:
                # Fallback if ffprobe fails (unlikely if ffmpeg works)
                total_duration = 0.0

                # Heuristic defaults per model for accuracy + speed on M-series
            if beam_size is None:
                if selected_model == config.WHISPER_MODEL_TURBO:
                    beam_size = 1
                elif "large" in selected_model:
                    beam_size = 3
                else:
                    beam_size = 1

            if best_of is None:
                if selected_model == config.WHISPER_MODEL_TURBO:
                    best_of = 1
                elif "large" in selected_model:
                    best_of = 3
                else:
                    best_of = 1

            if condition_on_previous_text is None:
                condition_on_previous_text = "large" in selected_model

            if temperature is None:
                # Use deterministic pass on fast modes; leave Best with library defaults
                if selected_model == config.WHISPER_MODEL_TURBO:
                    temperature = 0.0
                elif "large" in selected_model:
                    temperature = None
                else:
                    temperature = 0.0

            # If running Turbo on CPU/auto, prefer int8 for speed
            if selected_model == config.WHISPER_MODEL_TURBO and effective_device in ("auto", "cpu") and effective_compute in (
                "float16",
                "auto",
            ):
                effective_compute = config.WHISPER_COMPUTE_TYPE_TURBO

            # Stage 1: Audio Extraction (5%)
            if progress_callback:
                progress_callback("Extracting audio...", 0.0)
            
            with metrics.measure_time(pipeline_timings, "extract_audio_s"):
                audio_path = subtitles.extract_audio(input_path, output_dir=scratch)
            
            # Stage 2: Transcription (5% -> 65%)
            if progress_callback:
                progress_callback("Transcribing audio...", 5.0)
                
            def _transcribe_progress(p: float) -> None:
                if progress_callback:
                    # Map 0-100% to 5-65% (range of 60%)
                    overall = 5.0 + (p * 0.6)
                    progress_callback(f"Transcribing audio ({int(p)}%)...", overall)

            with metrics.measure_time(pipeline_timings, "transcribe_s"):
                srt_path, cues = subtitles.generate_subtitles_from_audio(
                    audio_path,
                    model_size=selected_model,
                    language=language or config.WHISPER_LANGUAGE,
                    device=effective_device,
                    compute_type=effective_compute,
                    beam_size=beam_size,
                    best_of=best_of,
                    output_dir=scratch,
                    progress_callback=_transcribe_progress if total_duration > 0 else None,
                    total_duration=total_duration,
                    temperature=temperature,
                    chunk_length=effective_chunk_length,
                    condition_on_previous_text=condition_on_previous_text,
                    initial_prompt=initial_prompt,
                    vad_filter=effective_vad_filter,
                    vad_parameters=effective_vad_parameters,
                    provider=effective_provider,
                    openai_api_key=openai_api_key,
                )
            
            # Stage 3: Subtitle Styling (65% -> 70%)
            if progress_callback:
                progress_callback("Styling subtitles...", 65.0)
            
            with metrics.measure_time(pipeline_timings, "style_subs_s"):
                ass_path = subtitles.create_styled_subtitle_file(srt_path, cues=cues)

            transcript_text = subtitles.cues_to_text(cues)
            
            # Stage 4: Social Copy Generation (70% -> 80%)
            if generate_social_copy and progress_callback:  # pragma: no cover - UI progress only
                progress_callback("Generating social copy...", 70.0)
            
            # Parallel Execution:
            # 1. Generate Social Copy (if enabled)
            # 2. Burn Subtitles (FFmpeg)
            
            future_social = None
            social_start = time.perf_counter() if generate_social_copy else None
            
            with ThreadPoolExecutor() as executor:
                if generate_social_copy:
                    if use_llm_social_copy:
                        future_social = executor.submit(
                            subtitles.build_social_copy_llm,
                            transcript_text,
                            model=llm_model,
                            temperature=llm_temperature,
                            api_key=llm_api_key,
                        )
                    else:
                        # Local generation is fast enough to run inline
                        with metrics.measure_time(pipeline_timings, "social_copy_s"):
                            social_copy = subtitles.build_social_copy(transcript_text)

                # Stage 5: Video Encoding (80% -> 100%)
                if progress_callback:
                    progress_callback("Encoding video with subtitles...", 80.0)
                
                def _encode_progress(p: float) -> None:
                    if progress_callback:
                        # Map 0-100% to 80-100% (range of 20%)
                        overall = 80.0 + (p * 0.2)
                        progress_callback(f"Encoding video ({int(p)}%)...", overall)

                # Start FFmpeg immediately
                encode_log = ""
                with metrics.measure_time(pipeline_timings, "encode_s"):
                    try:
                        encode_log = _run_ffmpeg_with_subs(
                            input_path,
                            ass_path,
                            destination,
                            video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
                            video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
                            audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
                            audio_copy=effective_audio_copy,
                            use_hw_accel=use_hw_accel,
                            progress_callback=_encode_progress if total_duration > 0 else None,
                            total_duration=total_duration,
                            output_width=output_width,
                            output_height=output_height,
                        )
                    except subprocess.CalledProcessError as exc:
                        encode_log = exc.output or ""
                        if use_hw_accel:
                            # Retry without hardware acceleration if VideoToolbox fails
                            pipeline_timings["encode_retry"] = "fallback_to_software"
                            encode_log = _run_ffmpeg_with_subs(
                                input_path,
                                ass_path,
                                destination,
                                video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
                                video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
                                audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
                                audio_copy=effective_audio_copy,
                                use_hw_accel=False,
                                progress_callback=_encode_progress if total_duration > 0 else None,
                                total_duration=total_duration,
                                output_width=output_width,
                                output_height=output_height,
                            )
                        else:
                            raise  # pragma: no cover - surfaced for unexpected ffmpeg failure
                
                if encode_log:  # pragma: no cover - best-effort logging
                    pipeline_timings["encode_log"] = encode_log

                # Collect Social Copy result
                if generate_social_copy and future_social:
                    with metrics.measure_time(pipeline_timings, "social_copy_s"):
                        social_copy = future_social.result()
            
            # Final stage: Persisting artifacts
            if progress_callback:
                progress_callback("Finalizing...", 95.0)

            final_output = destination
            if not destination.exists():
                raise RuntimeError(f"Output video was not produced by ffmpeg; last log: {encode_log or 'n/a'}")

            if artifact_dir:
                artifact_dir.mkdir(parents=True, exist_ok=True)
                video_copy = artifact_dir / destination.name
                # Avoid copying a file onto itself when the output is already under artifact_dir
                if destination.resolve() != video_copy.resolve():
                    shutil.copy2(destination, video_copy)
                    final_output = video_copy
                else:
                    final_output = destination

                _persist_artifacts(
                    artifact_dir,
                    audio_path,
                    srt_path,
                    ass_path,
                    transcript_text,
                    social_copy,
                )
    except Exception as exc:
        pipeline_error = str(exc)
        raise
    finally:
        pipeline_timings["total_s"] = time.perf_counter() - overall_start
        metrics.log_pipeline_metrics(
            {
                "status": "error" if pipeline_error else "success",
                "error": pipeline_error,
                "encode_log": pipeline_timings.get("encode_log"),
                "model_size": selected_model,
                "device": effective_device,
                "compute_type": effective_compute,
                "beam_size": beam_size,
                "best_of": best_of,
                "temperature": temperature,
                "chunk_length": effective_chunk_length,
                "condition_on_previous_text": condition_on_previous_text,
                "initial_prompt": bool(initial_prompt),
                "transcribe_provider": effective_provider,
                "use_hw_accel": use_hw_accel,
                "audio_copy": effective_audio_copy,
                "language": language or config.WHISPER_LANGUAGE,
                "llm_social_copy": generate_social_copy,
                "use_llm_social_copy": use_llm_social_copy,
                "video_preset": video_preset or config.DEFAULT_VIDEO_PRESET,
                "video_crf": video_crf or config.DEFAULT_VIDEO_CRF,
                "output_width": output_width or config.DEFAULT_WIDTH,
                "output_height": output_height or config.DEFAULT_HEIGHT,
                "input_bytes": input_path.stat().st_size if input_path.exists() else None,
                "output_bytes": final_output.stat().st_size if 'final_output' in locals() and final_output.exists() else None,
                "duration_s": total_duration,
                "timings": pipeline_timings,
            }
        )
        if scratch_dir_path and scratch_dir_path.exists():  # pragma: no cover - cleanup path
            shutil.rmtree(scratch_dir_path, ignore_errors=True)
    
    if progress_callback:
        progress_callback("Complete!", 100.0)
    
    if generate_social_copy:
        if social_copy is None:
            # Safety fallback to deterministic social copy so we never raise on None
            social_copy = subtitles.build_social_copy(transcript_text or "")
        return final_output if 'final_output' in locals() else destination, social_copy
    return final_output if 'final_output' in locals() else destination
