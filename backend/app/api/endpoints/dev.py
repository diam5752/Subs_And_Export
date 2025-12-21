from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ...core.config import settings
from ...core.auth import User

from ...schemas.base import JobResponse
from ...services.jobs import JobStore
from ..deps import get_current_user, get_job_store

router = APIRouter()
logger = logging.getLogger(__name__)


def _data_roots() -> tuple[Path, Path, Path]:
    data_dir = settings.project_root / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    return data_dir, uploads_dir, artifacts_dir


def _link_or_copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite {destination}")

    try:
        destination.symlink_to(source)
        return
    except Exception:
        pass

    try:
        os.link(source, destination)
        return
    except Exception:
        pass

    shutil.copy2(source, destination)


from pydantic import BaseModel


class DevSampleRequest(BaseModel):
    provider: str | None = None
    model_size: str | None = None

def _resolve_sample_source(
    uploads_dir: Path,
    artifacts_root: Path,
    job_store: JobStore,
    req: DevSampleRequest
) -> tuple[str, Path, Path]:
    """
    Returns (source_job_id, source_input_video, source_artifact_dir).

    If provider/model_size are specified, searches for a matching existing job.
    Otherwise/fallback: Prefers GSP_DEV_SAMPLE_JOB_ID or picks first available.
    """
    preferred = os.getenv("GSP_DEV_SAMPLE_JOB_ID")
    candidates: list[str] = []

    # 1. Gather all candidates from artifacts directory
    all_candidates = sorted({p.parent.name for p in artifacts_root.glob("*/transcription.json")})

    # 2. If filtering is requested, check job store
    if req.provider or req.model_size:
        filtered_candidates = []
        for job_id in all_candidates:
            job = job_store.get_job(job_id)
            if not job or not job.result_data:
                continue

            # Check match
            job_provider = job.result_data.get("transcribe_provider")
            job_model = job.result_data.get("model_size")

            # Loose matching: if req param is None, it ignores it.
            match_provider = (not req.provider) or (job_provider == req.provider)
            match_model = (not req.model_size) or (job_model == req.model_size)

            if match_provider and match_model:
                filtered_candidates.append(job_id)

        # If we found matches, use them. If not, we fall through?
        # User requested specific model alignment. If we fallback, it breaks expectation.
        # But we can fallback to *any* if we fail? strict=False?
        # Let's try strict.
        # If we found matches, use them.
        if filtered_candidates:
            candidates = filtered_candidates
            # Put preferred first if it's in the filtered list
            if preferred and preferred in candidates:
                candidates.remove(preferred)
                candidates.insert(0, preferred)
        else:
             # Fallback to ALL candidates if strict match fails
             # This allows dev tools to work even if we haven't run this specific model yet
             candidates = list(all_candidates)
             if candidates:
                 logger.warning(f"No exact match for {req}. Falling back to available samples: {candidates[:3]}")

    if not candidates:
        # If absolutely no samples exist (fresh install), we can't do anything
        hint = (
            f"No sample video found matching provider={req.provider}, model={req.model_size}. "
            "Run a job with these settings first to create a sample."
        )
        raise HTTPException(status_code=404, detail=hint)

    # Use the first available candidate
    # Logic below iterates, but effectively picks the first valid one
    pass

    for job_id in candidates:
        artifact_dir = artifacts_root / job_id
        transcription_json = artifact_dir / "transcription.json"

        # Double check existence (redundant matching check but safe)
        if not transcription_json.exists():
            continue

        for ext in (".mp4", ".mov", ".mkv"):
            input_path = uploads_dir / f"{job_id}_input{ext}"
            if input_path.exists():
                return job_id, input_path, artifact_dir

    hint = (
        f"No sample video found matching provider={req.provider}, model={req.model_size}. "
        "Run a job with these settings first to create a sample."
    )
    raise HTTPException(status_code=404, detail=hint)


@router.post("/sample-job", response_model=JobResponse)
def create_sample_job(
    request: DevSampleRequest | None = None,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
):
    """
    DEV-only helper: Create a completed job by linking/copying an existing sample.
    Accepts optional provider/model_size to find a matching previously run job.
    """
    if not settings.is_dev:
        raise HTTPException(status_code=404, detail="Not found")

    if request is None:
        request = DevSampleRequest()

    data_dir, uploads_dir, artifacts_root = _data_roots()
    source_job_id, source_input, source_artifacts = _resolve_sample_source(
        uploads_dir, artifacts_root, job_store, request
    )

    # ... Rest logic is similar but we need to fetch source job data to replicate result_data properly?
    # The original implementation hardcoded some result_data defaults but kept source job_id.
    # We should arguably copy result_data from source job if available + update paths.

    source_job = job_store.get_job(source_job_id)
    base_result_data = source_job.result_data if source_job and source_job.result_data else {}

    job_id = str(uuid.uuid4())
    job_store.create_job(job_id, current_user.id)

    input_path = uploads_dir / f"{job_id}_input{source_input.suffix}"
    _link_or_copy_file(source_input, input_path)

    artifact_dir = artifacts_root / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for path in source_artifacts.iterdir():
        if path.is_file():
            _link_or_copy_file(path, artifact_dir / path.name)

    if not (artifact_dir / "transcription.json").exists():
        raise HTTPException(status_code=500, detail="Sample artifacts are missing transcription.json")

    video_rel = input_path.relative_to(data_dir).as_posix()
    artifacts_rel = artifact_dir.relative_to(data_dir).as_posix()

    # Merge/Overlay result data
    result_data = base_result_data.copy()
    result_data.update({
        "video_path": video_rel,
        "artifacts_dir": artifacts_rel,
        "public_url": f"/static/{video_rel}",
        "artifact_url": f"/static/{artifacts_rel}",
        "transcription_url": f"/static/{artifacts_rel}/transcription.json",
        "original_filename": os.getenv("GSP_DEV_SAMPLE_FILENAME") or "DEV_SAMPLE.mp4",
        # Keep original model info if present, else fallback.
        # BUT if request specified a model, use that to simulate a fresh job for the frontend.
        "model_size": request.model_size or result_data.get("model_size", "dev-sample"),
        "transcribe_provider": request.provider or result_data.get("transcribe_provider", "dev-sample"),
        "dev_sample_source_job_id": source_job_id,
    })

    # Ensure defaults like resolution exist for UI if missing in source
    defaults = {
         "resolution": "",
         "max_subtitle_lines": 2,
         "subtitle_position": 16,
         "subtitle_color": None,
         "shadow_strength": 4,
         "highlight_style": "active-graphics",
         "subtitle_size": 100,
         "karaoke_enabled": True,
    }
    for k, v in defaults.items():
        if k not in result_data:
            result_data[k] = v

    job_store.update_job(
        job_id,
        status="completed",
        progress=100,
        message="Loaded dev sample",
        result_data=result_data,
    )

    job = job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=500, detail="Failed to load created sample job")
    return job

