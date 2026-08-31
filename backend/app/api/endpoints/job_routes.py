"""Job management route handlers.

This module contains routes for job listing, retrieval, deletion,
cancellation, and transcription updates.
"""

from __future__ import annotations

import json
import logging
from typing import TypedDict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core.auth import User
from ...core.erasure_journal import (
    ErasureJournalError,
    JobTerminalStatus,
    TombstoneKind,
    configured_erasure_journal,
)
from ...core.job_lifecycle import ACTIVE_JOB_STATUSES, CANCELLABLE_JOB_STATUSES
from ...core.ratelimit import limiter_content
from ...core.workspace_deletion import (
    JobWorkspaceLockTimeoutError,
    delete_job_workspace,
    lock_job_workspace,
    lock_job_workspaces,
)
from ...schemas.base import BatchDeleteRequest, BatchDeleteResponse, JobResponse, PaginatedJobsResponse
from ...services.history import HistoryStore
from ...services.jobs import Job, JobStore
from ...services.transcription.utils import normalize_text
from ..deps import get_current_user, get_history_store, get_job_store
from .file_utils import DATA_DIR, data_roots
from .processing_tasks import record_event_safe

logger = logging.getLogger(__name__)

router = APIRouter()


def _record_erasure_intent_or_503(
    *,
    kind: TombstoneKind,
    user_id: str,
    job_ids: list[str],
) -> None:
    """Fail closed when restore-safe privacy state cannot be persisted."""
    try:
        configured_erasure_journal().append(
            kind=kind,
            user_id=user_id,
            job_ids=job_ids,
        )
    except ErasureJournalError as exc:
        logger.error(
            "Refusing destructive media action because the erasure journal is unavailable",
            extra={"erasure_kind": kind, "job_count": len(job_ids)},
        )
        raise HTTPException(
            status_code=503,
            detail="Privacy protection is temporarily unavailable. Please try again.",
        ) from exc


def _record_terminal_intent_or_503(
    *,
    user_id: str,
    job_ids: list[str],
    terminal_status: JobTerminalStatus,
) -> None:
    """Fail closed when restore cannot safely finish a terminal job."""
    try:
        configured_erasure_journal().append_job_terminal(
            user_id=user_id,
            job_ids=job_ids,
            terminal_status=terminal_status,
        )
    except ErasureJournalError as exc:
        logger.error(
            "Refusing terminal media action because the erasure journal is unavailable",
            extra={"terminal_status": terminal_status, "job_count": len(job_ids)},
        )
        raise HTTPException(
            status_code=503,
            detail="Privacy protection is temporarily unavailable. Please try again.",
        ) from exc


class TranscriptionWordPayload(TypedDict):
    start: float
    end: float
    text: str


class TranscriptionCuePayload(TypedDict):
    start: float
    end: float
    text: str
    words: list[TranscriptionWordPayload] | None


def ensure_job_integrity(job: Job) -> Job:
    """Annotate completed local jobs with current artifact availability and size."""
    if job.status == "completed" and job.result_data:
        video_path = job.result_data.get("video_path")
        if isinstance(video_path, str) and video_path:
            try:
                data_root = DATA_DIR.resolve()
                full_path = (data_root / video_path).resolve()
                file_exists = full_path.is_relative_to(data_root) and full_path.is_file()
                result_data = dict(job.result_data)
                result_data["files_missing"] = not file_exists
                if file_exists:
                    result_data["output_size"] = full_path.stat().st_size
                job.result_data = result_data
            except OSError as exc:
                logger.warning("Failed to check job file integrity for %s: %s", job.id, exc)
    return job


@router.get("/jobs", response_model=list[JobResponse])
def list_jobs(
    current_user: User = Depends(get_current_user), job_store: JobStore = Depends(get_job_store)
) -> list[JobResponse]:
    """List all jobs for the current user."""
    jobs = job_store.list_jobs_for_user(current_user.id)
    return [JobResponse.model_validate(ensure_job_integrity(job)) for job in jobs]


@router.get("/jobs/paginated", response_model=PaginatedJobsResponse)
def list_jobs_paginated(
    page: int = 1,
    page_size: int = 5,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
) -> PaginatedJobsResponse:
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
    items = [JobResponse.model_validate(ensure_job_integrity(job)) for job in jobs]

    return PaginatedJobsResponse(items=items, total=total, page=page, page_size=page_size, total_pages=total_pages)


