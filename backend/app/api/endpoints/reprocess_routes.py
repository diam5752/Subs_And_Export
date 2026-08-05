"""Reprocess routes."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core.auth import User
from ...core.config import settings
from ...core.database import Database
from ...core.erasure_journal import configured_erasure_journal
from ...core.errors import sanitize_message
from ...core.ratelimit import limiter_processing
from ...core.workspace_deletion import delete_job_workspace, lock_job_workspace
from ...schemas.base import JobResponse
from ...services import pricing
from ...services.charge_plans import (
    preflight_processing_charges,
    reserve_processing_charges,
)
from ...services.ffmpeg_utils import probe_media
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.usage_ledger import UsageLedgerStore
from ..deps import get_current_user, get_db, get_history_store, get_job_store, get_usage_ledger_store
from .file_utils import data_roots, link_or_copy_file, require_storage_capacity
from .processing_tasks import (
    record_event_safe,
    refund_charge_best_effort,
    run_video_processing,
)
from .settings import build_processing_settings
from .validation import ALLOWED_VIDEO_EXTENSIONS

router = APIRouter()


class ReprocessRequest(BaseModel):
    transcribe_tier: str = Field(settings.default_transcribe_tier, max_length=50)
    transcribe_provider: str = Field(settings.transcribe_tier_provider[settings.default_transcribe_tier], max_length=50)
    openai_model: str = Field("", max_length=50)
    video_quality: str = Field("high quality", max_length=50)
    video_resolution: str = Field("", max_length=50)
    use_llm: bool = settings.use_llm_by_default
    context_prompt: str = Field("", max_length=5000)
    subtitle_position: int = 16
    max_subtitle_lines: int = 2
    subtitle_color: str | None = Field(None, max_length=20)
    shadow_strength: int = 4
    highlight_style: str = Field("karaoke", max_length=20)
    subtitle_size: int = 100
    karaoke_enabled: bool = True
    watermark_enabled: bool = False


def _record_and_delete_failed_reprocess(
    *,
    job_id: str,
    user_id: str,
    input_path: Path,
    artifacts_root: Path,
    database_job_may_exist: bool,
    job_store: JobStore,
    history_store: HistoryStore,
) -> None:
    """Persist restore-safe intent before removing a failed reprocess copy."""
    with lock_job_workspace(data_dir=artifacts_root.parent, job_id=job_id):
        configured_erasure_journal().append(
            kind="job" if database_job_may_exist else "workspace",
            user_id=user_id,
            job_ids=[job_id],
        )
        delete_job_workspace(
            job_id=job_id,
            uploads_dir=input_path.parent,
            artifacts_dir=artifacts_root,
        )
        if database_job_may_exist:
            history_store.delete_job_events([job_id])
            job_store.delete_job(job_id)


@router.post("/jobs/{job_id}/reprocess", response_model=JobResponse, dependencies=[Depends(limiter_processing)])
def reprocess_job(
    job_id: str,
    request: ReprocessRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
    db: Database = Depends(get_db),
) -> JobResponse:
    source_job = job_store.get_job(job_id)
    if not source_job or source_job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if source_job.status != "completed":
        raise HTTPException(status_code=400, detail="Job must be completed to reprocess")

    active_jobs = job_store.count_active_jobs_for_user(current_user.id)
    if active_jobs >= settings.max_concurrent_jobs:
        raise HTTPException(
            status_code=429,
            detail=f"Too many active jobs. Please wait for your current jobs to finish (max {settings.max_concurrent_jobs}).",
        )

    proc_settings = build_processing_settings(
        transcribe_tier=request.transcribe_tier,
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
    if size_bytes > (settings.max_upload_mb * 1024 * 1024):
        raise HTTPException(status_code=413, detail=f"File too large; limit is {settings.max_upload_mb}MB")
    require_storage_capacity(
        data_dir,
        required_bytes=size_bytes * 2,
        db=db,
    )

    try:
        probe = probe_media(source_input)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Could not validate source media file") from exc

    if probe.duration_s is None or probe.duration_s <= 0:
        raise HTTPException(status_code=400, detail="Could not determine video duration")
    if probe.duration_s > settings.max_video_duration_seconds:
        raise HTTPException(
            status_code=400, detail=f"Video too long (max {settings.max_video_duration_seconds / 60:.1f} minutes)"
        )

    llm_models = pricing.resolve_llm_models(proc_settings.transcribe_tier)
    stt_model = pricing.resolve_requested_transcribe_model(
        tier=proc_settings.transcribe_tier,
        provider=proc_settings.transcribe_provider,
        openai_model=proc_settings.openai_model,
    )
    preflight_processing_charges(
        ledger_store=ledger_store,
        user_id=current_user.id,
        tier=proc_settings.transcribe_tier,
        duration_seconds=float(probe.duration_s),
        use_llm=proc_settings.use_llm,
        llm_model=llm_models.social,
        provider=proc_settings.transcribe_provider,
        stt_model=stt_model,
    )

    new_job_id = str(uuid.uuid4())
    input_path = uploads_dir / f"{new_job_id}_input{file_ext}"
    output_path = artifacts_root / new_job_id / "processed.mp4"
    artifact_path = artifacts_root / new_job_id

    try:
        link_or_copy_file(source_input, input_path)
    except BaseException as exc:
        _record_and_delete_failed_reprocess(
            job_id=new_job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            database_job_may_exist=False,
            job_store=job_store,
            history_store=history_store,
        )
        if isinstance(exc, FileNotFoundError):
            raise HTTPException(
                status_code=404,
                detail="Source video not found; upload again to reprocess",
            ) from exc
        raise

    try:
        job = job_store.create_job(new_job_id, current_user.id)
    except BaseException:
        _record_and_delete_failed_reprocess(
            job_id=new_job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            # create_job can fail after its transaction commits. A job
            # tombstone and idempotent exact deletes cover both outcomes.
            database_job_may_exist=True,
            job_store=job_store,
            history_store=history_store,
        )
        raise

    try:
        charge_plan, new_balance = reserve_processing_charges(
            ledger_store=ledger_store,
            user_id=current_user.id,
            job_id=new_job_id,
            tier=proc_settings.transcribe_tier,
            duration_seconds=float(probe.duration_s or 0),
            use_llm=proc_settings.use_llm,
            llm_model=llm_models.social,
            provider=proc_settings.transcribe_provider,
            stt_model=stt_model,
        )
    except BaseException:
        _record_and_delete_failed_reprocess(
            job_id=new_job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            database_job_may_exist=True,
            job_store=job_store,
            history_store=history_store,
        )
        raise
    try:
        # Job already created above
        record_event_safe(
            history_store,
            current_user,
            "process_started",
            f"Reprocessing {source_job.result_data.get('original_filename', 'video') if source_job.result_data else 'video'}",
            {
                "job_id": new_job_id,
                "source_job_id": job_id,
                "provider": proc_settings.transcribe_provider,
                "transcribe_tier": proc_settings.transcribe_tier,
                "source": "local",
            },
        )

        background_tasks.add_task(
            run_video_processing,
            new_job_id,
            input_path,
            output_path,
            artifact_path,
            proc_settings,
            job_store,
            history_store,
            current_user,
            (source_job.result_data or {}).get("original_filename"),
            ledger_store=ledger_store,
            charge_plan=charge_plan,
            source_probe=probe,
        )

    except BaseException as exc:
        refund_charge_best_effort(ledger_store, charge_plan, status="failed", error=sanitize_message(str(exc)))
        _record_and_delete_failed_reprocess(
            job_id=new_job_id,
            user_id=current_user.id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            database_job_may_exist=True,
            job_store=job_store,
            history_store=history_store,
        )
        raise

    return JobResponse.model_validate(job).model_copy(update={"balance": new_balance})
