from __future__ import annotations

import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from ...core.auth import User
from ...core.config import settings
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
        os.link(source, destination)
        return
    except Exception:
        pass

    shutil.copy2(source, destination)


from pydantic import BaseModel


class DevSampleRequest(BaseModel):
    provider: str | None = None
    model_size: str | None = None


def _prioritize_preferred(candidates: list[str], preferred: str | None) -> list[str]:
    if preferred and preferred in candidates:
        return [preferred, *[job_id for job_id in candidates if job_id != preferred]]
    return candidates


def _parse_srt_timestamp(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _transcription_json_from_srt(srt_path: Path) -> list[dict[str, object]]:
    content = srt_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip()
    if not content:
        return []

    cues: list[dict[str, object]] = []
    for block in content.split("\n\n"):
        lines = [line.strip() for line in block.split("\n") if line.strip()]
        if len(lines) < 2:
            continue

        timing_line_index = 0 if "-->" in lines[0] else 1
        if timing_line_index >= len(lines) or "-->" not in lines[timing_line_index]:
            continue

        start_raw, end_raw = [part.strip() for part in lines[timing_line_index].split("-->", maxsplit=1)]
        text = "\n".join(lines[timing_line_index + 1:]).strip()
        if not text:
            continue

        cues.append(
            {
                "start": _parse_srt_timestamp(start_raw),
                "end": _parse_srt_timestamp(end_raw),
                "text": text,
                "words": [],
            }
        )

    return cues


def _ensure_bundled_dev_sample(uploads_dir: Path, artifacts_root: Path) -> tuple[str, Path, Path] | None:
    fixture_root = settings.project_root / "backend" / "tests" / "data"
    bundled_input = fixture_root / "demo.mp4"
    if not bundled_input.exists():
        bundled_input = settings.project_root / "backend" / "data" / "demo.mp4"

    bundled_artifacts = fixture_root / "demo_artifacts"
    bundled_srt = bundled_artifacts / "demo.srt"
    if not bundled_input.exists() or not bundled_srt.exists():
        return None

    source_job_id = "bundled-dev-sample"
    input_path = uploads_dir / f"{source_job_id}_input{bundled_input.suffix}"
    if not input_path.exists():
        _link_or_copy_file(bundled_input, input_path)

    artifact_dir = artifacts_root / source_job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    bundled_output = fixture_root / "demo_output.mp4"
    output_source = bundled_output if bundled_output.exists() else bundled_input

    artifacts_to_copy = {
        "processed.mp4": output_source,
        "demo.srt": bundled_srt,
        "demo.ass": bundled_artifacts / "demo.ass",
        "transcript.txt": bundled_artifacts / "transcript.txt",
    }
    for filename, source in artifacts_to_copy.items():
        destination = artifact_dir / filename
        if source.exists() and not destination.exists():
            _link_or_copy_file(source, destination)

    transcription_path = artifact_dir / "transcription.json"
    if not transcription_path.exists():
        transcription_path.write_text(
            json.dumps(_transcription_json_from_srt(bundled_srt), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return source_job_id, input_path, artifact_dir


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

    # 1. Gather all candidates from artifacts directory
    all_candidates = sorted({p.parent.name for p in artifacts_root.glob("*/transcription.json")})
    filtered_candidates: list[str] = []

    # 2. If filtering is requested, check job store
    if req.provider or req.model_size:
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

    if not all_candidates:
        bundled = _ensure_bundled_dev_sample(uploads_dir, artifacts_root)
        if bundled:
            logger.info("Seeded bundled DEV sample because no recorded sample jobs were available.")
            return bundled
        hint = (
            f"No sample video found matching provider={req.provider}, model={req.model_size}. "
            "Run a job with these settings first to create a sample."
        )
        raise HTTPException(status_code=404, detail=hint)

    fallback_candidates = [job_id for job_id in all_candidates if job_id not in filtered_candidates]
    candidate_groups: list[list[str]] = []

    if filtered_candidates:
        candidate_groups.append(_prioritize_preferred(filtered_candidates, preferred))
        if fallback_candidates:
            logger.warning(
                "Exact dev-sample matches for %s may be stale; falling back to other samples if inputs are missing.",
                req,
            )
    else:
        if req.provider or req.model_size:
            logger.warning("No exact match for %s. Falling back to available samples: %s", req, all_candidates[:3])
        fallback_candidates = all_candidates

    if fallback_candidates:
        candidate_groups.append(_prioritize_preferred(fallback_candidates, preferred))

    for candidates in candidate_groups:
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

    bundled = _ensure_bundled_dev_sample(uploads_dir, artifacts_root)
    if bundled:
        logger.warning("Falling back to bundled DEV sample because recorded samples were incomplete.")
        return bundled

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
            # Demo artifacts are writable: transcript edits and exports can replace
            # ASS/SRT/video variants in place. A hard link here would mutate the
            # source sample (and, for the bundled sample, repository fixtures).
            shutil.copy2(path, artifact_dir / path.name)

    if not (artifact_dir / "transcription.json").exists():
        raise HTTPException(status_code=500, detail="Sample artifacts are missing transcription.json")

    preview_path = artifact_dir / "processed.mp4"
    if not preview_path.exists():
        preview_path = input_path

    video_rel = preview_path.relative_to(data_dir).as_posix()
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
        "output_size": preview_path.stat().st_size if preview_path.exists() else result_data.get("output_size", 0),
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
