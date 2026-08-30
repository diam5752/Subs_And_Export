"""Export routes - video and subtitle file exports."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response

from ...core.auth import User
from ...core.config import settings
from ...core.database import Database
from ...core.download_grants import DownloadGrantError, create_download_grant
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
from .export_artifact_state import (
    VideoExportPlan as _VideoExportPlan,
)
from .export_artifact_state import (
    build_video_export_plan,
    cached_export_matches,
    record_rendered_export,
    resolve_subtitle_export_limits,
)
from .export_artifact_state import (
    record_export_variant as _record_export_variant,
)
from .export_models import (
    ArtifactDownloadGrantRequest,
    ArtifactDownloadGrantResponse,
    ExportRequest,
)
from .file_utils import (
    data_roots,
    reserve_render_storage,
    sanitize_download_filename,
)
from .validation import (
    validate_highlight_style,
    validate_max_subtitle_lines,
    validate_shadow_strength,
    validate_subtitle_position,
    validate_subtitle_size,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _log_export_failure(message: str, exc: Exception) -> None:
    logger.error(
        message,
        extra={"data": {"error_type": type(exc).__name__}},
    )


def _export_progress_callback(
    job_store: JobStore,
    job_id: str,
) -> Callable[[float], None]:
    """Persist coarse FFmpeg progress without turning every frame into a write."""
    last_progress = -2

    def update(progress: float) -> None:
        nonlocal last_progress
        bounded = max(1, min(99, int(progress)))
        if bounded < last_progress + 2:
            return
        last_progress = bounded
        job_store.update_job(job_id, progress=bounded)

    return update


def _render_export_video(
    *,
    job_id: str,
    input_video: Path,
    artifact_dir: Path,
    resolution: str,
    job_store: JobStore,
    user_id: str,
    subtitle_settings: dict[str, object],
    video_crf: int,
    data_dir: Path,
    db: Database,
) -> Path:
    width, height = (int(part) for part in resolution.split("x"))
    pixel_multiplier = max(1.0, (width * height) / (1080 * 1920))
    required_output_bytes = int(input_video.stat().st_size * pixel_multiplier)
    slots_required = render_slot_weight(
        width,
        height,
        capacity=settings.media_render_slots,
    )
    job_store.update_job(job_id, progress=0)
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
            return generate_video_variant(
                job_id,
                input_video,
                artifact_dir,
                resolution,
                job_store,
                user_id,
                subtitle_settings=subtitle_settings or None,
                video_crf=video_crf,
                held_render_slots=render_slots,
                progress_callback=_export_progress_callback(job_store, job_id),
            )


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


def _download_grant_file_path(artifact_path: str, expected_job_id: str) -> str:
    parsed = urlsplit(artifact_path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or "%" in artifact_path:
        raise DownloadGrantError("Artifact path must be a canonical same-origin path")
    prefix = f"/static/artifacts/{expected_job_id}/"
    if not parsed.path.startswith(prefix) or "\\" in parsed.path:
        raise DownloadGrantError("Artifact path does not match the requested job")
    file_path = parsed.path.removeprefix("/static/")
    parts = file_path.split("/")
    if len(parts) < 3 or any(not part or part in {".", ".."} for part in parts):
        raise DownloadGrantError("Artifact path is invalid")
    return file_path


def _assert_regular_job_artifact(artifacts_root: Path, job_id: str, file_path: str) -> None:
    job_root = artifacts_root / job_id
    relative_path = Path(*file_path.split("/")[2:])
    candidate = job_root / relative_path
    try:
        if job_root.is_symlink() or not job_root.is_dir():
            raise ValueError("invalid job root")
        current = job_root
        for component in relative_path.parts:
            current = current / component
            if current.is_symlink():
                raise ValueError("symlinked artifact")
        candidate.resolve().relative_to(job_root.resolve())
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="File not found") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")


@router.post(
    "/jobs/{job_id}/download-grant",
    response_model=ArtifactDownloadGrantResponse,
    dependencies=[Depends(limiter_content)],
)
def create_artifact_download_grant(
    job_id: str,
    request: ArtifactDownloadGrantRequest,
    response: Response,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
) -> ArtifactDownloadGrantResponse:
    """Create an exact, short-lived URL that may cross browser sessions."""
    job = job_store.get_job(job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        file_path = _download_grant_file_path(request.artifact_path, job_id)
    except DownloadGrantError as exc:
        raise HTTPException(status_code=400, detail="Invalid artifact path") from exc

    _, _, artifacts_root = data_roots()
    _assert_regular_job_artifact(artifacts_root, job_id, file_path)
    source_filename = Path(file_path).name
    filename = sanitize_download_filename(request.filename, source_filename)
    token = create_download_grant(
        secret=settings.download_grant_signing_secret(),
        user_id=current_user.id,
        file_path=file_path,
        filename=filename,
        ttl_seconds=settings.download_grant_ttl_seconds,
    )
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return ArtifactDownloadGrantResponse(
        download_url=f"/static/{file_path}?grant={token}",
        expires_in=settings.download_grant_ttl_seconds,
    )


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


def _reload_exported_job(
    job_store: JobStore,
    job_id: str,
    *,
    missing_detail: str,
) -> JobResponse:
    updated_job = job_store.get_job(job_id)
    if updated_job is None:
        raise HTTPException(status_code=500, detail=missing_detail)
    return JobResponse.model_validate(updated_job)


def _export_subtitle_artifact(
    *,
    job_id: str,
    request: ExportRequest,
    job: Job,
    artifact_dir: Path,
    data_dir: Path,
    job_store: JobStore,
) -> JobResponse:
    try:
        return _write_subtitle_artifact(
            job_id=job_id,
            request=request,
            job=job,
            artifact_dir=artifact_dir,
            data_dir=data_dir,
            job_store=job_store,
        )
    except HTTPException:
        raise
    except MalformedTranscriptError as exc:
        raise HTTPException(
            422,
            f"Cannot export malformed transcript: {sanitize_message(str(exc))}",
        ) from exc
    except Exception as exc:
        _log_export_failure("Subtitle export failed", exc)
        raise HTTPException(
            500,
            f"{request.resolution.upper()} export failed: {sanitize_message(str(exc))}",
        ) from exc


def _write_subtitle_artifact(
    *,
    job_id: str,
    request: ExportRequest,
    job: Job,
    artifact_dir: Path,
    data_dir: Path,
    job_store: JobStore,
) -> JobResponse:
    transcription_json = artifact_dir / "transcription.json"
    if not transcription_json.exists():
        raise HTTPException(404, "Transcript not found (cannot export subtitle file)")
    result_data: dict[str, object] = dict(job.result_data or {})
    resolved_lines, resolved_size = resolve_subtitle_export_limits(
        requested_lines=request.max_subtitle_lines,
        requested_size=request.subtitle_size,
        result_data=result_data,
    )
    export_path = artifact_dir / f"processed.{request.resolution}"
    export_subtitle_file(
        transcription_json=transcription_json,
        export_path=export_path,
        export_format=request.resolution,
        max_subtitle_lines=resolved_lines,
        subtitle_size=resolved_size,
    )
    _record_export_variant(
        result_data,
        resolution=request.resolution,
        output_path=export_path,
        data_dir=data_dir,
    )
    job_store.update_job(job_id, result_data=result_data, status="completed")
    return _reload_exported_job(
        job_store,
        job_id,
        missing_detail="Exported job could not be reloaded",
    )


def _find_export_input(
    *,
    job_id: str,
    job: Job,
    uploads_dir: Path,
    data_dir: Path,
) -> Path:
    for extension in (".mp4", ".mov", ".mkv"):
        candidate = uploads_dir / f"{job_id}_input{extension}"
        if candidate.exists():
            return candidate
    candidate_rel = (job.result_data or {}).get("video_path")
    if isinstance(candidate_rel, str) and candidate_rel:
        candidate = (data_dir / candidate_rel).resolve()
        if candidate.is_relative_to(data_dir.resolve()) and candidate.exists():
            return candidate
    raise HTTPException(404, "Original input video not found")


def _video_export_subtitle_settings(request: ExportRequest) -> dict[str, object]:
    subtitle_settings = request.model_dump(
        exclude_none=True,
        exclude={"resolution", "video_quality"},
    )
    if subtitle_settings.get("highlight_style"):
        subtitle_settings["highlight_style"] = validate_highlight_style(
            str(subtitle_settings["highlight_style"]),
        )
    validators = (
        ("subtitle_position", validate_subtitle_position),
        ("max_subtitle_lines", validate_max_subtitle_lines),
        ("shadow_strength", validate_shadow_strength),
        ("subtitle_size", validate_subtitle_size),
    )
    for field, validator in validators:
        if subtitle_settings.get(field) is not None:
            subtitle_settings[field] = validator(int(subtitle_settings[field]))
    return subtitle_settings


def _video_export_crf(
    request: ExportRequest,
    result_data: dict[str, object],
) -> int:
    if request.video_quality is not None:
        return crf_for_video_quality(request.video_quality)
    stored_crf = result_data.get("video_crf")
    return int(cast(Any, stored_crf)) if stored_crf is not None else settings.default_video_crf


def _reuse_cached_export(
    *,
    job_id: str,
    request: ExportRequest,
    result_data: dict[str, object],
    output_path: Path,
    data_dir: Path,
    job_store: JobStore,
) -> JobResponse:
    _record_export_variant(
        result_data,
        resolution=request.resolution,
        output_path=output_path,
        data_dir=data_dir,
    )
    job_store.update_job(
        job_id,
        result_data=result_data,
        status="completed",
        progress=100,
    )
    logger.info("Reused exact rendered video export")
    return _reload_exported_job(
        job_store,
        job_id,
        missing_detail="Cached export job could not be reloaded",
    )


def _reuse_video_export_if_cached(
    *,
    job_id: str,
    request: ExportRequest,
    plan: _VideoExportPlan,
    data_dir: Path,
    job_store: JobStore,
) -> JobResponse | None:
    if not cached_export_matches(
        plan.export_cache.get(request.resolution),
        export_signature=plan.export_signature,
        output_path=plan.output_path,
    ):
        return None
    return _reuse_cached_export(
        job_id=job_id,
        request=request,
        result_data=plan.result_data,
        output_path=plan.output_path,
        data_dir=data_dir,
        job_store=job_store,
    )


def _persist_rendered_video_export(
    *,
    job_id: str,
    request: ExportRequest,
    plan: _VideoExportPlan,
    output_path: Path,
    export_signature: str,
    data_dir: Path,
    job_store: JobStore,
) -> JobResponse:
    _record_export_variant(
        plan.result_data,
        resolution=request.resolution,
        output_path=output_path,
        data_dir=data_dir,
    )
    record_rendered_export(
        plan,
        resolution=request.resolution,
        output_path=output_path,
        export_signature=export_signature,
    )
    job_store.update_job(
        job_id,
        result_data=plan.result_data,
        status="completed",
        progress=100,
    )
    return _reload_exported_job(
        job_store,
        job_id,
        missing_detail="Exported job could not be reloaded",
    )


def _render_planned_video_export(
    *,
    job_id: str,
    request: ExportRequest,
    current_user: User,
    job_store: JobStore,
    db: Database,
    input_video: Path,
    artifact_dir: Path,
    data_dir: Path,
    plan: _VideoExportPlan,
) -> JobResponse:
    output_path = _render_export_video(
        job_id=job_id,
        input_video=input_video,
        artifact_dir=artifact_dir,
        resolution=request.resolution,
        job_store=job_store,
        user_id=current_user.id,
        subtitle_settings=plan.subtitle_settings,
        video_crf=plan.video_crf,
        data_dir=data_dir,
        db=db,
    )
    export_signature = build_video_export_signature(
        input_video=input_video,
        artifact_dir=artifact_dir,
        resolution=request.resolution,
        subtitle_settings=plan.subtitle_settings,
        result_data=plan.result_data,
        video_crf=plan.video_crf,
    )
    return _persist_rendered_video_export(
        job_id=job_id,
        request=request,
        plan=plan,
        output_path=output_path,
        export_signature=export_signature,
        data_dir=data_dir,
        job_store=job_store,
    )


def _export_video_artifact(
    *,
    job_id: str,
    request: ExportRequest,
    current_user: User,
    job_store: JobStore,
    db: Database,
    job: Job,
    data_dir: Path,
    uploads_dir: Path,
    artifact_dir: Path,
) -> JobResponse:
    try:
        return _perform_video_artifact_export(
            job_id=job_id,
            request=request,
            current_user=current_user,
            job_store=job_store,
            db=db,
            job=job,
            data_dir=data_dir,
            uploads_dir=uploads_dir,
            artifact_dir=artifact_dir,
        )
    except HTTPException:
        raise
    except Exception as exc:
        job_store.update_job(job_id, progress=100)
        _log_export_failure("Video export failed", exc)
        raise HTTPException(
            500,
            "Export failed. Please try again.",
        ) from exc


def _perform_video_artifact_export(
    *,
    job_id: str,
    request: ExportRequest,
    current_user: User,
    job_store: JobStore,
    db: Database,
    job: Job,
    data_dir: Path,
    uploads_dir: Path,
    artifact_dir: Path,
) -> JobResponse:
    input_video = _find_export_input(job_id=job_id, job=job, uploads_dir=uploads_dir, data_dir=data_dir)
    result_data: dict[str, object] = dict(job.result_data or {})
    subtitle_settings = _video_export_subtitle_settings(request)
    plan = build_video_export_plan(
        resolution=request.resolution,
        raw_result_data=result_data,
        subtitle_settings=subtitle_settings,
        video_crf=_video_export_crf(request, result_data),
        input_video=input_video,
        artifact_dir=artifact_dir,
        build_signature=build_video_export_signature,
    )
    cached_response = _reuse_video_export_if_cached(
        job_id=job_id,
        request=request,
        plan=plan,
        data_dir=data_dir,
        job_store=job_store,
    )
    if cached_response is not None:
        return cached_response
    return _render_planned_video_export(
        job_id=job_id,
        request=request,
        current_user=current_user,
        job_store=job_store,
        db=db,
        input_video=input_video,
        artifact_dir=artifact_dir,
        data_dir=data_dir,
        plan=plan,
    )


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
    job_store.update_job(job_id, status="completed")
    if job_store.count_active_jobs_for_user(current_user.id) >= settings.max_concurrent_jobs:
        raise HTTPException(
            status_code=429,
            detail="System busy. Please wait for your other jobs to finish.",
        )
    artifact_dir = artifacts_root / job_id
    _validate_subtitle_export_settings(request)
    if request.resolution in SUBTITLE_EXPORT_FORMATS:
        return _export_subtitle_artifact(
            job_id=job_id,
            request=request,
            job=job,
            artifact_dir=artifact_dir,
            data_dir=data_dir,
            job_store=job_store,
        )
    return _export_video_artifact(
        job_id=job_id,
        request=request,
        current_user=current_user,
        job_store=job_store,
        db=db,
        job=job,
        data_dir=data_dir,
        uploads_dir=uploads_dir,
        artifact_dir=artifact_dir,
    )
