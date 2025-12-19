"""Background processing tasks for video processing endpoints."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core import config
from ...core.auth import User
from ...core.database import Database
from ...core.errors import sanitize_message
from ...core.gcs import delete_object, download_object, get_gcs_settings, upload_object
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.points import PointsStore, make_idempotency_id
from ...services.ffmpeg_utils import probe_media
from ...services.video_processing import normalize_and_stub_subtitles
from .file_utils import MAX_UPLOAD_BYTES, data_roots, relpath_safe
from .settings import ProcessingSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChargeContext:
    """Context for tracking charges that may need refunds."""

    user_id: str
    cost: int
    reason: str
    meta: dict[str, Any] | None


def refund_charge_best_effort(
    points_store: PointsStore | None,
    charge: ChargeContext | None,
    *,
    status: str,
    error: str | None = None,
) -> None:
    """Best-effort refund of a charge. Never raises."""
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


def record_event_safe(
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
    charge: ChargeContext | None = None,
    db: Database | None = None,
) -> None:
    """Background task to run the heavy video processing."""
    try:
        current = job_store.get_job(job_id)
        if current and current.status == "cancelled":
            raise InterruptedError("Job cancelled by user")

        job_store.update_job(job_id, status="processing", progress=0, message="Starting processing...")

        last_update_time = 0.0
        last_check_time = 0.0

        def progress_callback(msg: str, percent: float) -> None:
            nonlocal last_update_time
            now = time.time()
            if percent <= 0 or percent >= 100 or (now - last_update_time) >= 1.0:
                job_store.update_job(job_id, progress=int(percent), message=msg)
                last_update_time = now

        def check_cancelled() -> None:
            """Check if job was cancelled by user."""
            nonlocal last_check_time
            now = time.monotonic()
            if now - last_check_time < 0.5:
                return

            current_job = job_store.get_job(job_id)
            last_check_time = now
            if current_job and current_job.status == "cancelled":
                raise InterruptedError("Job cancelled by user")

        data_dir, _, _ = data_roots()

        # Map settings to internal params
        model_size = settings.openai_model or settings.transcribe_model
        provider = settings.transcribe_provider or "local"
        crf_map = {"low size": 28, "balanced": 20, "high quality": 12}
        video_crf = crf_map.get(settings.video_quality.lower(), 12)
        target_width = settings.target_width
        target_height = settings.target_height

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

        public_path = relpath_safe(final_path, data_dir).as_posix()
        artifact_public = relpath_safe(artifact_dir, data_dir).as_posix()

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
                    transcription_rel = relpath_safe(transcription_path, data_dir).as_posix()
                    upload_object(
                        settings=gcs_settings,
                        object_name=f"{gcs_settings.static_prefix}/{transcription_rel}",
                        source=transcription_path,
                        content_type="application/json",
                    )
            except Exception as exc:
                logger.warning("Failed to upload job artifacts to GCS (%s): %s", job_id, exc)

        result_data = {
            "video_path": public_path,
            "artifacts_dir": artifact_public,
            "public_url": f"/static/{public_path}",
            "artifact_url": f"/static/{artifact_public}",
            "transcription_url": f"/static/{artifact_public}/transcription.json",
            "social": social.tiktok.title if social else None,
            "original_filename": original_name or input_path.name,
            "video_crf": video_crf,
            "model_size": model_size,
            "transcribe_provider": provider,
            "output_size": final_path.stat().st_size if final_path.exists() else 0,
            "resolution": f"{target_width}x{target_height}",
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
        record_event_safe(
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
        record_event_safe(
            history_store,
            user,
            "process_cancelled",
            f"Processing cancelled for {original_name or input_path.name}",
            {"job_id": job_id, "error": sanitize_message(str(exc))},
        )
        refund_charge_best_effort(points_store, charge, status="cancelled", error=sanitize_message(str(exc)))
    except Exception as exc:
        safe_msg = sanitize_message(str(exc))
        job_store.update_job(job_id, status="failed", message=safe_msg)
        record_event_safe(
            history_store,
            user,
            "process_failed",
            f"Processing failed for {original_name or input_path.name}",
            {"job_id": job_id, "error": safe_msg},
        )
        refund_charge_best_effort(points_store, charge, status="failed", error=safe_msg)


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
    charge: ChargeContext | None = None,
) -> None:
    """Background task to process a video from GCS."""
    gcs_settings = get_gcs_settings()
    if not gcs_settings:
        job_store.update_job(job_id, status="failed", message="GCS is not configured")
        refund_charge_best_effort(points_store, charge, status="failed", error="GCS is not configured")
        return

    try:
        current = job_store.get_job(job_id)
        if current and current.status == "cancelled":
            refund_charge_best_effort(points_store, charge, status="cancelled", error="Job cancelled by user")
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
        safe_msg = sanitize_message(str(exc))
        job_store.update_job(job_id, status="failed", message=safe_msg)
        record_event_safe(
            history_store,
            user,
            "process_failed",
            f"Processing failed for {original_name or gcs_object_name}",
            {"job_id": job_id, "error": safe_msg},
        )
        refund_charge_best_effort(points_store, charge, status="failed", error=safe_msg)
