"""On-demand rendering of additional video resolution variants."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from backend.app.core.config import settings
from backend.app.services import ffmpeg_utils, settings_utils, subtitle_renderer
from backend.app.services.jobs import JobStore


def _parse_resolution(resolution: str) -> tuple[int, int]:
    try:
        width_text, height_text = resolution.lower().replace("×", "x").split("x")
        width, height = int(width_text), int(height_text)
    except ValueError as exc:
        raise ValueError("Invalid resolution format") from exc

    if width <= 0 or height <= 0:
        raise ValueError("Resolution dimensions must be positive")
    if width > settings.max_resolution_dimension or height > settings.max_resolution_dimension:
        raise ValueError(f"Resolution exceeds max {settings.max_resolution_dimension}")
    return width, height


def _find_transcript_path(input_path: Path, artifact_dir: Path) -> Path:
    expected_path = artifact_dir / f"{input_path.stem}.srt"
    if expected_path.exists():
        return expected_path
    fallback_path = next(iter(artifact_dir.glob("*.srt")), None)
    if fallback_path is None:
        raise FileNotFoundError("Transcript not found. Cannot generate variant.")
    return fallback_path


def _get_authorized_result_data(job_id: str, job_store: JobStore, user_id: str) -> dict[str, Any]:
    job = job_store.get_job(job_id)
    if not job or job.user_id != user_id:
        raise PermissionError("Job not found or access denied")
    return job.result_data or {}


def _resolve_integer(value: Any, default: int) -> int:
    return int(value) if value is not None else default


def _create_variant_ass(
    *,
    transcript_path: Path,
    artifact_dir: Path,
    style_settings: Mapping[str, Any],
    load_persisted_cues: Callable[[Path], Any],
    normalize_highlight_style: Callable[..., Any],
    resolve_ass_highlight_style: Callable[..., str],
) -> Path:
    cues = load_persisted_cues(artifact_dir / "transcription.json")
    font_size = settings_utils.font_size_from_subtitle_size(style_settings.get("subtitle_size"))
    karaoke_enabled = bool(style_settings.get("karaoke_enabled", True))
    requested_style = str(style_settings.get("highlight_style") or "karaoke")
    highlight_style = resolve_ass_highlight_style(
        normalize_highlight_style(requested_style, karaoke_enabled=karaoke_enabled),
        cues,
    )
    return subtitle_renderer.create_styled_subtitle_file(
        transcript_path,
        cues=cues,
        subtitle_position=settings_utils.normalize_subtitle_position(style_settings.get("subtitle_position")),
        max_lines=_resolve_integer(style_settings.get("max_subtitle_lines"), 2),
        primary_color=str(style_settings.get("subtitle_color") or settings.default_sub_color),
        shadow_strength=_resolve_integer(style_settings.get("shadow_strength"), 4),
        font_size=font_size,
        highlight_style=highlight_style,
        play_res_x=settings.default_width,
        play_res_y=settings.default_height,
        output_dir=artifact_dir,
    )


def _find_existing_ass(transcript_path: Path, artifact_dir: Path) -> Path:
    expected_path = transcript_path.with_suffix(".ass")
    if expected_path.exists():
        return expected_path
    candidates = sorted(artifact_dir.glob("*.ass"))
    return candidates[0] if candidates else expected_path


def _prepare_variant_ass(
    *,
    transcript_path: Path,
    artifact_dir: Path,
    result_data: Mapping[str, Any],
    subtitle_settings: Mapping[str, Any] | None,
    load_persisted_cues: Callable[[Path], Any],
    normalize_highlight_style: Callable[..., Any],
    resolve_ass_highlight_style: Callable[..., str],
) -> Path:
    if subtitle_settings:
        return _create_variant_ass(
            transcript_path=transcript_path,
            artifact_dir=artifact_dir,
            style_settings=subtitle_settings,
            load_persisted_cues=load_persisted_cues,
            normalize_highlight_style=normalize_highlight_style,
            resolve_ass_highlight_style=resolve_ass_highlight_style,
        )

    ass_path = _find_existing_ass(transcript_path, artifact_dir)
    if ass_path.exists():
        return ass_path
    return _create_variant_ass(
        transcript_path=transcript_path,
        artifact_dir=artifact_dir,
        style_settings=result_data,
        load_persisted_cues=load_persisted_cues,
        normalize_highlight_style=normalize_highlight_style,
        resolve_ass_highlight_style=resolve_ass_highlight_style,
    )


def _encode_video_variant(
    *,
    input_path: Path,
    ass_path: Path,
    artifact_dir: Path,
    width: int,
    height: int,
    result_data: Mapping[str, Any],
    subtitle_settings: Mapping[str, Any] | None,
    video_crf: int | None,
    held_render_slots: tuple[int, ...] | None,
    progress_callback: Callable[[float], None] | None,
) -> Path:
    output_filename = f"processed_{width}x{height}.mp4"
    destination = artifact_dir / output_filename
    stored_crf = result_data.get("video_crf")
    resolved_video_crf = (
        int(video_crf)
        if video_crf is not None
        else int(stored_crf)
        if stored_crf is not None
        else settings.default_video_crf
    )
    watermark_enabled = (
        bool(subtitle_settings.get("watermark_enabled", False))
        if subtitle_settings
        else bool(result_data.get("watermark_enabled", False))
    )
    temporary_destination = artifact_dir / f".{output_filename}.{uuid.uuid4().hex}.tmp.mp4"
    try:
        ffmpeg_utils.run_ffmpeg_with_subs(
            input_path,
            ass_path,
            temporary_destination,
            video_crf=resolved_video_crf,
            video_preset=settings.default_video_preset,
            audio_bitrate=settings.default_audio_bitrate,
            audio_copy=ffmpeg_utils.input_audio_is_aac(input_path),
            use_hw_accel=settings.use_hw_accel,
            output_width=width,
            output_height=height,
            watermark_enabled=watermark_enabled,
            held_render_slots=held_render_slots,
            progress_callback=progress_callback,
        )
        temporary_destination.replace(destination)
    finally:
        temporary_destination.unlink(missing_ok=True)
    return destination


def generate_video_variant(
    job_id: str,
    input_path: Path,
    artifact_dir: Path,
    resolution: str,
    job_store: JobStore,
    user_id: str,
    subtitle_settings: Mapping[str, Any] | None = None,
    video_crf: int | None = None,
    held_render_slots: tuple[int, ...] | None = None,
    progress_callback: Callable[[float], None] | None = None,
    *,
    load_persisted_cues: Callable[[Path], Any],
    normalize_highlight_style: Callable[..., Any],
    resolve_ass_highlight_style: Callable[..., str],
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError("Original input video not found")

    width, height = _parse_resolution(resolution)
    transcript_path = _find_transcript_path(input_path, artifact_dir)
    result_data = _get_authorized_result_data(job_id, job_store, user_id)
    ass_path = _prepare_variant_ass(
        transcript_path=transcript_path,
        artifact_dir=artifact_dir,
        result_data=result_data,
        subtitle_settings=subtitle_settings,
        load_persisted_cues=load_persisted_cues,
        normalize_highlight_style=normalize_highlight_style,
        resolve_ass_highlight_style=resolve_ass_highlight_style,
    )

    return _encode_video_variant(
        input_path=input_path,
        ass_path=ass_path,
        artifact_dir=artifact_dir,
        width=width,
        height=height,
        result_data=result_data,
        subtitle_settings=subtitle_settings,
        video_crf=video_crf,
        held_render_slots=held_render_slots,
        progress_callback=progress_callback,
    )
