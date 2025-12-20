"""Reprocess and admin routes."""

from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...core import config
from ...core.auth import User
from ...core.errors import sanitize_message
from ...core.gcs import get_gcs_settings
from ...core.ratelimit import limiter_processing
from ...core.settings import load_app_settings
from ...schemas.base import JobResponse
from ...schemas.usage import UsageSummaryResponse, UsageSummaryRow
from ...services import pricing
from ...services.charge_plans import reserve_processing_charges
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.usage_ledger import UsageLedgerStore
from ...services.ffmpeg_utils import probe_media
from ..deps import get_current_user, get_history_store, get_job_store, get_usage_ledger_store
from .file_utils import MAX_UPLOAD_BYTES, data_roots, link_or_copy_file
from .processing_tasks import record_event_safe, refund_charge_best_effort, run_gcs_video_processing, run_video_processing
from .settings import build_processing_settings
from .validation import ALLOWED_VIDEO_EXTENSIONS


logger = logging.getLogger(__name__)
router = APIRouter()

APP_SETTINGS = load_app_settings()


def _ensure_admin(current_user: User) -> None:
    admin_emails_str = os.getenv("GSP_ADMIN_EMAILS", "")
    admin_emails = [e.strip().lower() for e in admin_emails_str.split(",") if e.strip()]

    if not admin_emails:
        raise HTTPException(status_code=403, detail="Admin access not configured")

    if current_user.email.strip().lower() not in admin_emails:
        raise HTTPException(status_code=403, detail="Not authorized")


