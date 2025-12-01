"""Video normalization and subtitle burn-in helpers."""

from __future__ import annotations

import json
import platform
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from . import config, subtitles


def _build_filtergraph(ass_path: Path) -> str:
    ass_file = ass_path.as_posix().replace("'", r"\'")
    ass_filter = f"ass='{ass_file}'"
    scale = (
        f"scale={config.DEFAULT_WIDTH}:-2:force_original_aspect_ratio=decrease"
    )
    pad = (
        f"pad={config.DEFAULT_WIDTH}:{config.DEFAULT_HEIGHT}:"
        f"({config.DEFAULT_WIDTH}-iw)/2:({config.DEFAULT_HEIGHT}-ih)/2"
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
) -> None:
    filtergraph = _build_filtergraph(ass_path)
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
        universal_newlines=True
    )
    
    # Regex to extract time=HH:MM:SS.mm
    time_pattern = re.compile(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})")
    
    if process.stderr:
        for line in process.stderr:
            if progress_callback and total_duration and total_duration > 0:
                match = time_pattern.search(line)
                if match:
                    h, m, s = match.groups()
                    current_seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    progress = min(100.0, (current_seconds / total_duration) * 100.0)
                    progress_callback(progress)
    
    process.wait()
    if process.returncode != 0:
        raise subprocess.CalledProcessError(process.returncode, cmd)


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
    best_of: int | None = 1,
    video_crf: int | None = None,
    video_preset: str | None = None,
    audio_bitrate: str | None = None,
    audio_copy: bool = False,
    generate_social_copy: bool = False,
    use_llm_social_copy: bool = False,
    llm_model: str | None = None,
    llm_temperature: float = 0.6,
    llm_api_key: str | None = None,
    artifact_dir: Path | None = None,
    use_hw_accel: bool = False,
    progress_callback: Callable[[str, float], None] | None = None,
) -> Path | tuple[Path, subtitles.SocialCopy]:
    """
    Normalize video to 9:16, generate Greek subs, and burn them into the output.
    """
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    social_copy: subtitles.SocialCopy | None = None

    with tempfile.TemporaryDirectory() as scratch_dir:
        scratch = Path(scratch_dir)
        
        # Get total duration for smart progress tracking
        total_duration = 0.0
        try:
            total_duration = subtitles.get_video_duration(input_path)
        except Exception:
            # Fallback if ffprobe fails (unlikely if ffmpeg works)
            pass

        # Stage 1: Audio Extraction (5%)
        if progress_callback:
            progress_callback("Extracting audio...", 0.0)
        audio_path = subtitles.extract_audio(input_path, output_dir=scratch)
        
        # Stage 2: Transcription (5% -> 65%)
        if progress_callback:
            progress_callback("Transcribing audio...", 5.0)
            
        def _transcribe_progress(p: float) -> None:
            if progress_callback:
                # Map 0-100% to 5-65% (range of 60%)
                overall = 5.0 + (p * 0.6)
                progress_callback(f"Transcribing audio ({int(p)}%)...", overall)

        srt_path, cues = subtitles.generate_subtitles_from_audio(
            audio_path,
            model_size=model_size or config.WHISPER_MODEL_SIZE,
            language=language or config.WHISPER_LANGUAGE,
            device=device or config.WHISPER_DEVICE,
            compute_type=compute_type or config.WHISPER_COMPUTE_TYPE,
            beam_size=beam_size,
            best_of=best_of,
            output_dir=scratch,
            progress_callback=_transcribe_progress if total_duration > 0 else None,
            total_duration=total_duration,
        )
        
        # Stage 3: Subtitle Styling (65% -> 70%)
        if progress_callback:
            progress_callback("Styling subtitles...", 65.0)
        ass_path = subtitles.create_styled_subtitle_file(srt_path, cues=cues)

        transcript_text = subtitles.cues_to_text(cues)
        
        # Stage 4: Social Copy Generation (70% -> 80%)
        if generate_social_copy and progress_callback:
            progress_callback("Generating social copy...", 70.0)
        
        # Parallel Execution:
        # 1. Generate Social Copy (if enabled)
        # 2. Burn Subtitles (FFmpeg)
        
        future_social = None
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
                    # Local generation is fast enough to run inline, but for consistency we can submit it too
                    # or just run it. It's instant, so let's just run it if not LLM.
                    # Actually, let's keep it simple. If LLM, use future.
                    pass

            # Stage 5: Video Encoding (80% -> 100%)
            if progress_callback:
                progress_callback("Encoding video with subtitles...", 80.0)
            
            def _encode_progress(p: float) -> None:
                if progress_callback:
                    # Map 0-100% to 80-100% (range of 20%)
                    overall = 80.0 + (p * 0.2)
                    progress_callback(f"Encoding video ({int(p)}%)...", overall)

            # Start FFmpeg immediately
            _run_ffmpeg_with_subs(
                input_path,
                ass_path,
                destination,
                video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
                video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
                audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
                audio_copy=audio_copy,
                use_hw_accel=use_hw_accel,
                progress_callback=_encode_progress if total_duration > 0 else None,
                total_duration=total_duration,
            )

            # Collect Social Copy result
            if generate_social_copy:
                if future_social:
                    social_copy = future_social.result()
                else:
                    # Fallback to local deterministic copy
                    social_copy = subtitles.build_social_copy(transcript_text)
        
        # Final stage: Persisting artifacts
        if progress_callback:
            progress_callback("Finalizing...", 95.0)
        
        if artifact_dir:
            _persist_artifacts(
                artifact_dir,
                audio_path,
                srt_path,
                ass_path,
                transcript_text,
                social_copy,
            )
    
    if progress_callback:
        progress_callback("Complete!", 100.0)
    
    if generate_social_copy:
        assert social_copy is not None
        return destination, social_copy
    return destination
