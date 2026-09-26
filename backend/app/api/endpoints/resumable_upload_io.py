"""Bounded, integrity-checked appends to an already admitted local upload."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import time
from pathlib import Path
from typing import Any, BinaryIO

import anyio
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ...core.config import settings
from ...core.upload_session import UPLOAD_CHUNK_BYTES, UPLOAD_SESSION_KEY
from ...services.jobs import Job, JobStore
from .file_utils import UPLOAD_STORAGE_RESERVATION_KEY, upload_storage_reservation_bytes
from .stream_upload_contract import StreamProcessMetadata


class UploadSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metadata: StreamProcessMetadata
    size: int = Field(gt=0, le=settings.max_upload_mb * 1024 * 1024, strict=True)
    content_type: str = Field(default="application/octet-stream", max_length=100)


class UploadSessionResponse(BaseModel):
    upload_id: str
    size: int
    offset: int
    chunk_size: int = UPLOAD_CHUNK_BYTES
    expires_at: int


def owned_upload(job_store: JobStore, upload_id: str, user_id: str) -> Job:
    job = job_store.get_job(upload_id)
    if job is None or job.user_id != user_id:
        raise HTTPException(404, "Upload not found")
    return job


def upload_state(job: Job) -> dict[str, Any]:
    state = (job.result_data or {}).get(UPLOAD_SESSION_KEY)
    if not isinstance(state, dict):
        raise HTTPException(409, "Upload is no longer accepting data")
    return dict(state)


def writable_upload_state(job: Job) -> dict[str, Any]:
    state = upload_state(job)
    if job.status != "pending" or state["phase"] != "uploading":
        raise HTTPException(409, "Upload is no longer accepting data")
    if int(state["expires_at"]) <= time.time():
        raise HTTPException(410, "Upload session expired")
    return state


def session_response(job: Job) -> UploadSessionResponse:
    state = upload_state(job)
    return UploadSessionResponse(
        upload_id=job.id,
        size=state["size"],
        offset=state["offset"],
        expires_at=state["expires_at"],
    )


def upload_input_path(job: Job, uploads_dir: Path) -> Path:
    metadata = StreamProcessMetadata.model_validate(upload_state(job)["metadata"])
    suffix = Path(metadata.filename).suffix.lower()
    return uploads_dir / f"{job.id}_input{suffix}"


def chunk_headers(request: Request, total_size: int) -> tuple[int, str]:
    raw_offset = request.headers.get("x-gsubs-upload-offset", "")
    digest = request.headers.get("x-gsubs-chunk-sha256", "")
    if not re.fullmatch(r"[0-9]{1,12}", raw_offset) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HTTPException(400, "Invalid upload chunk headers")
    offset = int(raw_offset)
    if offset >= total_size:
        raise HTTPException(409, "Upload offset is outside the file")
    return offset, digest


async def read_chunk(request: Request, *, expires_at: int, digest: str) -> bytes:
    """Authenticate before this bounded buffer; never buffer a whole video."""
    deadline = min(float(expires_at) - time.time(), settings.upload_total_timeout_seconds)
    if deadline <= 0:
        raise HTTPException(410, "Upload session expired")
    buffer = bytearray()
    stream = request.stream().__aiter__()
    try:
        with anyio.fail_after(deadline):
            while True:
                with anyio.fail_after(settings.upload_inactivity_timeout_seconds):
                    chunk = await anext(stream, None)
                if chunk is None:
                    break
                if len(buffer) + len(chunk) > UPLOAD_CHUNK_BYTES:
                    raise HTTPException(413, "Upload chunk is too large")
                buffer.extend(chunk)
    except TimeoutError as exc:
        raise HTTPException(408, "Upload chunk timed out") from exc
    if not buffer or hashlib.sha256(buffer).hexdigest() != digest:
        raise HTTPException(400, "Upload chunk checksum mismatch")
    return bytes(buffer)


def append_chunk(job: Job, job_store: JobStore, path: Path, offset: int, body: bytes) -> Job:
    """Called under the workspace lock; acknowledge only fsynced bytes."""
    state = writable_upload_state(job)
    committed = int(state["offset"])
    end = offset + len(body)
    if end > state["size"] or offset > committed:
        raise HTTPException(409, "Upload offset does not match the stored file")
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "r+b") as target:
        if not stat.S_ISREG(os.fstat(target.fileno()).st_mode):
            raise HTTPException(409, "Upload workspace is invalid")
        if offset < committed:
            _verify_replayed_chunk(target, offset, end, committed, body)
            return job
        if os.fstat(target.fileno()).st_size < committed:
            raise HTTPException(409, "Upload workspace is incomplete")
        # Discard an uncommitted suffix left by an interrupted write/DB update.
        target.truncate(committed)
        target.seek(committed)
        target.write(body)
        target.flush()
        os.fsync(target.fileno())
    state["offset"] = end
    result = dict(job.result_data or {})
    result[UPLOAD_SESSION_KEY] = state
    result[UPLOAD_STORAGE_RESERVATION_KEY] = upload_storage_reservation_bytes(state["size"] - end)
    job_store.update_job(job.id, result_data=result)
    job.result_data = result
    return job


def _verify_replayed_chunk(target: BinaryIO, offset: int, end: int, committed: int, body: bytes) -> None:
    if end > committed:
        raise HTTPException(409, "Upload chunk overlaps the committed offset")
    target.seek(offset)
    if target.read(len(body)) != body:
        raise HTTPException(409, "Upload retry does not match the stored chunk")
