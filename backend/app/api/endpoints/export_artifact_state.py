"""Small state helpers for exact video-export caching."""

from __future__ import annotations

import hmac
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .file_utils import relpath_safe


@dataclass(frozen=True)
class VideoExportPlan:
    result_data: dict[str, object]
    subtitle_settings: dict[str, object]
    video_crf: int
    output_path: Path
    export_signature: str
    export_cache: dict[str, object]


def record_export_variant(
    result_data: dict[str, object],
    *,
    resolution: str,
    output_path: Path,
    data_dir: Path,
) -> None:
    variants_value = result_data.get("variants")
    variants = dict(variants_value) if isinstance(variants_value, dict) else {}
    public_path = relpath_safe(output_path, data_dir).as_posix()
    variants[resolution] = f"/static/{public_path}"
    result_data["variants"] = variants


def resolve_subtitle_export_limits(
    *,
    requested_lines: int | None,
    requested_size: int | None,
    result_data: Mapping[str, object],
) -> tuple[int, int]:
    resolved_lines = requested_lines
    if resolved_lines is None:
        resolved_lines = int(cast(Any, result_data.get("max_subtitle_lines", 2) or 2))
    resolved_size = requested_size
    if resolved_size is None:
        resolved_size = int(cast(Any, result_data.get("subtitle_size", 100) or 100))
    return resolved_lines, resolved_size


def build_video_export_plan(
    *,
    resolution: str,
    raw_result_data: Mapping[str, object] | None,
    subtitle_settings: dict[str, object],
    video_crf: int,
    input_video: Path,
    artifact_dir: Path,
    build_signature: Callable[..., str],
) -> VideoExportPlan:
    result_data = dict(raw_result_data or {})
    output_path = artifact_dir / f"processed_{resolution}.mp4"
    export_signature = build_signature(
        input_video=input_video,
        artifact_dir=artifact_dir,
        resolution=resolution,
        subtitle_settings=subtitle_settings,
        result_data=result_data,
        video_crf=video_crf,
    )
    export_cache_value = result_data.get("export_cache")
    export_cache = dict(export_cache_value) if isinstance(export_cache_value, dict) else {}
    return VideoExportPlan(
        result_data=result_data,
        subtitle_settings=subtitle_settings,
        video_crf=video_crf,
        output_path=output_path,
        export_signature=export_signature,
        export_cache=export_cache,
    )


def cached_export_matches(
    cache_record: object,
    *,
    export_signature: str,
    output_path: Path,
) -> bool:
    if not isinstance(cache_record, dict):
        return False
    cached_signature = cache_record.get("signature")
    cached_size = cache_record.get("size")
    if not isinstance(cached_signature, str):
        return False
    if not isinstance(cached_size, int) or isinstance(cached_size, bool):
        return False
    if cached_size <= 0 or not output_path.is_file():
        return False
    return hmac.compare_digest(cached_signature, export_signature) and output_path.stat().st_size == cached_size


def record_rendered_export(
    plan: VideoExportPlan,
    *,
    resolution: str,
    output_path: Path,
    export_signature: str,
) -> None:
    plan.export_cache[resolution] = {
        "signature": export_signature,
        "size": output_path.stat().st_size,
    }
    plan.result_data["export_cache"] = plan.export_cache
