from __future__ import annotations

import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ...core import config
from ...core.auth import User
from ...core.env import is_dev_env
from ...schemas.base import JobResponse
from ...services.jobs import JobStore
from ..deps import get_current_user, get_job_store

router = APIRouter()
logger = logging.getLogger(__name__)


def _data_roots() -> tuple[Path, Path, Path]:
    data_dir = config.PROJECT_ROOT / "data"
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


def _resolve_sample_source(uploads_dir: Path, artifacts_root: Path) -> tuple[str, Path, Path]:
    """
    Returns (source_job_id, source_input_video, source_artifact_dir).

    Prefers GSP_DEV_SAMPLE_JOB_ID when provided, otherwise picks the first job
    under artifacts containing transcription.json with a matching upload file.
    """
    preferred = os.getenv("GSP_DEV_SAMPLE_JOB_ID")
    candidates: list[str]
    if preferred:
        candidates = [preferred]
    else:
        candidates = sorted({p.parent.name for p in artifacts_root.glob("*/transcription.json")})

    for job_id in candidates:
        artifact_dir = artifacts_root / job_id
        transcription_json = artifact_dir / "transcription.json"
        if not transcription_json.exists():
            continue
        for ext in (".mp4", ".mov", ".mkv"):
            input_path = uploads_dir / f"{job_id}_input{ext}"
            if input_path.exists():
                return job_id, input_path, artifact_dir

    hint = (
        "Set GSP_DEV_SAMPLE_JOB_ID to a job id with "
        "`data/uploads/{job_id}_input.mp4` and `data/artifacts/{job_id}/transcription.json`."
    )
    raise HTTPException(status_code=404, detail=f"No dev sample video found. {hint}")


@router.post("/sample-job", response_model=JobResponse)
def create_sample_job(
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
):
    """
    DEV-only helper: Create a completed job by linking/copying an existing sample.

    This avoids repeatedly uploading & transcribing a large video while iterating
    on UI/export behavior.
    """
    if not is_dev_env():
        raise HTTPException(status_code=404, detail="Not found")

    data_dir, uploads_dir, artifacts_root = _data_roots()
    source_job_id, source_input, source_artifacts = _resolve_sample_source(uploads_dir, artifacts_root)

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

    result_data = {
        "video_path": video_rel,
        "artifacts_dir": artifacts_rel,
        "public_url": f"/static/{video_rel}",
        "artifact_url": f"/static/{artifacts_rel}",
        "transcription_url": f"/static/{artifacts_rel}/transcription.json",
        "original_filename": os.getenv("GSP_DEV_SAMPLE_FILENAME") or "DEV_SAMPLE.mp4",
        "model_size": "dev-sample",
        "transcribe_provider": "dev-sample",
        "resolution": "",
        # Defaults for export fallback / UI:
        "max_subtitle_lines": 2,
        "subtitle_position": 16,
        "subtitle_color": None,
        "shadow_strength": 4,
        "highlight_style": "active-graphics",
        "subtitle_size": 100,
        "karaoke_enabled": True,
        # Debug aid:
        "dev_sample_source_job_id": source_job_id,
    }

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

