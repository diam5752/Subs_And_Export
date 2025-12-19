import logging
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator

from ...core import config
from ...core.database import Database
from ...core.auth import User
from ...core.gcs import delete_object, download_object, generate_signed_upload_url, get_gcs_settings, upload_object
from ...core.gcs_uploads import GcsUploadStore
from ...core.ratelimit import limiter_content, limiter_processing
from ...core.settings import load_app_settings
from ...schemas.base import (
    BatchDeleteRequest,
    BatchDeleteResponse,
    FactCheckResponse,
    JobResponse,
    PaginatedJobsResponse,
    SocialCopyResponse,
)
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.points import FACT_CHECK_COST, PointsStore, make_idempotency_id, process_video_cost
from ...services.video_processing import normalize_and_stub_subtitles, probe_media
from ..deps import (
    get_current_user,
    get_db,
    get_gcs_upload_store,
    get_history_store,
    get_job_store,
    get_points_store,
)

router = APIRouter()
logger = logging.getLogger(__name__)

APP_SETTINGS = load_app_settings()
MAX_UPLOAD_BYTES = APP_SETTINGS.max_upload_mb * 1024 * 1024

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv"}
ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-matroska",
    "application/octet-stream",
}
ALLOWED_TRANSCRIBE_PROVIDERS = {"local", "openai", "groq", "whispercpp"}
ALLOWED_VIDEO_QUALITIES = {"low size", "balanced", "high quality"}
ALLOWED_HIGHLIGHT_STYLES = {"static", "karaoke", "pop", "active-graphics", "active"}
MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/\\-]{0,63}$")


@dataclass(frozen=True)
class _ChargeContext:
    user_id: str
    cost: int
    reason: str
    meta: dict[str, Any] | None


def _refund_charge_best_effort(
    points_store: PointsStore | None,
    charge: _ChargeContext | None,
    *,
    status: str,
    error: str | None = None,
) -> None:
    if not points_store or not charge:
        return
    if charge.cost <= 0:
        return

    meta: dict[str, Any] = dict(charge.meta or {})
    meta["refunded_for_status"] = status
    if error:
        meta["error"] = error[:500]

    try:
        charge_id = meta.get("charge_id") or meta.get("job_id")
        if isinstance(charge_id, str) and charge_id:
            tx_id = make_idempotency_id("refund", charge.user_id, charge.reason, charge_id, str(charge.cost))
            points_store.refund_once(
                charge.user_id,
                charge.cost,
                original_reason=charge.reason,
                transaction_id=tx_id,
                meta=meta,
            )
        else:
            points_store.refund(
                charge.user_id,
                charge.cost,
                original_reason=charge.reason,
                meta=meta,
            )
    except Exception:
        logger.exception(
            "Failed to refund points (user_id=%s reason=%s status=%s)",
            charge.user_id,
            charge.reason,
            status,
        )


def _link_or_copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")

    try:
        os.link(source, destination)
        return
    except Exception:
        pass

    shutil.copy2(source, destination)


def _validate_transcribe_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized not in ALLOWED_TRANSCRIBE_PROVIDERS:
        raise HTTPException(status_code=400, detail="Invalid transcribe provider")
    return normalized


def _validate_model_name(value: str, *, allow_empty: bool, field_name: str) -> str | None:
    cleaned = value.strip()
    if not cleaned:
        if allow_empty:
            return None
        raise HTTPException(status_code=400, detail=f"{field_name} is required")
    if ".." in cleaned or cleaned.startswith(("/", "\\")) or "\\" in cleaned or ":" in cleaned:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    if not MODEL_NAME_PATTERN.match(cleaned):
        raise HTTPException(status_code=400, detail=f"Invalid {field_name}")
    return cleaned


