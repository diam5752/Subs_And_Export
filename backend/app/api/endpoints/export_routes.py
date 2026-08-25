"""Export routes - video and subtitle file exports."""

from __future__ import annotations

import hmac
import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from ...core.auth import User
from ...core.config import settings
from ...core.database import Database
from ...core.errors import sanitize_message
from ...core.media_capacity import lock_media_render, render_slot_weight
from ...core.ratelimit import limiter_content
from ...core.workspace_deletion import (
    JobWorkspaceLockTimeoutError,
    lock_job_workspace,
)
from ...schemas.base import JobResponse
from ...services.jobs import Job, JobStore
from ...services.subtitle_exports import (
    SUBTITLE_EXPORT_FORMATS,
    MalformedTranscriptError,
    export_subtitle_file,
)
from ...services.video_export_cache import build_video_export_signature
from ...services.video_processing import generate_video_variant
from ...services.video_quality import crf_for_video_quality
from ..deps import get_current_user, get_db, get_job_store
from .file_utils import data_roots, relpath_safe, reserve_render_storage
from .validation import (
    validate_highlight_style,
    validate_max_subtitle_lines,
    validate_shadow_strength,
    validate_subtitle_position,
    validate_subtitle_size,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _validate_subtitle_export_settings(request: "ExportRequest") -> None:
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
    video_quality: str | None = Field(None, max_length=50)

    @field_validator("subtitle_color")
    @classmethod
    def validate_subtitle_color(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^&H[0-9A-Fa-f]{8}$", v):
            raise ValueError("Invalid subtitle color format (expected &HAABBGGRR)")
        return v

    @field_validator("video_quality")
    @classmethod
    def validate_video_quality_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        crf_for_video_quality(normalized)
        return normalized

    @field_validator("resolution")
    @classmethod
    def validate_resolution(cls, value: str) -> str:
        cleaned = value.strip().lower().replace("×", "x")
        if cleaned in SUBTITLE_EXPORT_FORMATS:
            return cleaned

        parts = cleaned.split("x")
        if len(parts) != 2:
            raise ValueError("Invalid resolution format (expected WIDTHxHEIGHT or subtitle export format)")

        try:
            width = int(parts[0])
            height = int(parts[1])
        except ValueError as exc:
            raise ValueError("Invalid resolution format (expected WIDTHxHEIGHT or subtitle export format)") from exc

        if width <= 0 or height <= 0:
            raise ValueError("Resolution dimensions must be positive")
        if width > settings.max_resolution_dimension or height > settings.max_resolution_dimension:
            raise ValueError(f"Resolution exceeds max {settings.max_resolution_dimension}")

        return f"{width}x{height}"


@router.post("/jobs/{job_id}/export", response_model=JobResponse, dependencies=[Depends(limiter_content)])
def export_video(
    job_id: str,
    request: ExportRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    db: Database = Depends(get_db),
) -> JobResponse:
    """Export a video variant from an existing job."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to export")

    data_dir, uploads_dir, artifacts_root = data_roots()
    try:
        with lock_job_workspace(data_dir=data_dir, job_id=job_id):
            locked_job = job_store.get_job(job_id)
            if not locked_job or locked_job.user_id != current_user.id:
                raise HTTPException(404, "Job not found")
            if locked_job.status != "completed":
                raise HTTPException(400, "Job must be completed to export")
            return _export_video_locked(
                job_id=job_id,
                request=request,
                current_user=current_user,
                job_store=job_store,
                db=db,
                job=locked_job,
                data_dir=data_dir,
                uploads_dir=uploads_dir,
                artifacts_root=artifacts_root,
            )
    except JobWorkspaceLockTimeoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _export_video_locked(
    *,
    job_id: str,
    request: ExportRequest,
    current_user: User,
    job_store: JobStore,
    db: Database,
    job: Job,
    data_dir: Path,
    uploads_dir: Path,
    artifacts_root: Path,
) -> JobResponse:
    """Write one export while its cross-process workspace lock is held."""
    # Refresh the workspace lease before any potentially long export work.
    # The retention worker rechecks this timestamp immediately before deletion.
    job_store.update_job(job_id, status="completed")

    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= settings.max_concurrent_jobs:
        raise HTTPException(status_code=429, detail="System busy. Please wait for your other jobs to finish.")

    artifact_dir = artifacts_root / job_id
    _validate_subtitle_export_settings(request)

    if request.resolution in SUBTITLE_EXPORT_FORMATS:
        # Subtitle file export: fast path
        try:
            transcription_json = artifact_dir / "transcription.json"
            if not transcription_json.exists():
                raise HTTPException(404, "Transcript not found (cannot export subtitle file)")

            result_data = job.result_data.copy() if job.result_data else {}
            resolved_lines = request.max_subtitle_lines
            if resolved_lines is None:
                resolved_lines = int(result_data.get("max_subtitle_lines", 2) or 2)
            resolved_size = request.subtitle_size
            if resolved_size is None:
                resolved_size = int(result_data.get("subtitle_size", 100) or 100)

            export_path = artifact_dir / f"processed.{request.resolution}"
            subtitle_export = export_subtitle_file(
                transcription_json=transcription_json,
                export_path=export_path,
                export_format=request.resolution,
                max_subtitle_lines=resolved_lines,
                subtitle_size=resolved_size,
            )

            variants = result_data.get("variants", {})
            public_path = relpath_safe(export_path, data_dir).as_posix()
            variants[request.resolution] = f"/static/{public_path}"
            result_data["variants"] = variants

            job_store.update_job(job_id, result_data=result_data, status="completed")
            updated_job = job_store.get_job(job_id)
            if updated_job is None:
                raise HTTPException(status_code=500, detail="Exported job could not be reloaded")
            return JobResponse.model_validate(updated_job)
        except HTTPException:
            raise
        except MalformedTranscriptError as e:
            raise HTTPException(422, f"Cannot export malformed transcript: {sanitize_message(str(e))}") from e
        except Exception as e:
            logger.exception("%s export failed", request.resolution.upper())
            raise HTTPException(500, f"{request.resolution.upper()} export failed: {sanitize_message(str(e))}")

    # Video export
    input_video = None
    for ext in [".mp4", ".mov", ".mkv"]:
        candidate = uploads_dir / f"{job_id}_input{ext}"
        if candidate.exists():
            input_video = candidate
            break

    if not input_video:
        candidate_rel = (job.result_data or {}).get("video_path")
        if isinstance(candidate_rel, str) and candidate_rel:
            candidate = (data_dir / candidate_rel).resolve()
            data_dir_resolved = data_dir.resolve()
            if candidate.is_relative_to(data_dir_resolved) and candidate.exists():
                input_video = candidate

    if not input_video:
        raise HTTPException(404, "Original input video not found")

    try:
        result_data = dict(job.result_data or {})
        subtitle_settings = request.model_dump(
            exclude_none=True,
            exclude={"resolution", "video_quality"},
        )
        if subtitle_settings.get("highlight_style"):
            subtitle_settings["highlight_style"] = validate_highlight_style(str(subtitle_settings["highlight_style"]))
        if subtitle_settings.get("subtitle_position") is not None:
            subtitle_settings["subtitle_position"] = validate_subtitle_position(
                int(subtitle_settings["subtitle_position"])
            )
        if subtitle_settings.get("max_subtitle_lines") is not None:
            subtitle_settings["max_subtitle_lines"] = validate_max_subtitle_lines(
                int(subtitle_settings["max_subtitle_lines"])
            )
        if subtitle_settings.get("shadow_strength") is not None:
            subtitle_settings["shadow_strength"] = validate_shadow_strength(int(subtitle_settings["shadow_strength"]))
        if subtitle_settings.get("subtitle_size") is not None:
            subtitle_settings["subtitle_size"] = validate_subtitle_size(int(subtitle_settings["subtitle_size"]))

        if request.video_quality is not None:
            video_crf = crf_for_video_quality(request.video_quality)
        else:
            stored_crf = result_data.get("video_crf")
            video_crf = int(stored_crf) if stored_crf is not None else settings.default_video_crf

        output_path = artifact_dir / f"processed_{request.resolution}.mp4"
        export_signature = build_video_export_signature(
            input_video=input_video,
            artifact_dir=artifact_dir,
            resolution=request.resolution,
            subtitle_settings=subtitle_settings,
            result_data=result_data,
            video_crf=video_crf,
        )
        export_cache_value = result_data.get("export_cache")
        export_cache = dict(export_cache_value) if isinstance(export_cache_value, dict) else {}
        cache_record = export_cache.get(request.resolution)
        if (
            isinstance(cache_record, dict)
            and isinstance(cache_record.get("signature"), str)
            and hmac.compare_digest(cache_record["signature"], export_signature)
            and isinstance(cache_record.get("size"), int)
            and not isinstance(cache_record["size"], bool)
            and cache_record["size"] > 0
            and output_path.is_file()
            and output_path.stat().st_size == cache_record["size"]
        ):
            variants_value = result_data.get("variants")
            variants = dict(variants_value) if isinstance(variants_value, dict) else {}
            public_path = relpath_safe(output_path, data_dir).as_posix()
            variants[request.resolution] = f"/static/{public_path}"
            result_data["variants"] = variants
            job_store.update_job(
                job_id,
                result_data=result_data,
                status="completed",
                progress=100,
            )
            updated_job = job_store.get_job(job_id)
            if updated_job is None:
                raise HTTPException(
                    status_code=500,
                    detail="Cached export job could not be reloaded",
                )
            logger.info(
                "Reused exact rendered video export",
                extra={"job_id": job_id, "resolution": request.resolution},
            )
            return JobResponse.model_validate(updated_job)

        width, height = (int(part) for part in request.resolution.split("x"))
        pixel_multiplier = max(1.0, (width * height) / (1080 * 1920))
        required_output_bytes = int(input_video.stat().st_size * pixel_multiplier)
        slots_required = render_slot_weight(
            width,
            height,
            capacity=settings.media_render_slots,
        )
        with lock_media_render(
            data_dir=data_dir,
            slots_required=slots_required,
        ) as render_slots:
            with reserve_render_storage(
                data_dir=data_dir,
                required_bytes=required_output_bytes,
                render_slots=render_slots,
                db=db,
            ):
                output_path = generate_video_variant(
                    job_id,
                    input_video,
                    artifact_dir,
                    request.resolution,
                    job_store,
                    current_user.id,
                    subtitle_settings=subtitle_settings or None,
                    video_crf=video_crf,
                    held_render_slots=render_slots,
                )

        # Rendering may create or replace the ASS file. Persist the signature
        # of the exact subtitle asset that produced this MP4.
        export_signature = build_video_export_signature(
            input_video=input_video,
            artifact_dir=artifact_dir,
            resolution=request.resolution,
            subtitle_settings=subtitle_settings,
            result_data=result_data,
            video_crf=video_crf,
        )

        variants_value = result_data.get("variants")
        variants = dict(variants_value) if isinstance(variants_value, dict) else {}

        public_path = relpath_safe(output_path, data_dir).as_posix()
        variants[request.resolution] = f"/static/{public_path}"
        result_data["variants"] = variants
        export_cache[request.resolution] = {
            "signature": export_signature,
            "size": output_path.stat().st_size,
        }
        result_data["export_cache"] = export_cache

        job_store.update_job(job_id, result_data=result_data, status="completed", progress=100)
        updated_job = job_store.get_job(job_id)
        if updated_job is None:
            raise HTTPException(status_code=500, detail="Exported job could not be reloaded")
        return JobResponse.model_validate(updated_job)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Export failed: {sanitize_message(str(e))}")
