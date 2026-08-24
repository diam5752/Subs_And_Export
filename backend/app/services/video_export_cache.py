"""Deterministic fingerprints for reusable rendered video exports."""

from __future__ import annotations

import hashlib
import json
import platform
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from backend.app.core.config import settings

_EXPORT_RENDERER_VERSION = 1
_RESULT_RENDER_FIELDS = (
    "subtitle_position",
    "max_subtitle_lines",
    "subtitle_color",
    "shadow_strength",
    "highlight_style",
    "subtitle_size",
    "karaoke_enabled",
    "watermark_enabled",
)


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprint(path: Path) -> dict[str, int | str]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _preferred_transcript(input_video: Path, artifact_dir: Path) -> Path | None:
    preferred = artifact_dir / f"{input_video.stem}.srt"
    if preferred.is_file():
        return preferred
    return next(iter(sorted(artifact_dir.glob("*.srt"))), None)


def _preferred_ass(input_video: Path, artifact_dir: Path) -> Path | None:
    preferred = artifact_dir / f"{input_video.stem}.ass"
    if preferred.is_file():
        return preferred
    return next(iter(sorted(artifact_dir.glob("*.ass"))), None)


def build_video_export_signature(
    *,
    input_video: Path,
    artifact_dir: Path,
    resolution: str,
    subtitle_settings: Mapping[str, Any],
    result_data: Mapping[str, Any],
    video_crf: int,
) -> str:
    """Hash every persisted input that can change the rendered MP4."""
    transcript_path = _preferred_transcript(input_video, artifact_dir)
    ass_path = _preferred_ass(input_video, artifact_dir)
    transcription_path = artifact_dir / "transcription.json"
    watermark_enabled = bool(
        subtitle_settings.get(
            "watermark_enabled",
            result_data.get("watermark_enabled", False),
        ),
    )
    payload = {
        "renderer_version": _EXPORT_RENDERER_VERSION,
        "resolution": resolution,
        "source": _source_fingerprint(input_video),
        "transcript": {
            "name": transcript_path.name if transcript_path else None,
            "sha256": _sha256_file(transcript_path) if transcript_path else None,
        },
        "ass": {
            "name": ass_path.name if ass_path else None,
            "sha256": _sha256_file(ass_path) if ass_path else None,
        },
        "transcription_sha256": _sha256_file(transcription_path),
        "subtitle_settings": dict(subtitle_settings),
        "persisted_settings": {field: result_data.get(field) for field in _RESULT_RENDER_FIELDS},
        "encoder": {
            "crf": video_crf,
            "preset": settings.default_video_preset,
            "audio_bitrate": settings.default_audio_bitrate,
            "hardware_acceleration": bool(
                settings.use_hw_accel and platform.system() == "Darwin",
            ),
        },
        "watermark_sha256": (_sha256_file(settings.watermark_path) if watermark_enabled else None),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
