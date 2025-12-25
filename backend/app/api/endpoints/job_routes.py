"""Job management route handlers.

This module contains routes for job listing, retrieval, deletion,
cancellation, and transcription updates.
"""

from __future__ import annotations

import json
import logging
import shutil
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field


from ...core.auth import User
from ...core.ratelimit import limiter_content
from ...schemas.base import BatchDeleteRequest, BatchDeleteResponse, JobResponse, PaginatedJobsResponse
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ..deps import get_current_user, get_history_store, get_job_store
from .file_utils import DATA_DIR, data_roots
from .processing_tasks import record_event_safe

logger = logging.getLogger(__name__)

router = APIRouter()


def ensure_job_size(job):
    """Helper to backfill output_size for legacy jobs and check file existence."""
    if job.status == "completed" and job.result_data:
        video_path = job.result_data.get("video_path") or job.result_data.get("public_url")
        if video_path:
            try:
                # Clean up the path - handle various formats like "/static/artifacts/..." or "data/artifacts/..."
                cleaned_path = video_path.lstrip("/")
                if cleaned_path.startswith("static/"):
                    cleaned_path = cleaned_path[7:]  # Remove "static/" prefix
                if cleaned_path.startswith("data/"):
                    cleaned_path = cleaned_path[5:]  # Remove "data/" prefix
                
                full_path = DATA_DIR / cleaned_path
                
                # Also try the artifacts path directly
                artifacts_path = DATA_DIR / "artifacts" / job.id / "processed.mp4"
                
                file_exists = full_path.exists() or artifacts_path.exists()
                
                if not file_exists:
                    # Mark job as having missing files
                    job.result_data = {**job.result_data, "files_missing": True}
                else:
                    # Backfill output_size if missing
                    if not job.result_data.get("output_size"):
                        existing_path = full_path if full_path.exists() else artifacts_path
                        job.result_data["output_size"] = existing_path.stat().st_size
            except Exception as e:
                logger.warning(f"Failed to check job file integrity: {e}")
    return job


@router.get("/jobs", response_model=List[JobResponse])
def list_jobs(
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    """List all jobs for the current user."""
    jobs = job_store.list_jobs_for_user(current_user.id)
    return [ensure_job_size(job) for job in jobs]


@router.get("/jobs/paginated", response_model=PaginatedJobsResponse)
def list_jobs_paginated(
    page: int = 1,
    page_size: int = 5,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    """List jobs with pagination support."""
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 10
    if page_size > 100:
        page_size = 100

    offset = (page - 1) * page_size
    total = job_store.count_jobs_for_user(current_user.id)
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    jobs = job_store.list_jobs_for_user_paginated(current_user.id, offset=offset, limit=page_size)
    items = [ensure_job_size(job) for job in jobs]

    return PaginatedJobsResponse(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


@router.post("/jobs/batch-delete", response_model=BatchDeleteResponse, dependencies=[Depends(limiter_content)])
def batch_delete_jobs(
    request: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Delete multiple jobs at once."""
    if not request.job_ids:
        return BatchDeleteResponse(status="success", deleted_count=0, job_ids=[])

    if len(request.job_ids) > 50:
        raise HTTPException(400, "Cannot delete more than 50 jobs at once")

    data_dir, uploads_dir, artifacts_root = data_roots()
    deleted_ids = []

    # Optimize: Fetch all jobs in one query instead of N+1
    jobs = job_store.get_jobs(request.job_ids, current_user.id)

    for job in jobs:
        job_id = job.id
        artifact_dir = artifacts_root / job_id
        if artifact_dir.exists():
            shutil.rmtree(artifact_dir, ignore_errors=True)

        for ext in [".mp4", ".mov", ".mkv"]:
            input_file = uploads_dir / f"{job_id}_input{ext}"
            if input_file.exists():
                input_file.unlink(missing_ok=True)

        deleted_ids.append(job_id)

    deleted_count = job_store.delete_jobs(deleted_ids, current_user.id)

    if deleted_count > 0:
        record_event_safe(
            history_store, current_user, "jobs_batch_deleted",
            f"Deleted {deleted_count} jobs", {"job_ids": deleted_ids, "count": deleted_count}
        )

    return BatchDeleteResponse(status="deleted", deleted_count=deleted_count, job_ids=deleted_ids)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store)
):
    """Get a specific job."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")
    return ensure_job_size(job)


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
    """Update job transcription."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    _, _, artifacts_root = data_roots()
    artifacts_root_resolved = artifacts_root.resolve()
    artifact_dir = (artifacts_root / job_id).resolve()
    if not artifact_dir.is_relative_to(artifacts_root_resolved):
        raise HTTPException(status_code=400, detail="Invalid job id")

    transcription_json = artifact_dir / "transcription.json"
    if not transcription_json.exists():
        raise HTTPException(status_code=404, detail="Transcript not found")

    payload = [cue.model_dump() for cue in request.cues]
    tmp_path = transcription_json.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(transcription_json)

    result_data = job.result_data.copy() if job.result_data else {}
    result_data["transcription_edited"] = True
    job_store.update_job(job_id, result_data=result_data)

    return {"status": "ok"}


@router.delete("/jobs/{job_id}", dependencies=[Depends(limiter_content)])
def delete_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store)
):
    """Delete a job and its associated files."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    data_dir, uploads_dir, artifacts_root = data_roots()

    artifact_dir = artifacts_root / job_id
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir, ignore_errors=True)

    for ext in [".mp4", ".mov", ".mkv"]:
        input_file = uploads_dir / f"{job_id}_input{ext}"
        if input_file.exists():
            input_file.unlink(missing_ok=True)

    job_store.delete_job(job_id)
    record_event_safe(history_store, current_user, "job_deleted", f"Deleted job {job_id}", {"job_id": job_id})

    return {"status": "deleted", "job_id": job_id}


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse, dependencies=[Depends(limiter_content)])
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

    if job.status not in ("pending", "processing"):
        raise HTTPException(400, f"Cannot cancel job with status '{job.status}'")

    job_store.update_job(job_id, status="cancelled", message="Cancelled by user")
    record_event_safe(history_store, current_user, "job_cancelled", f"Cancelled job {job_id}", {"job_id": job_id})

    updated_job = job_store.get_job(job_id)
    return ensure_job_size(updated_job)