@router.post("/jobs/batch-delete", response_model=BatchDeleteResponse)
def batch_delete_jobs(
    request: BatchDeleteRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
) -> BatchDeleteResponse:
    """Delete multiple jobs at once."""
    if not request.job_ids:
        return BatchDeleteResponse(status="success", deleted_count=0, job_ids=[])

    if len(request.job_ids) > 50:
        raise HTTPException(400, "Cannot delete more than 50 jobs at once")

    data_dir, uploads_dir, artifacts_root = data_roots()

    # Optimize: Fetch all jobs in one query instead of N+1
    jobs = job_store.get_jobs(request.job_ids, current_user.id)
    if any(job.status in ACTIVE_JOB_STATUSES for job in jobs):
        raise HTTPException(
            status_code=409,
            detail=(
                "Active projects cannot be deleted. Cancel processing first and wait for cancellation to complete."
            ),
        )

    try:
        with lock_job_workspaces(
            data_dir=data_dir,
            job_ids=(job.id for job in jobs),
        ):
            locked_jobs = job_store.get_jobs(
                [job.id for job in jobs],
                current_user.id,
            )
            if any(job.status in ACTIVE_JOB_STATUSES for job in locked_jobs):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Active projects cannot be deleted. Cancel processing first and wait for cancellation to complete."
                    ),
                )

            deleted_ids = [job.id for job in locked_jobs]
            if locked_jobs:
                _record_erasure_intent_or_503(
                    kind="job",
                    user_id=current_user.id,
                    job_ids=deleted_ids,
                )

            for locked_job in locked_jobs:
                delete_job_workspace(
                    job_id=locked_job.id,
                    uploads_dir=uploads_dir,
                    artifacts_dir=artifacts_root,
                    expected_user_id=locked_job.user_id,
                )

            history_store.delete_job_events(deleted_ids)
            deleted_count = job_store.delete_jobs(deleted_ids, current_user.id)
    except JobWorkspaceLockTimeoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if deleted_count > 0:
        record_event_safe(
            history_store,
            current_user,
            "jobs_batch_deleted",
            f"Deleted {deleted_count} projects",
            {"count": deleted_count},
        )

    return BatchDeleteResponse(status="deleted", deleted_count=deleted_count, job_ids=deleted_ids)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(
    job_id: str, current_user: User = Depends(get_current_user), job_store: JobStore = Depends(get_job_store)
) -> JobResponse:
    """Get a specific job."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")
    return JobResponse.model_validate(ensure_job_integrity(job))


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


def _normalize_transcription_text(text: str) -> str:
    return " ".join(normalize_text(text).split())


def _normalize_transcription_payload(
    cues: list[TranscriptionCueRequest],
) -> list[TranscriptionCuePayload]:
    payload: list[TranscriptionCuePayload] = []
    for cue in cues:
        words_payload: list[TranscriptionWordPayload] | None = None
        if cue.words is not None:
            words_payload = []
            for word in cue.words:
                normalized_word = _normalize_transcription_text(word.text)
                if normalized_word:
                    words_payload.append({"start": word.start, "end": word.end, "text": normalized_word})

        normalized_text = _normalize_transcription_text(cue.text)
        if words_payload:
            normalized_text = " ".join(word["text"] for word in words_payload)

        payload.append(
            {
                "start": cue.start,
                "end": cue.end,
                "text": normalized_text,
                "words": words_payload,
            }
        )
    return payload


@router.put("/jobs/{job_id}/transcription", dependencies=[Depends(limiter_content)])
def update_transcription(
    job_id: str,
    request: UpdateTranscriptionRequest,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
) -> dict[str, str]:
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

    payload = _normalize_transcription_payload(request.cues)
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
    history_store: HistoryStore = Depends(get_history_store),
) -> dict[str, str]:
    """Delete a job and its associated files."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")
    if job.status in ACTIVE_JOB_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                "Active projects cannot be deleted. Cancel processing first and wait for cancellation to complete."
            ),
        )

    data_dir, uploads_dir, artifacts_root = data_roots()

    try:
        with lock_job_workspace(data_dir=data_dir, job_id=job_id):
            locked_job = job_store.get_job(job_id)
            if not locked_job or locked_job.user_id != current_user.id:
                raise HTTPException(404, "Job not found")
            if locked_job.status in ACTIVE_JOB_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Active projects cannot be deleted. Cancel processing first and wait for cancellation to complete."
                    ),
                )

            _record_erasure_intent_or_503(
                kind="job",
                user_id=current_user.id,
                job_ids=[job_id],
            )

            delete_job_workspace(
                job_id=job_id,
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_root,
                expected_user_id=locked_job.user_id,
            )
            history_store.delete_job_events([job_id])
            job_store.delete_job(job_id)
            record_event_safe(history_store, current_user, "job_deleted", "Deleted a project", {})
    except JobWorkspaceLockTimeoutError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return {"status": "deleted", "job_id": job_id}


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    history_store: HistoryStore = Depends(get_history_store),
) -> JobResponse:
    """Request cancellation; the worker publishes terminal state after cleanup."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status not in CANCELLABLE_JOB_STATUSES:
        raise HTTPException(400, f"Cannot cancel job with status '{job.status}'")

    if not job_store.update_job_if_status(
        job_id,
        expected_statuses=CANCELLABLE_JOB_STATUSES,
        status="cancelling",
        message="Cancellation requested",
    ):
        latest_job = job_store.get_job(job_id)
        if latest_job is None or latest_job.user_id != current_user.id:
            raise HTTPException(404, "Job not found")
        raise HTTPException(400, f"Cannot cancel job with status '{latest_job.status}'")

    # Publish intent only after this request wins the active->cancelling CAS.
    # Otherwise a losing cancellation could leave a tombstone that later
    # erases a successfully completed project. The worker holds the workspace
    # lock for its write-capable lifetime, so live replay cannot delete beneath
    # it. If this append fails, cancelling remains fail-closed for startup
    # recovery instead of exposing a premature terminal state.
    _record_terminal_intent_or_503(
        user_id=current_user.id,
        job_ids=[job_id],
        terminal_status="cancelled",
    )
    record_event_safe(
        history_store,
        current_user,
        "job_cancellation_requested",
        f"Cancellation requested for job {job_id}",
        {"job_id": job_id},
    )

    updated_job = job_store.get_job(job_id)
    if updated_job is None:
        raise HTTPException(status_code=500, detail="Cancelling job could not be reloaded")
    return JobResponse.model_validate(ensure_job_integrity(updated_job))
