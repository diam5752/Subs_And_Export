"""Export routes - video and SRT exports."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ...core.config import settings
from ...core.auth import User
from ...core.errors import sanitize_message
from ...core.gcs import download_object, get_gcs_settings, upload_object
from ...core.ratelimit import limiter_content
from ...schemas.base import JobResponse
from ...services.jobs import JobStore
from ...services.video_processing import generate_video_variant
from ..deps import get_current_user, get_job_store
from .file_utils import DATA_DIR, MAX_UPLOAD_BYTES, data_roots, relpath_safe
from .validation import (
    ALLOWED_VIDEO_EXTENSIONS,
    validate_highlight_style,
    validate_max_subtitle_lines,
    validate_shadow_strength,
    validate_subtitle_position,
    validate_subtitle_size,
)


logger = logging.getLogger(__name__)
router = APIRouter()


def _ensure_job_size(job):
    """Helper to backfill output_size for legacy jobs."""
    if job.status == "completed" and job.result_data:
        if not job.result_data.get("output_size"):
            video_path = job.result_data.get("video_path")
            if video_path:
                try:
                    full_path = DATA_DIR / video_path
                    if not full_path.exists():
                        full_path = settings.project_root.parent / video_path
                    if full_path.exists():
                        job.result_data["output_size"] = full_path.stat().st_size
                except Exception as e:
                    logger.warning(f"Failed to ensure job size: {e}")
    return job


class ExportRequest(BaseModel):
    resolution: str = Field(..., max_length=50)
    subtitle_position: int | None = None
    max_subtitle_lines: int | None = None
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int | None = None
    highlight_style: str | None = Field(None, max_length=20)
    subtitle_size: int | None = None
    karaoke_enabled: bool | None = None
    watermark_enabled: bool | None = None

    @field_validator('subtitle_color')
    @classmethod
    def validate_subtitle_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^&H[0-9A-Fa-f]{8}$", v):
            raise ValueError("Invalid subtitle color format (expected &HAABBGGRR)")
        return v


@router.post("/jobs/{job_id}/export", response_model=JobResponse, dependencies=[Depends(limiter_content)])
def export_video(
    job_id: str,
    request: ExportRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
):
    """Export a video variant from an existing job."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to export")

    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= settings.max_concurrent_jobs:
        raise HTTPException(status_code=429, detail="System busy. Please wait for your other jobs to finish.")

    data_dir, uploads_dir, artifacts_root = data_roots()
    artifact_dir = artifacts_root / job_id

    if request.resolution == "srt":
        # SRT Export: Fast path
        try:
            from ...services.subtitles import _write_srt_from_segments

            transcription_json = artifact_dir / "transcription.json"
            if not transcription_json.exists():
                raise HTTPException(404, "Transcript not found (cannot export SRT)")

            cues_data = json.loads(transcription_json.read_text(encoding="utf-8"))
            segments = [(cue["start"], cue["end"], cue["text"]) for cue in cues_data]

            srt_path = artifact_dir / "processed.srt"
            _write_srt_from_segments(segments, srt_path)

            result_data = job.result_data.copy() if job.result_data else {}
            variants = result_data.get("variants", {})
            public_path = relpath_safe(srt_path, data_dir).as_posix()
            variants["srt"] = f"/static/{public_path}"
            result_data["variants"] = variants

            gcs_settings = get_gcs_settings()
            if gcs_settings:
                try:
                    upload_object(
                        settings=gcs_settings,
                        object_name=f"{gcs_settings.static_prefix}/{public_path}",
                        source=srt_path,
                        content_type="text/plain",
                    )
                except Exception as exc:
                    logger.warning("Failed to upload SRT export to GCS (%s): %s", job_id, exc)

            job_store.update_job(job_id, result_data=result_data, status="completed")
            updated_job = job_store.get_job(job_id)
            return _ensure_job_size(updated_job)

        except Exception as e:
            logger.exception("SRT Export failed")
            raise HTTPException(500, f"SRT Export failed: {sanitize_message(str(e))}")

    # Video export
    input_video = None
    for ext in [".mp4", ".mov", ".mkv"]:
        candidate = uploads_dir / f"{job_id}_input{ext}"
        if candidate.exists():
            input_video = candidate
            break

    if not input_video:
        gcs_settings = get_gcs_settings()
        source_gcs_object = (job.result_data or {}).get("source_gcs_object")
        if (
            gcs_settings
            and isinstance(source_gcs_object, str)
            and source_gcs_object.startswith(f"{gcs_settings.uploads_prefix}/")
        ):
            ext = Path(source_gcs_object).suffix.lower()
            if ext in ALLOWED_VIDEO_EXTENSIONS:
                destination = uploads_dir / f"{job_id}_input{ext}"
                try:
                    download_object(
                        settings=gcs_settings,
                        object_name=source_gcs_object,
                        destination=destination,
                        max_bytes=MAX_UPLOAD_BYTES,
                    )
                    input_video = destination
                except Exception as exc:
                    logger.warning("Failed to download input video from GCS for export (%s): %s", job_id, exc)

    if not input_video:
        raise HTTPException(404, "Original input video not found")

    if request.subtitle_position is not None:
        validate_subtitle_position(request.subtitle_position)
    if request.max_subtitle_lines is not None:
        validate_max_subtitle_lines(request.max_subtitle_lines)
    if request.shadow_strength is not None:
        validate_shadow_strength(request.shadow_strength)
    if request.subtitle_size is not None:
        validate_subtitle_size(request.subtitle_size)
    if request.highlight_style is not None:
        validate_highlight_style(request.highlight_style)

    try:
        subtitle_settings = request.model_dump(exclude_defaults=True)
        subtitle_settings.pop("resolution", None)
        if subtitle_settings.get("highlight_style"):
            subtitle_settings["highlight_style"] = validate_highlight_style(str(subtitle_settings["highlight_style"]))
        if subtitle_settings.get("subtitle_position") is not None:
            subtitle_settings["subtitle_position"] = validate_subtitle_position(int(subtitle_settings["subtitle_position"]))
        if subtitle_settings.get("max_subtitle_lines") is not None:
            subtitle_settings["max_subtitle_lines"] = validate_max_subtitle_lines(int(subtitle_settings["max_subtitle_lines"]))
        if subtitle_settings.get("shadow_strength") is not None:
            subtitle_settings["shadow_strength"] = validate_shadow_strength(int(subtitle_settings["shadow_strength"]))
        if subtitle_settings.get("subtitle_size") is not None:
            subtitle_settings["subtitle_size"] = validate_subtitle_size(int(subtitle_settings["subtitle_size"]))

        output_path = generate_video_variant(
            job_id, input_video, artifact_dir, request.resolution,
            job_store, current_user.id, subtitle_settings=subtitle_settings or None,
        )

        result_data = job.result_data.copy() if job.result_data else {}
        variants = result_data.get("variants", {})

        public_path = relpath_safe(output_path, data_dir).as_posix()
        variants[request.resolution] = f"/static/{public_path}"
        result_data["variants"] = variants

        gcs_settings = get_gcs_settings()
        if gcs_settings:
            try:
                upload_object(
                    settings=gcs_settings,
                    object_name=f"{gcs_settings.static_prefix}/{public_path}",
                    source=output_path,
                    content_type="video/mp4",
                )
            except Exception as exc:
                logger.warning("Failed to upload export variant to GCS (%s): %s", job_id, exc)

        job_store.update_job(job_id, result_data=result_data, status="completed", progress=100)
        updated_job = job_store.get_job(job_id)
        return _ensure_job_size(updated_job)

    except Exception as e:
        raise HTTPException(500, f"Export failed: {sanitize_message(str(e))}")