class ReprocessRequest(BaseModel):
    transcribe_model: str = Field(config.DEFAULT_TRANSCRIBE_TIER, max_length=50)
    transcribe_provider: str = Field(config.TRANSCRIBE_TIER_PROVIDER[config.DEFAULT_TRANSCRIBE_TIER], max_length=50)
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
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
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

    settings = build_processing_settings(
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

    data_dir, uploads_dir, artifacts_root = data_roots()

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

        job = job_store.create_job(new_job_id, current_user.id)
        
        try:
            llm_models = pricing.resolve_llm_models(settings.transcribe_model)
            charge_plan, new_balance = reserve_processing_charges(
                ledger_store=ledger_store,
                user_id=current_user.id,
                job_id=new_job_id,
                tier=settings.transcribe_model,
                duration_seconds=float(config.MAX_VIDEO_DURATION_SECONDS),
                use_llm=settings.use_llm,
                llm_model=llm_models.social,
                provider=settings.transcribe_provider,
                stt_model=pricing.resolve_transcribe_model(settings.transcribe_model),
            )
        except Exception:
            job_store.delete_job(new_job_id)
            raise

        try:
            # Job already created above

            record_event_safe(
                history_store, current_user, "process_started",
                f"Reprocessing {source_job.result_data.get('original_filename', 'video') if source_job.result_data else 'video'}",
                {"job_id": new_job_id, "source_job_id": job_id, "provider": settings.transcribe_provider, "model_size": settings.transcribe_model, "source": "gcs"},
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
                ledger_store=ledger_store,
                charge_plan=charge_plan,
            )

            from ...core.cleanup import cleanup_old_uploads
            background_tasks.add_task(cleanup_old_uploads, uploads_dir, 24)
        except Exception as exc:
            refund_charge_best_effort(ledger_store, charge_plan, status="failed", error=sanitize_message(str(exc)))
            raise

        return {**job.__dict__, "balance": new_balance}

    # Local file reprocessing
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
        raise HTTPException(status_code=413, detail=f"File too large; limit is {APP_SETTINGS.max_upload_mb}MB")

    try:
        probe = probe_media(source_input)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not validate source media file") from exc

    if probe.duration_s is None or probe.duration_s <= 0:
        raise HTTPException(status_code=400, detail="Could not determine video duration")
    if probe.duration_s > config.MAX_VIDEO_DURATION_SECONDS:
        raise HTTPException(status_code=400, detail=f"Video too long (max {config.MAX_VIDEO_DURATION_SECONDS/60:.1f} minutes)")

    new_job_id = str(uuid.uuid4())
    input_path = uploads_dir / f"{new_job_id}_input{file_ext}"
    output_path = artifacts_root / new_job_id / "processed.mp4"
    artifact_path = artifacts_root / new_job_id

    try:
        link_or_copy_file(source_input, input_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Source video not found; upload again to reprocess")

    job = job_store.create_job(new_job_id, current_user.id)

    try:
        llm_models = pricing.resolve_llm_models(settings.transcribe_model)
        charge_plan, new_balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=current_user.id,
            job_id=new_job_id,
            tier=settings.transcribe_model,
            duration_seconds=float(probe.duration_s or 0),
            use_llm=settings.use_llm,
            llm_model=llm_models.social,
            provider=settings.transcribe_provider,
            stt_model=pricing.resolve_transcribe_model(settings.transcribe_model),
        )
    except Exception:
        job_store.delete_job(new_job_id)
        input_path.unlink(missing_ok=True)
        raise


    try:
        # Job already created above
        record_event_safe(
            history_store, current_user, "process_started",
            f"Reprocessing {source_job.result_data.get('original_filename', 'video') if source_job.result_data else 'video'}",
            {"job_id": new_job_id, "source_job_id": job_id, "provider": settings.transcribe_provider, "model_size": settings.transcribe_model, "source": "local"},
        )

        background_tasks.add_task(
            run_video_processing,
            new_job_id, input_path, output_path, artifact_path, settings,
            job_store, history_store, current_user,
            (source_job.result_data or {}).get("original_filename"),
            ledger_store=ledger_store,
            charge_plan=charge_plan,
        )

        from ...core.cleanup import cleanup_old_uploads
        background_tasks.add_task(cleanup_old_uploads, uploads_dir, 24)
    except Exception as exc:
        refund_charge_best_effort(ledger_store, charge_plan, status="failed", error=sanitize_message(str(exc)))
        input_path.unlink(missing_ok=True)
        raise

    return {**job.__dict__, "balance": new_balance}


@router.post("/jobs/cleanup")
def run_retention_policy(
    days: int = 30,
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger retention policy: Delete jobs older than {days} days."""
    _ensure_admin(current_user)

    cutoff = int(time.time()) - (days * 24 * 3600)
    old_jobs = job_store.list_jobs_created_before(cutoff)

    if not old_jobs:
        return {"status": "success", "deleted_count": 0, "message": "No old jobs found"}

    _, uploads_dir, artifacts_root = data_roots()
    deleted_ids = []

    for job in old_jobs:
        artifact_dir = artifacts_root / job.id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)

        for ext in [".mp4", ".mov", ".mkv"]:
            input_file = uploads_dir / f"{job.id}_input{ext}"
            if input_file.exists():
                input_file.unlink(missing_ok=True)

        deleted_ids.append(job.id)

    for jid in deleted_ids:
        job_store.delete_job(jid)

    return {"status": "success", "deleted_count": len(deleted_ids), "message": f"Deleted {len(deleted_ids)} jobs older than {days} days"}


@router.get("/admin/usage/summary", response_model=UsageSummaryResponse)
def get_usage_summary(
    group_by: str = Query("day", max_length=16),
    start_ts: int | None = Query(None, ge=0),
    end_ts: int | None = Query(None, ge=0),
    current_user: User = Depends(get_current_user),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
):
    """Admin usage summary by day/month/user/action."""
    _ensure_admin(current_user)

    now = int(time.time())
    start = start_ts if start_ts is not None else now - (30 * 24 * 3600)
    end = end_ts if end_ts is not None else now
    if start > end:
        raise HTTPException(status_code=400, detail="start_ts must be <= end_ts")

    try:
        items = ledger_store.summarize(start_ts=start, end_ts=end, group_by=group_by)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return UsageSummaryResponse(
        group_by=group_by,
        start_ts=start,
        end_ts=end,
        items=[
            UsageSummaryRow(
                bucket=item.bucket,
                credits_reserved=item.credits_reserved,
                credits_charged=item.credits_charged,
                cost_usd=item.cost_usd,
                count=item.count,
            )
            for item in items
        ],
    )
