"""Video normalization and subtitle burn-in helpers."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

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
) -> None:
    filtergraph = _build_filtergraph(ass_path)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filtergraph,
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
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


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
    artifact_dir: Path | None = None,
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
        audio_path = subtitles.extract_audio(input_path, output_dir=scratch)
        srt_path, cues = subtitles.generate_subtitles_from_audio(
            audio_path,
            model_size=model_size or config.WHISPER_MODEL_SIZE,
            language=language or config.WHISPER_LANGUAGE,
            device=device or config.WHISPER_DEVICE,
            compute_type=compute_type or config.WHISPER_COMPUTE_TYPE,
            beam_size=beam_size,
            best_of=best_of,
            output_dir=scratch,
        )
        ass_path = subtitles.create_styled_subtitle_file(srt_path, cues=cues)

        transcript_text = subtitles.cues_to_text(cues)
        if generate_social_copy:
            if use_llm_social_copy:
                social_copy = subtitles.build_social_copy_llm(
                    transcript_text,
                    model=llm_model,
                    temperature=llm_temperature,
                )
            else:
                social_copy = subtitles.build_social_copy(transcript_text)

        _run_ffmpeg_with_subs(
            input_path,
            ass_path,
            destination,
            video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
            video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
            audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
            audio_copy=audio_copy,
        )
        if artifact_dir:
            _persist_artifacts(
                artifact_dir,
                audio_path,
                srt_path,
                ass_path,
                transcript_text,
                social_copy,
            )
    if generate_social_copy:
        assert social_copy is not None
        return destination, social_copy
    return destination