def _validate_video_quality(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_VIDEO_QUALITIES:
        raise HTTPException(status_code=400, detail="Invalid video quality")
    return normalized


def _validate_subtitle_position(value: int) -> int:
    if value < 5 or value > 35:
        raise HTTPException(status_code=400, detail="subtitle_position out of range (5-35)")
    return value


def _validate_max_subtitle_lines(value: int) -> int:
    if value < 0 or value > 4:
        raise HTTPException(status_code=400, detail="max_subtitle_lines out of range (0-4)")
    return value


def _validate_shadow_strength(value: int) -> int:
    if value < 0 or value > 10:
        raise HTTPException(status_code=400, detail="shadow_strength out of range (0-10)")
    return value


def _validate_subtitle_size(value: int) -> int:
    if value < 50 or value > 150:
        raise HTTPException(status_code=400, detail="subtitle_size out of range (50-150)")
    return value


def _validate_highlight_style(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in ALLOWED_HIGHLIGHT_STYLES:
        raise HTTPException(status_code=400, detail="Invalid highlight style")
    return normalized

def _data_roots() -> tuple[Path, Path, Path]:
    """Resolve data directories relative to the configured project root."""
    # Use backend/data for all artifacts (not PROJECT_ROOT.parent)
    data_dir = config.PROJECT_ROOT / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, uploads_dir, artifacts_dir


def _relpath_safe(path: Path, base: Path) -> Path:
    """Return ``path`` relative to ``base`` when possible, otherwise the absolute path."""
    try:
        return path.relative_to(base)
    except ValueError:
        return path

# Initialize directories on import
DATA_DIR, UPLOADS_DIR, ARTIFACTS_DIR = _data_roots()

class ProcessingSettings(BaseModel):
    transcribe_model: str = "medium"
    transcribe_provider: str = "local"
    openai_model: str | None = None
    video_quality: str = "high quality"
    target_width: int | None = None
    target_height: int | None = None
    use_llm: bool = APP_SETTINGS.use_llm_by_default
    context_prompt: str = ""
    llm_model: str = APP_SETTINGS.llm_model
    llm_temperature: float = APP_SETTINGS.llm_temperature
    subtitle_position: int = 16  # 5-35 percentage from bottom
    max_subtitle_lines: int = 2
    subtitle_color: str | None = None
    shadow_strength: int = 4
    highlight_style: str = "karaoke"
    subtitle_size: int = 100  # 50-150 percentage scale
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


def _validate_upload_content_type(content_type: str) -> str:
    normalized = content_type.strip().lower()
    if not normalized:
        normalized = "application/octet-stream"
    if normalized not in ALLOWED_VIDEO_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Invalid content type")
    return normalized


def _build_processing_settings(
    *,
    transcribe_model: str,
    transcribe_provider: str,
    openai_model: str,
    video_quality: str,
    video_resolution: str,
    use_llm: bool,
    context_prompt: str,
    subtitle_position: int,
    max_subtitle_lines: int,
    subtitle_color: str | None,
    shadow_strength: int,
    highlight_style: str,
    subtitle_size: int,
    karaoke_enabled: bool,
    watermark_enabled: bool,
) -> ProcessingSettings:
    # Security: Validate input lengths to prevent DoS
    if len(context_prompt) > 5000:
        raise HTTPException(status_code=400, detail="Context prompt too long (max 5000 chars)")
    if len(transcribe_model) > 50:
        raise HTTPException(status_code=400, detail="Model name too long")
    if len(video_quality) > 50:
        raise HTTPException(status_code=400, detail="Video quality string too long")
    if len(transcribe_provider) > 50:
        raise HTTPException(status_code=400, detail="Provider name too long")
    if len(openai_model) > 50:
        raise HTTPException(status_code=400, detail="OpenAI model name too long")
    if len(video_resolution) > 50:
        raise HTTPException(status_code=400, detail="Resolution string too long")

    provider = _validate_transcribe_provider(transcribe_provider)
    model = _validate_model_name(transcribe_model, allow_empty=False, field_name="transcribe_model") or "medium"
    openai_model_value = _validate_model_name(openai_model, allow_empty=True, field_name="openai_model")
    if provider == "openai" and not openai_model_value:
        raise HTTPException(status_code=400, detail="openai_model is required when using the openai provider")

    quality = _validate_video_quality(video_quality)
    subtitle_position = _validate_subtitle_position(subtitle_position)
    max_subtitle_lines = _validate_max_subtitle_lines(max_subtitle_lines)
    shadow_strength = _validate_shadow_strength(shadow_strength)
    highlight_style = _validate_highlight_style(highlight_style)
    subtitle_size = _validate_subtitle_size(subtitle_size)

    if subtitle_color:
        if len(subtitle_color) > 20:
            raise HTTPException(status_code=400, detail="Subtitle color too long")
        if not re.match(r"^&H[0-9A-Fa-f]{8}$", subtitle_color):
            raise HTTPException(status_code=400, detail="Invalid subtitle color format (expected &HAABBGGRR)")

    target_width, target_height = _parse_resolution(video_resolution)
    return ProcessingSettings(
        transcribe_model=model,
        transcribe_provider=provider,
        openai_model=openai_model_value,
        video_quality=quality,
        target_width=target_width,
        target_height=target_height,
        use_llm=use_llm,
        context_prompt=context_prompt,
        subtitle_position=subtitle_position,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_color=subtitle_color,
        shadow_strength=shadow_strength,
        highlight_style=highlight_style,
        subtitle_size=subtitle_size,
        karaoke_enabled=karaoke_enabled,
        watermark_enabled=watermark_enabled,
    )


def _save_upload_with_limit(upload: UploadFile, destination: Path) -> None:
    """Write an upload to disk while enforcing the configured size limit."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    upload.file.seek(0)
    with destination.open("wb") as buffer:
        for chunk in iter(lambda: upload.file.read(1024 * 1024), b""):
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                buffer.close()
                destination.unlink(missing_ok=True)
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large; limit is {APP_SETTINGS.max_upload_mb}MB",
                )
            buffer.write(chunk)
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Empty upload")


def _record_event_safe(
    history_store: HistoryStore | None,
    user: User | None,
    kind: str,
    summary: str,
    data: dict,
) -> None:
    """Best-effort history logger that never raises."""
    if not history_store or not user:
        return
    try:
        history_store.record_event(user, kind, summary, data)
    except Exception:
        return


def _parse_resolution(res_str: str | None) -> tuple[int | None, int | None]:
    """Parse resolution strings like '1080x1920' or '2160×3840'. Returns (None, None) if empty."""
    if not res_str:
        return None, None  # Skip scaling, keep original resolution
    cleaned = res_str.lower().replace("×", "x")
    parts = cleaned.split("x")
    if len(parts) != 2:
        return None, None  # Skip scaling on parse error
    try:
        w = int(parts[0])
        h = int(parts[1])
        if w > 0 and h > 0:
            if w > config.MAX_RESOLUTION_DIMENSION or h > config.MAX_RESOLUTION_DIMENSION:
                logger.warning(f"Resolution {w}x{h} exceeds max {config.MAX_RESOLUTION_DIMENSION}")
                return None, None
            return w, h
    except Exception as e:
        logger.warning(f"Failed to parse resolution: {e}")
    return None, None  # Skip scaling on invalid dimensions

def run_video_processing(
    job_id: str,
    input_path: Path,
    output_path: Path,
    artifact_dir: Path,
    settings: ProcessingSettings,
    job_store: JobStore,
    history_store: HistoryStore | None = None,
    user: User | None = None,
    original_name: str | None = None,
    source_gcs_object_name: str | None = None,
    *,
    points_store: PointsStore | None = None,
    charge: _ChargeContext | None = None,
    db: Database | None = None,
):
    """Background task to run the heavy video processing."""
    try:
        current = job_store.get_job(job_id)
        if current and current.status == "cancelled":
            raise InterruptedError("Job cancelled by user")

        job_store.update_job(job_id, status="processing", progress=0, message="Starting processing...")

        last_update_time = 0.0
        last_check_time = 0.0

        def progress_callback(msg: str, percent: float):
            nonlocal last_update_time
            now = time.time()
            # Throttle DB updates to 1 per second to prevent SQLite contention
            if percent <= 0 or percent >= 100 or (now - last_update_time) >= 1.0:
                job_store.update_job(job_id, progress=int(percent), message=msg)
                last_update_time = now

        last_check_time = 0.0

        def check_cancelled():
            """Check if job was cancelled by user."""
            nonlocal last_check_time
            # Throttle DB checks to 2Hz to prevent SQLite contention during tight loops
            now = time.monotonic()
            if now - last_check_time < 0.5:
                return

            current_job = job_store.get_job(job_id)
            last_check_time = now
            if current_job and current_job.status == "cancelled":
                raise InterruptedError("Job cancelled by user")

        data_dir, _, _ = _data_roots()

        # Map settings to internal params
        # (Simplified logic from original app.py)
        model_size = settings.openai_model or settings.transcribe_model
        provider = settings.transcribe_provider or "local"
        crf_map = {"low size": 28, "balanced": 20, "high quality": 12}
        video_crf = crf_map.get(settings.video_quality.lower(), 12) # Default to high quality (12)
        target_width = settings.target_width  # None = keep original resolution
        target_height = settings.target_height  # None = keep original resolution

        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        result = normalize_and_stub_subtitles(
            input_path=input_path,
            output_path=output_path,
            model_size=model_size,
            generate_social_copy=settings.use_llm,
            use_llm_social_copy=settings.use_llm,
            llm_model=settings.llm_model,
            llm_temperature=settings.llm_temperature,
            artifact_dir=artifact_dir,
            video_crf=video_crf,
            initial_prompt=settings.context_prompt,
            transcribe_provider=provider,
            progress_callback=progress_callback,
            output_width=target_width,
            output_height=target_height,
            subtitle_position=settings.subtitle_position,
            max_subtitle_lines=settings.max_subtitle_lines,
            subtitle_color=settings.subtitle_color,
            shadow_strength=settings.shadow_strength,
            highlight_style=settings.highlight_style,
            subtitle_size=settings.subtitle_size,
            karaoke_enabled=settings.karaoke_enabled,
            watermark_enabled=settings.watermark_enabled,
            check_cancelled=check_cancelled,
            transcription_only=True,
            db=db,
            job_id=job_id,
        )

        # Result unpacking
        social = None
        final_path = output_path
        if isinstance(result, tuple):
            final_path, social = result
        else:
            final_path = result

        logger.debug(
            "normalize_and_stub_subtitles completed: max_subtitle_lines=%s subtitle_color=%s shadow_strength=%s highlight_style=%s",
            settings.max_subtitle_lines,
            settings.subtitle_color,
            settings.shadow_strength,
            settings.highlight_style,
        )

        public_path = _relpath_safe(final_path, data_dir).as_posix()
        artifact_public = _relpath_safe(artifact_dir, data_dir).as_posix()

        gcs_settings = get_gcs_settings()
        if gcs_settings:
            try:
                upload_object(
                    settings=gcs_settings,
                    object_name=f"{gcs_settings.static_prefix}/{public_path}",
                    source=final_path,
                    content_type="video/mp4",
                )
                transcription_path = artifact_dir / "transcription.json"
                if transcription_path.exists():
                    transcription_rel = _relpath_safe(transcription_path, data_dir).as_posix()
                    upload_object(
                        settings=gcs_settings,
                        object_name=f"{gcs_settings.static_prefix}/{transcription_rel}",
                        source=transcription_path,
                        content_type="application/json",
                    )
            except Exception as exc:
                logger.warning("Failed to upload job artifacts to GCS (%s): %s", job_id, exc)

        result_data = {
            # Store relative paths from data_dir for consistent serving across environments
            "video_path": public_path,  # Same as public_url path (relative to data_dir)
            "artifacts_dir": artifact_public,  # Same as artifact_url path (relative to data_dir)
            "public_url": f"/static/{public_path}",
            "artifact_url": f"/static/{artifact_public}",
            "transcription_url": f"/static/{artifact_public}/transcription.json",
            "social": social.tiktok.title if social else None, # Just storing title for simple view now
            "original_filename": original_name or input_path.name,
            "video_crf": video_crf,
            "model_size": model_size,
            "transcribe_provider": provider,
            "output_size": final_path.stat().st_size if final_path.exists() else 0,
            "resolution": f"{target_width}x{target_height}",
            # Persist styling settings for Export/Re-generation
            "max_subtitle_lines": settings.max_subtitle_lines,
            "subtitle_position": settings.subtitle_position,
            "subtitle_color": settings.subtitle_color,
            "shadow_strength": settings.shadow_strength,
            "highlight_style": settings.highlight_style,
            "subtitle_size": settings.subtitle_size,
            "karaoke_enabled": settings.karaoke_enabled,
            "watermark_enabled": settings.watermark_enabled,
        }
        if source_gcs_object_name:
            result_data["source_gcs_object"] = source_gcs_object_name

        job_store.update_job(job_id, status="completed", progress=100, message="Done!", result_data=result_data)
        _record_event_safe(
            history_store,
            user,
            "process_completed",
            f"Processed {original_name or input_path.name}",
            {
                "job_id": job_id,
                "model_size": model_size,
                "provider": provider,
                "video_crf": video_crf,
                "output": result_data.get("public_url"),
                "artifacts": result_data.get("artifact_url"),
            },
        )

    except InterruptedError as exc:
        job_store.update_job(job_id, status="cancelled", message="Cancelled by user")
        _record_event_safe(
            history_store,
            user,
            "process_cancelled",
            f"Processing cancelled for {original_name or input_path.name}",
            {"job_id": job_id, "error": str(exc)},
        )
        _refund_charge_best_effort(points_store, charge, status="cancelled", error=str(exc))
    except Exception as exc:
        job_store.update_job(job_id, status="failed", message=str(exc))
        _record_event_safe(
            history_store,
            user,
            "process_failed",
            f"Processing failed for {original_name or input_path.name}",
            {"job_id": job_id, "error": str(exc)},
        )
        _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))


def run_gcs_video_processing(
    *,
    job_id: str,
    gcs_object_name: str,
    input_path: Path,
    output_path: Path,
    artifact_dir: Path,
    settings: ProcessingSettings,
    job_store: JobStore,
    history_store: HistoryStore | None = None,
    user: User | None = None,
    original_name: str | None = None,
    points_store: PointsStore | None = None,
    charge: _ChargeContext | None = None,
) -> None:
    gcs_settings = get_gcs_settings()
    if not gcs_settings:
        job_store.update_job(job_id, status="failed", message="GCS is not configured")
        _refund_charge_best_effort(points_store, charge, status="failed", error="GCS is not configured")
        return

    try:
        current = job_store.get_job(job_id)
        if current and current.status == "cancelled":
            _refund_charge_best_effort(points_store, charge, status="cancelled", error="Job cancelled by user")
            return

        job_store.update_job(job_id, status="processing", progress=0, message="Downloading upload…")
        download_object(
            settings=gcs_settings,
            object_name=gcs_object_name,
            destination=input_path,
            max_bytes=MAX_UPLOAD_BYTES,
        )

        try:
            probe = probe_media(input_path)
        except Exception as exc:
            raise ValueError("Could not validate uploaded media file") from exc

        if probe.duration_s is None or probe.duration_s <= 0:
            raise ValueError("Could not determine video duration")
        if probe.duration_s > config.MAX_VIDEO_DURATION_SECONDS:
            raise ValueError(f"Video too long (max {config.MAX_VIDEO_DURATION_SECONDS/60:.1f} minutes)")

        run_video_processing(
            job_id,
            input_path,
            output_path,
            artifact_dir,
            settings,
            job_store,
            history_store,
            user,
            original_name,
            source_gcs_object_name=gcs_object_name,
            points_store=points_store,
            charge=charge,
        )

        if not gcs_settings.keep_uploads:
            final_job = job_store.get_job(job_id)
            if final_job and final_job.status == "completed":
                try:
                    delete_object(settings=gcs_settings, object_name=gcs_object_name)
                except Exception:
                    pass
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        job_store.update_job(job_id, status="failed", message=str(exc))
        _record_event_safe(
            history_store,
            user,
            "process_failed",
            f"Processing failed for {original_name or gcs_object_name}",
            {"job_id": job_id, "error": str(exc)},
        )
        _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))


@router.post("/process", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
async def process_video(
    background_tasks: BackgroundTasks,
    request: Request,
    file: UploadFile = File(...),
    transcribe_model: str = Form("medium"),
    transcribe_provider: str = Form("local"),
    openai_model: str = Form(""),
    video_quality: str = Form("high quality"),
    video_resolution: str = Form(""),
    use_llm: bool = Form(APP_SETTINGS.use_llm_by_default),
    context_prompt: str = Form(""),
    subtitle_position: int = Form(16),
    max_subtitle_lines: int = Form(2),
    subtitle_color: str | None = Form(None),
    shadow_strength: int = Form(4),
    highlight_style: str = Form("karaoke"),
    subtitle_size: int = Form(100),
    karaoke_enabled: bool = Form(True),
    watermark_enabled: bool = Form(False),
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    points_store: PointsStore = Depends(get_points_store),
    db: Database = Depends(get_db),
):
    """Upload a video and start processing."""
    settings = _build_processing_settings(
        transcribe_model=transcribe_model,
        transcribe_provider=transcribe_provider,
        openai_model=openai_model,
        video_quality=video_quality,
        video_resolution=video_resolution,
        use_llm=use_llm,
        context_prompt=context_prompt,
        subtitle_position=subtitle_position,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_color=subtitle_color,
        shadow_strength=shadow_strength,
        highlight_style=highlight_style,
        subtitle_size=subtitle_size,
        karaoke_enabled=karaoke_enabled,
        watermark_enabled=watermark_enabled,
    )

    # Rate Limiting: Check concurrent jobs
    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many active jobs. Please wait for your current jobs to finish (max {config.MAX_CONCURRENT_JOBS})."
        )

    job_id = str(uuid.uuid4())
    data_dir, uploads_dir, artifacts_root = _data_roots()

    # Save Upload
    filename = file.filename or ""
    file_ext = Path(filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(400, "Invalid file type")

    input_path = uploads_dir / f"{job_id}_input{file_ext}"
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Request too large; limit is {APP_SETTINGS.max_upload_mb}MB",
                )
        except ValueError:
            pass
    _save_upload_with_limit(file, input_path)

    # Validate Duration
    try:
        probe = probe_media(input_path)
    except Exception as exc:
        input_path.unlink(missing_ok=True)
        logger.warning("Failed to probe uploaded media; rejecting upload: %s", exc)
        raise HTTPException(status_code=400, detail="Could not validate uploaded media file")

    if probe.duration_s is None or probe.duration_s <= 0:
        input_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Could not determine video duration")

    if probe.duration_s > config.MAX_VIDEO_DURATION_SECONDS:
        input_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail=f"Video too long (max {config.MAX_VIDEO_DURATION_SECONDS/60:.1f} minutes)",
        )

    cost = process_video_cost(settings.transcribe_model)
    charge = _ChargeContext(
        user_id=current_user.id,
        cost=cost,
        reason="process_video",
        meta={"charge_id": job_id, "job_id": job_id, "model": settings.transcribe_model, "source": "upload"},
    )
    try:
        new_balance = points_store.spend(
            current_user.id,
            cost,
            reason="process_video",
            meta=charge.meta,
        )
    except Exception:
        input_path.unlink(missing_ok=True)
        raise

    # Prepare Output
    output_path = artifacts_root / job_id / "processed.mp4"
    artifact_path = artifacts_root / job_id

    try:
        # Create Job
        job = job_store.create_job(job_id, current_user.id)
        _record_event_safe(
            history_store,
            current_user,
            "process_started",
            f"Queued {file.filename}",
            {
                "job_id": job_id,
                "model_size": settings.transcribe_model,
                "provider": settings.transcribe_provider or "local",
                "video_quality": settings.video_quality,
                "video_resolution": video_resolution,
                "use_llm": use_llm,
            },
        )

        # Enqueue Task
        logger.debug(
            "Received process request: max_subtitle_lines=%s highlight_style=%s",
            max_subtitle_lines,
            highlight_style,
        )

        gcs_settings = get_gcs_settings()
        source_gcs_object_name: str | None = None
        if gcs_settings:
            source_gcs_object_name = f"{gcs_settings.uploads_prefix}/{current_user.id}/{job_id}{file_ext}"

        processing_kwargs: dict[str, Any] = {}
        if source_gcs_object_name:
            processing_kwargs["source_gcs_object_name"] = source_gcs_object_name

        background_tasks.add_task(
            run_video_processing,
            job_id,
            input_path,
            output_path,
            artifact_path,
            settings,
            job_store,
            history_store,
            current_user,
            file.filename,
            points_store=points_store,
            charge=charge,
            db=db,
            **processing_kwargs,
        )

        if gcs_settings and source_gcs_object_name:
            background_tasks.add_task(
                upload_object,
                settings=gcs_settings,
                object_name=source_gcs_object_name,
                source=input_path,
                content_type=file.content_type or "application/octet-stream",
            )

        # Trigger Cleanup
        from ...common.cleanup import cleanup_old_uploads

        background_tasks.add_task(
            cleanup_old_uploads,
            uploads_dir,
            24,  # 24 hours retention
        )
    except Exception as exc:
        _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))
        input_path.unlink(missing_ok=True)
        raise

    return {**job.__dict__, "balance": new_balance}


class GcsUploadUrlRequest(BaseModel):
    filename: str = Field(..., max_length=255)
    content_type: str = Field(..., max_length=100)
    size_bytes: int = Field(..., ge=1)


class GcsUploadUrlResponse(BaseModel):
    upload_id: str
    object_name: str
    upload_url: str
    expires_at: int
    required_headers: dict[str, str]


@router.post("/gcs/upload-url", response_model=GcsUploadUrlResponse, dependencies=[Depends(limiter_processing)])
def create_gcs_upload_url(
    payload: GcsUploadUrlRequest,
    current_user: User = Depends(get_current_user),
    gcs_upload_store: GcsUploadStore = Depends(get_gcs_upload_store),
    history_store: HistoryStore = Depends(get_history_store),
) -> Any:
    """Create a signed upload URL for direct-to-GCS uploads (Cloud Run safe)."""
    gcs_settings = get_gcs_settings()
    if not gcs_settings:
        raise HTTPException(status_code=503, detail="GCS uploads are not configured")

    file_ext = Path(payload.filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid file type")

    if payload.size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large; limit is {APP_SETTINGS.max_upload_mb}MB",
        )

    content_type = _validate_upload_content_type(payload.content_type)

    object_name = f"{gcs_settings.uploads_prefix}/{current_user.id}/{uuid.uuid4().hex}{file_ext}"
    session = gcs_upload_store.issue_upload(
        user_id=current_user.id,
        object_name=object_name,
        content_type=content_type,
        original_filename=payload.filename,
        ttl_seconds=gcs_settings.upload_url_ttl_seconds,
    )

    try:
        upload_url = generate_signed_upload_url(
            settings=gcs_settings,
            object_name=object_name,
            content_type=content_type,
            content_length=payload.size_bytes,
        )
    except Exception as exc:
        logger.warning("Failed to generate GCS signed upload URL: %s", exc)
        raise HTTPException(status_code=503, detail="Could not generate signed upload URL")

    _record_event_safe(
        history_store,
        current_user,
        "gcs_upload_url_issued",
        f"Issued GCS upload URL for {payload.filename}",
        {
            "object_name": object_name,
            "content_type": content_type,
            "size_bytes": payload.size_bytes,
        },
    )

    return {
        "upload_id": session.id,
        "object_name": object_name,
        "upload_url": upload_url,
        "expires_at": session.expires_at,
        "required_headers": {
            "Content-Type": content_type,
            "Content-Length": str(payload.size_bytes),
        },
    }


class GcsProcessRequest(BaseModel):
    upload_id: str = Field(..., max_length=128)
    transcribe_model: str = Field("medium", max_length=50)
    transcribe_provider: str = Field("local", max_length=50)
    openai_model: str = Field("", max_length=50)
    video_quality: str = Field("high quality", max_length=50)
    video_resolution: str = Field("", max_length=50)
    use_llm: bool = APP_SETTINGS.use_llm_by_default
    context_prompt: str = Field("", max_length=5000)
    subtitle_position: int = 16
    max_subtitle_lines: int = 2
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int = 4
    highlight_style: str = Field("karaoke", max_length=20)
    subtitle_size: int = 100
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


@router.post("/gcs/process", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
def process_video_from_gcs(
    payload: GcsProcessRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    gcs_upload_store: GcsUploadStore = Depends(get_gcs_upload_store),
    points_store: PointsStore = Depends(get_points_store),
) -> Any:
    """Start processing for an already-uploaded GCS object (via upload_id)."""
    gcs_settings = get_gcs_settings()
    if not gcs_settings:
        raise HTTPException(status_code=503, detail="GCS uploads are not configured")

    # Rate Limiting: Check concurrent jobs
    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many active jobs. Please wait for your current jobs to finish (max {config.MAX_CONCURRENT_JOBS}).",
        )

    session = gcs_upload_store.consume_upload(upload_id=payload.upload_id, user_id=current_user.id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload not found or expired")

    settings = _build_processing_settings(
        transcribe_model=payload.transcribe_model,
        transcribe_provider=payload.transcribe_provider,
        openai_model=payload.openai_model,
        video_quality=payload.video_quality,
        video_resolution=payload.video_resolution,
        use_llm=payload.use_llm,
        context_prompt=payload.context_prompt,
        subtitle_position=payload.subtitle_position,
        max_subtitle_lines=payload.max_subtitle_lines,
        subtitle_color=payload.subtitle_color,
        shadow_strength=payload.shadow_strength,
        highlight_style=payload.highlight_style,
        subtitle_size=payload.subtitle_size,
        karaoke_enabled=payload.karaoke_enabled,
        watermark_enabled=payload.watermark_enabled,
    )

    job_id = str(uuid.uuid4())
    _, uploads_dir, artifacts_root = _data_roots()

    file_ext = Path(session.original_filename).suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid original filename extension")

    input_path = uploads_dir / f"{job_id}_input{file_ext}"
    output_path = artifacts_root / job_id / "processed.mp4"
    artifact_path = artifacts_root / job_id

    cost = process_video_cost(settings.transcribe_model)
    charge = _ChargeContext(
        user_id=current_user.id,
        cost=cost,
        reason="process_video",
        meta={"charge_id": job_id, "job_id": job_id, "model": settings.transcribe_model, "source": "gcs"},
    )
    new_balance = points_store.spend(
        current_user.id,
        cost,
        reason=charge.reason,
        meta=charge.meta,
    )

    try:
        job = job_store.create_job(job_id, current_user.id)
        _record_event_safe(
            history_store,
            current_user,
            "process_started",
            f"Queued {session.original_filename}",
            {
                "job_id": job_id,
                "provider": settings.transcribe_provider,
                "model_size": settings.transcribe_model,
                "video_quality": settings.video_quality,
                "source": "gcs",
            },
        )

        background_tasks.add_task(
            run_gcs_video_processing,
            job_id=job_id,
            gcs_object_name=session.object_name,
            input_path=input_path,
            output_path=output_path,
            artifact_dir=artifact_path,
            settings=settings,
            job_store=job_store,
            history_store=history_store,
            user=current_user,
            original_name=session.original_filename,
            points_store=points_store,
            charge=charge,
        )

        from ...common.cleanup import cleanup_old_uploads

        background_tasks.add_task(
            cleanup_old_uploads,
            uploads_dir,
            24,
        )
    except Exception as exc:
        _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))
        raise

    return {**job.__dict__, "balance": new_balance}


def _ensure_job_size(job):
    """Helper to backfill output_size for legacy jobs."""
    if job.status == "completed" and job.result_data:
        if not job.result_data.get("output_size"):
             video_path = job.result_data.get("video_path")
             if video_path:
                 try:
                     # Try data_dir first (new format), then fallback to PROJECT_ROOT.parent (legacy)
                     full_path = DATA_DIR / video_path
                     if not full_path.exists():
                         full_path = config.PROJECT_ROOT.parent / video_path
                     if full_path.exists():
                         # Update in-memory object (and potentially could save back, but for now just serving)
                         job.result_data["output_size"] = full_path.stat().st_size
                 except Exception as e:
                     logger.warning(f"Failed to ensure job size: {e}")
    return job

@router.get("/jobs", response_model=List[JobResponse])
def list_jobs(
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    jobs = job_store.list_jobs_for_user(current_user.id)
    return [_ensure_job_size(job) for job in jobs]


@router.get("/jobs/paginated", response_model=PaginatedJobsResponse)
def list_jobs_paginated(
    page: int = 1,
    page_size: int = 5,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    """List jobs with pagination support."""
    # Validate parameters
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if page_size > 100:
        page_size = 100  # Cap at 100 to prevent abuse

    offset = (page - 1) * page_size
    total = job_store.count_jobs_for_user(current_user.id)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    jobs = job_store.list_jobs_for_user_paginated(current_user.id, offset=offset, limit=page_size)
    items = [_ensure_job_size(job) for job in jobs]

    return PaginatedJobsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/jobs/batch-delete", response_model=BatchDeleteResponse)
def batch_delete_jobs(
    request: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Delete multiple jobs at once."""
    import shutil

    if not request.job_ids:
        return BatchDeleteResponse(status="success", deleted_count=0, job_ids=[])

    # Limit batch size to prevent abuse
    if len(request.job_ids) > 50:
        raise HTTPException(400, "Cannot delete more than 50 jobs at once")

    data_dir, uploads_dir, artifacts_root = _data_roots()
    deleted_ids = []

    # First verify ownership and delete files for each job
    for job_id in request.job_ids:
        job = job_store.get_job(job_id)
        if job and job.user_id == current_user.id:
            # Delete artifact directory
            artifact_dir = artifacts_root / job_id
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir, ignore_errors=True)

            # Delete input files
            for ext in [".mp4", ".mov", ".mkv"]:
                input_file = uploads_dir / f"{job_id}_input{ext}"
                if input_file.exists():
                    input_file.unlink(missing_ok=True)

            deleted_ids.append(job_id)

    # Batch delete from database
    deleted_count = job_store.delete_jobs(deleted_ids, current_user.id)

    # Record batch deletion in history
    if deleted_count > 0:
        _record_event_safe(
            history_store,
            current_user,
            "jobs_batch_deleted",
            f"Deleted {deleted_count} jobs",
            {"job_ids": deleted_ids, "count": deleted_count},
        )

    return BatchDeleteResponse(
        status="deleted",
        deleted_count=deleted_count,
        job_ids=deleted_ids
    )

@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")
    return _ensure_job_size(job)

class TranscriptionWordRequest(BaseModel):
    start: float
    end: float
    text: str = Field(..., max_length=100)


class TranscriptionCueRequest(BaseModel):
    start: float
    end: float
    text: str = Field(..., max_length=2000)
    words: list[TranscriptionWordRequest] | None = Field(None, max_length=100)


class UpdateTranscriptionRequest(BaseModel):
    cues: list[TranscriptionCueRequest] = Field(..., max_length=5000)


@router.put("/jobs/{job_id}/transcription", dependencies=[Depends(limiter_content)])
def update_transcription(
    job_id: str,
    request: UpdateTranscriptionRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
):
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    _, _, artifacts_root = _data_roots()
    artifacts_root_resolved = artifacts_root.resolve()
    artifact_dir = (artifacts_root / job_id).resolve()
    if not artifact_dir.is_relative_to(artifacts_root_resolved):
        raise HTTPException(status_code=400, detail="Invalid job id")

    transcription_json = artifact_dir / "transcription.json"
    if not transcription_json.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")

    import json

    payload = [cue.model_dump() for cue in request.cues]
    tmp_path = transcription_json.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(transcription_json)

    result_data = job.result_data.copy() if job.result_data else {}
    result_data["transcription_edited"] = True
    job_store.update_job(job_id, result_data=result_data)

    return {"status": "ok"}


@router.delete("/jobs/{job_id}")
def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Delete a job and its associated files."""
    import shutil

    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    # Delete associated files
    data_dir, uploads_dir, artifacts_root = _data_roots()

    # Delete artifact directory
    artifact_dir = artifacts_root / job_id
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir, ignore_errors=True)

    # Delete input files
    for ext in [".mp4", ".mov", ".mkv"]:
        input_file = uploads_dir / f"{job_id}_input{ext}"
        if input_file.exists():
            input_file.unlink(missing_ok=True)

    # Delete job from store
    job_store.delete_job(job_id)

    # Record deletion in history
    _record_event_safe(
        history_store,
        current_user,
        "job_deleted",
        f"Deleted job {job_id}",
        {"job_id": job_id},
    )

    return {"status": "deleted", "job_id": job_id}


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Cancel a processing job."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    # Only allow cancelling pending or processing jobs
    if job.status not in ("pending", "processing"):
        raise HTTPException(400, f"Cannot cancel job with status '{job.status}'")

    job_store.update_job(job_id, status="cancelled", message="Cancelled by user")

    _record_event_safe(
        history_store,
        current_user,
        "job_cancelled",
        f"Cancelled job {job_id}",
        {"job_id": job_id},
    )

    updated_job = job_store.get_job(job_id)
    return _ensure_job_size(updated_job)


class ReprocessRequest(BaseModel):
    transcribe_model: str = Field("medium", max_length=50)
    transcribe_provider: str = Field("local", max_length=50)
    openai_model: str = Field("", max_length=50)
    video_quality: str = Field("high quality", max_length=50)
    video_resolution: str = Field("", max_length=50)
    use_llm: bool = APP_SETTINGS.use_llm_by_default
    context_prompt: str = Field("", max_length=5000)
    subtitle_position: int = 16
    max_subtitle_lines: int = 2
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int = 4
    highlight_style: str = Field("karaoke", max_length=20)
    subtitle_size: int = 100
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


@router.post("/jobs/{job_id}/reprocess", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
def reprocess_job(
    job_id: str,
    request: ReprocessRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    points_store: PointsStore = Depends(get_points_store),
):
    source_job = job_store.get_job(job_id)
    if not source_job or source_job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if source_job.status != "completed":
        raise HTTPException(status_code=400, detail="Job must be completed to reprocess")

    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail=f"Too many active jobs. Please wait for your current jobs to finish (max {config.MAX_CONCURRENT_JOBS}).",
        )

    settings = _build_processing_settings(
        transcribe_model=request.transcribe_model,
        transcribe_provider=request.transcribe_provider,
        openai_model=request.openai_model,
        video_quality=request.video_quality,
        video_resolution=request.video_resolution,
        use_llm=request.use_llm,
        context_prompt=request.context_prompt,
        subtitle_position=request.subtitle_position,
        max_subtitle_lines=request.max_subtitle_lines,
        subtitle_color=request.subtitle_color,
        shadow_strength=request.shadow_strength,
        highlight_style=request.highlight_style,
        subtitle_size=request.subtitle_size,
        karaoke_enabled=request.karaoke_enabled,
        watermark_enabled=request.watermark_enabled,
    )

    data_dir, uploads_dir, artifacts_root = _data_roots()

    gcs_settings = get_gcs_settings()
    source_gcs_object = (source_job.result_data or {}).get("source_gcs_object")
    if (
        gcs_settings
        and isinstance(source_gcs_object, str)
        and source_gcs_object.startswith(f"{gcs_settings.uploads_prefix}/{current_user.id}/")
    ):
        file_ext = Path(source_gcs_object).suffix.lower()
        if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Invalid source video extension")

        new_job_id = str(uuid.uuid4())
        input_path = uploads_dir / f"{new_job_id}_input{file_ext}"
        output_path = artifacts_root / new_job_id / "processed.mp4"
        artifact_path = artifacts_root / new_job_id

        cost = process_video_cost(settings.transcribe_model)
        charge = _ChargeContext(
            user_id=current_user.id,
            cost=cost,
            reason="process_video",
            meta={
                "charge_id": new_job_id,
                "job_id": new_job_id,
                "model": settings.transcribe_model,
                "action": "reprocess",
                "source_job_id": job_id,
                "source": "gcs",
            },
        )
        new_balance = points_store.spend(
            current_user.id,
            cost,
            reason=charge.reason,
            meta=charge.meta,
        )

        try:
            job = job_store.create_job(new_job_id, current_user.id)
            _record_event_safe(
                history_store,
                current_user,
                "process_started",
                f"Reprocessing {source_job.result_data.get('original_filename', 'video') if source_job.result_data else 'video'}",
                {
                    "job_id": new_job_id,
                    "source_job_id": job_id,
                    "provider": settings.transcribe_provider,
                    "model_size": settings.transcribe_model,
                    "source": "gcs",
                },
            )

            background_tasks.add_task(
                run_gcs_video_processing,
                job_id=new_job_id,
                gcs_object_name=source_gcs_object,
                input_path=input_path,
                output_path=output_path,
                artifact_dir=artifact_path,
                settings=settings,
                job_store=job_store,
                history_store=history_store,
                user=current_user,
                original_name=(source_job.result_data or {}).get("original_filename"),
                points_store=points_store,
                charge=charge,
            )

            from ...common.cleanup import cleanup_old_uploads

            background_tasks.add_task(
                cleanup_old_uploads,
                uploads_dir,
                24,
            )
        except Exception as exc:
            _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))
            raise

        return {**job.__dict__, "balance": new_balance}

    source_input: Path | None = None
    for ext in sorted(ALLOWED_VIDEO_EXTENSIONS):
        candidate = uploads_dir / f"{job_id}_input{ext}"
        if candidate.exists():
            source_input = candidate
            break

    if not source_input:
        candidate_rel = (source_job.result_data or {}).get("video_path")
        if isinstance(candidate_rel, str) and candidate_rel:
            candidate = (data_dir / candidate_rel).resolve()
            data_dir_resolved = data_dir.resolve()
            if candidate.is_relative_to(data_dir_resolved) and candidate.exists():
                source_input = candidate

    if not source_input:
        raise HTTPException(status_code=404, detail="Source video not found; upload again to reprocess")

    file_ext = source_input.suffix.lower()
    if file_ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Invalid source video extension")

    size_bytes = source_input.stat().st_size
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="Empty source video")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large; limit is {APP_SETTINGS.max_upload_mb}MB",
        )

    try:
        probe = probe_media(source_input)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not validate source media file") from exc

    if probe.duration_s is None or probe.duration_s <= 0:
        raise HTTPException(status_code=400, detail="Could not determine video duration")
    if probe.duration_s > config.MAX_VIDEO_DURATION_SECONDS:
        raise HTTPException(
            status_code=400,
            detail=f"Video too long (max {config.MAX_VIDEO_DURATION_SECONDS/60:.1f} minutes)",
        )

    new_job_id = str(uuid.uuid4())
    input_path = uploads_dir / f"{new_job_id}_input{file_ext}"
    output_path = artifacts_root / new_job_id / "processed.mp4"
    artifact_path = artifacts_root / new_job_id

    try:
        _link_or_copy_file(source_input, input_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Source video not found; upload again to reprocess")

    cost = process_video_cost(settings.transcribe_model)
    charge = _ChargeContext(
        user_id=current_user.id,
        cost=cost,
        reason="process_video",
        meta={
            "charge_id": new_job_id,
            "job_id": new_job_id,
            "model": settings.transcribe_model,
            "action": "reprocess",
            "source_job_id": job_id,
            "source": "local",
        },
    )
    try:
        new_balance = points_store.spend(
            current_user.id,
            cost,
            reason="process_video",
            meta=charge.meta,
        )
    except Exception:
        input_path.unlink(missing_ok=True)
        raise

    try:
        job = job_store.create_job(new_job_id, current_user.id)
        _record_event_safe(
            history_store,
            current_user,
            "process_started",
            f"Reprocessing {source_job.result_data.get('original_filename', 'video') if source_job.result_data else 'video'}",
            {
                "job_id": new_job_id,
                "source_job_id": job_id,
                "provider": settings.transcribe_provider,
                "model_size": settings.transcribe_model,
                "source": "local",
            },
        )

        background_tasks.add_task(
            run_video_processing,
            new_job_id,
            input_path,
            output_path,
            artifact_path,
            settings,
            job_store,
            history_store,
            current_user,
            (source_job.result_data or {}).get("original_filename"),
            points_store=points_store,
            charge=charge,
        )

        from ...common.cleanup import cleanup_old_uploads

        background_tasks.add_task(
            cleanup_old_uploads,
            uploads_dir,
            24,
        )
    except Exception as exc:
        _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))
        input_path.unlink(missing_ok=True)
        raise

    return {**job.__dict__, "balance": new_balance}





@router.post("/jobs/{job_id}/fact-check", response_model=FactCheckResponse, dependencies=[Depends(limiter_content)])
def fact_check_video(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    points_store: PointsStore = Depends(get_points_store),
    db: Database = Depends(get_db),
):
    """Analyze transcript for historical or factual correctness."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to fact check")

    _, _, artifacts_root = _data_roots()
    artifact_dir = artifacts_root / job_id
    transcript_path = artifact_dir / "transcript.txt"

    if not transcript_path.exists():
        raise HTTPException(404, "Transcript not found for this job")

    from ...services.subtitles import generate_fact_check

    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
        charge = _ChargeContext(
            user_id=current_user.id,
            cost=FACT_CHECK_COST,
            reason="fact_check",
            meta={"charge_id": uuid.uuid4().hex, "job_id": job_id},
        )
        new_balance = points_store.spend(
            current_user.id,
            FACT_CHECK_COST,
            reason=charge.reason,
            meta=charge.meta,
        )

        try:
            with db.session() as session:
                result = generate_fact_check(transcript_text, session=session, job_id=job_id)
        except Exception as exc:
            _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))
            raise

        return FactCheckResponse(
            items=[
                {
                    "mistake": item.mistake,
                    "correction": item.correction,
                    "explanation": item.explanation,
                    "severity": item.severity,
                    "confidence": item.confidence,
                    "real_life_example": item.real_life_example,
                    "scientific_evidence": item.scientific_evidence,
                }
                for item in result.items
            ],
            truth_score=result.truth_score,
            supported_claims_pct=result.supported_claims_pct,
            claims_checked=result.claims_checked,
            balance=new_balance,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in fact_check_video")
        raise HTTPException(500, f"Failed to fact check: {str(e)}")


@router.post("/jobs/{job_id}/social-copy", response_model=SocialCopyResponse, dependencies=[Depends(limiter_content)])
def generate_social_copy_video(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    points_store: PointsStore = Depends(get_points_store),
    db: Database = Depends(get_db),
):
    """Generate viral social media copy (title, description, tags) for a video."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to generate social copy")

    _, _, artifacts_root = _data_roots()
    artifact_dir = artifacts_root / job_id
    transcript_path = artifact_dir / "transcript.txt"

    if not transcript_path.exists():
        raise HTTPException(404, "Transcript not found for this job")

    from ...services.subtitles import build_social_copy_llm
    from ...services.points import SOCIAL_COPY_COST

    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
        charge = _ChargeContext(
            user_id=current_user.id,
            cost=SOCIAL_COPY_COST,
            reason="social_copy",
            meta={"charge_id": uuid.uuid4().hex, "job_id": job_id},
        )
        new_balance = points_store.spend(
            current_user.id,
            SOCIAL_COPY_COST,
            reason=charge.reason,
            meta=charge.meta,
        )

        try:
            # Generate the copy
            with db.session() as session:
                social_copy = build_social_copy_llm(transcript_text, session=session, job_id=job_id)
            
            # Persist it
            social_path = artifact_dir / "social.json"
            social_data = {
                "title": social_copy.generic.title,
                "description": social_copy.generic.description,
                "hashtags": social_copy.generic.hashtags,
            }
            import json
            social_path.write_text(json.dumps(social_data, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as exc:
            _refund_charge_best_effort(points_store, charge, status="failed", error=str(exc))
            raise

        return SocialCopyResponse(
            social_copy={
                "title": social_copy.generic.title,
                "description": social_copy.generic.description,
                "hashtags": social_copy.generic.hashtags,
            },
            balance=new_balance,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate social copy: {str(e)}")


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
    """
    Export a video variant (e.g. 4K) from an existing job.
    """
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to export")

    # Prevent abuse: Check if user has too many active jobs
    # We restrict export if the user is already clogging the queue
    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= config.MAX_CONCURRENT_JOBS:
        raise HTTPException(
            status_code=429,
            detail="System busy. Please wait for your other jobs to finish."
        )

    data_dir, uploads_dir, artifacts_root = _data_roots()
    artifact_dir = artifacts_root / job_id

    if request.resolution == "srt":
        # SRT Export: Fast path, direct generation
        try:
            from ...services.subtitles import _write_srt_from_segments
            
            # 1. Load transcription
            transcription_json = artifact_dir / "transcription.json"
            if not transcription_json.exists():
                raise HTTPException(404, "Transcript not found (cannot export SRT)")
            
            import json
            cues_data = json.loads(transcription_json.read_text(encoding="utf-8"))
            
            # 2. Convert to TimeRange tuples for the helper
            segments = []
            for cue in cues_data:
                # _write_srt_from_segments expects (start, end, text)
                segments.append((cue["start"], cue["end"], cue["text"]))
                
            # 3. Write SRT
            srt_path = artifact_dir / "processed.srt"
            _write_srt_from_segments(segments, srt_path)
            
            # 4. register variant
            result_data = job.result_data.copy() if job.result_data else {}
            variants = result_data.get("variants", {})
            public_path = _relpath_safe(srt_path, data_dir).as_posix()
            variants["srt"] = f"/static/{public_path}"
            result_data["variants"] = variants
            
            # 5. GCS Upload if configured
            gcs_settings = get_gcs_settings()
            if gcs_settings:
                try:
                    upload_object(
                        settings=gcs_settings,
                        object_name=f"{gcs_settings.static_prefix}/{public_path}",
                        source=srt_path,
                        content_type="text/plain", # or application/x-subrip
                    )
                except Exception as exc:
                    logger.warning("Failed to upload SRT export to GCS (%s): %s", job_id, exc)

            job_store.update_job(job_id, result_data=result_data, status="completed")
            updated_job = job_store.get_job(job_id)
            return _ensure_job_size(updated_job)
            
        except Exception as e:
            logger.exception("SRT Export failed")
            raise HTTPException(500, f"SRT Export failed: {str(e)}")

    # Locate original input
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

    from ...services.video_processing import generate_video_variant

    if request.subtitle_position is not None:
        _validate_subtitle_position(request.subtitle_position)
    if request.max_subtitle_lines is not None:
        _validate_max_subtitle_lines(request.max_subtitle_lines)
    if request.shadow_strength is not None:
        _validate_shadow_strength(request.shadow_strength)
    if request.subtitle_size is not None:
        _validate_subtitle_size(request.subtitle_size)
    if request.highlight_style is not None:
        _validate_highlight_style(request.highlight_style)
    if request.subtitle_color and not re.match(r"^&H[0-9A-Fa-f]{8}$", request.subtitle_color):
        raise HTTPException(status_code=400, detail="Invalid subtitle color format (expected &HAABBGGRR)")

    try:
        subtitle_settings = request.model_dump(exclude_defaults=True)
        subtitle_settings.pop("resolution", None)
        if subtitle_settings.get("highlight_style"):
            subtitle_settings["highlight_style"] = _validate_highlight_style(str(subtitle_settings["highlight_style"]))
        if subtitle_settings.get("subtitle_position") is not None:
            subtitle_settings["subtitle_position"] = _validate_subtitle_position(int(subtitle_settings["subtitle_position"]))
        if subtitle_settings.get("max_subtitle_lines") is not None:
            subtitle_settings["max_subtitle_lines"] = _validate_max_subtitle_lines(int(subtitle_settings["max_subtitle_lines"]))
        if subtitle_settings.get("shadow_strength") is not None:
            subtitle_settings["shadow_strength"] = _validate_shadow_strength(int(subtitle_settings["shadow_strength"]))
        if subtitle_settings.get("subtitle_size") is not None:
            subtitle_settings["subtitle_size"] = _validate_subtitle_size(int(subtitle_settings["subtitle_size"]))
        if subtitle_settings.get("subtitle_color") and not re.match(
            r"^&H[0-9A-Fa-f]{8}$", str(subtitle_settings["subtitle_color"])
        ):
            raise HTTPException(status_code=400, detail="Invalid subtitle color format (expected &HAABBGGRR)")

        # Note: This is synchronous/blocking for now as per MVP plan.
        # Ideally this should be a background task that updates job status.
        output_path = generate_video_variant(
            job_id,
            input_video,
            artifact_dir,
            request.resolution,
            job_store,
            current_user.id,
            subtitle_settings=subtitle_settings or None,
        )

        # Update job result data with the new variant info
        # We can store variants in a dict in result_data
        result_data = job.result_data.copy() if job.result_data else {}
        variants = result_data.get("variants", {})

        public_path = _relpath_safe(output_path, data_dir).as_posix()
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

        # We assume the user might want this to be the 'main' video now?
        # Or just return the link.
        # Let's just update variants.

        job_store.update_job(job_id, result_data=result_data, status="completed", progress=100)

        # Reload job
        updated_job = job_store.get_job(job_id)
        return _ensure_job_size(updated_job)

    except Exception as e:
        raise HTTPException(500, f"Export failed: {str(e)}")


@router.post("/jobs/cleanup")
def run_retention_policy(
    days: int = 30,
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    current_user: User = Depends(get_current_user),
):
    """
    Manually trigger retention policy: Delete jobs older than {days} days.
    Ideally protected by admin auth or run via CLI/Cron.
    """
    import os
    import shutil
    import time

    # Security: Only allow admins to trigger cleanup
    admin_emails_str = os.getenv("GSP_ADMIN_EMAILS", "")
    admin_emails = [e.strip().lower() for e in admin_emails_str.split(",") if e.strip()]

    if not admin_emails:
        # Secure default: If no admins are configured, disable the endpoint
        raise HTTPException(status_code=403, detail="Admin access not configured")

    if current_user.email.strip().lower() not in admin_emails:
        raise HTTPException(status_code=403, detail="Not authorized")

    cutoff = int(time.time()) - (days * 24 * 3600)
    old_jobs = job_store.list_jobs_created_before(cutoff)

    if not old_jobs:
        return {"status": "success", "deleted_count": 0, "message": "No old jobs found"}

    data_dir, uploads_dir, artifacts_root = _data_roots()
    deleted_ids = []

    for job in old_jobs:
        # Delete artifacts
        artifact_dir = artifacts_root / job.id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)

        # Delete inputs
        for ext in [".mp4", ".mov", ".mkv"]:
            input_file = uploads_dir / f"{job.id}_input{ext}"
            if input_file.exists():
                input_file.unlink(missing_ok=True)

        deleted_ids.append(job.id)

    # Delete from DB
    # Note: Using private method or list comprehension + delete_jobs if needed.
    # delete_jobs takes user_id for safety. Here we are system admin.
    # We'll use delete_job in loop or add delete_jobs_system to store.
    # Using existing delete_job works but it's one-by-one DB calls.
    # For efficiency we could act directly, but loop is fine for now.
    for job_id in deleted_ids:
        job_store.delete_job(job_id)

    return {
        "status": "success",
        "deleted_count": len(deleted_ids),
        "message": f"Deleted {len(deleted_ids)} jobs older than {days} days"
    }
