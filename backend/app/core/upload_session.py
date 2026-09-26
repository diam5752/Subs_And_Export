"""Shared lifetime contract for private, resumable media reservations."""

from __future__ import annotations

UPLOAD_SESSION_KEY = "_resumable_upload"
UPLOAD_CHUNK_BYTES = 16 * 1024 * 1024


def upload_session_expired(job: object, now: int) -> bool:
    result = getattr(job, "result_data", None)
    state = result.get(UPLOAD_SESSION_KEY) if isinstance(result, dict) else None
    if not isinstance(state, dict):
        return False
    if state.get("phase") == "cancelled":
        return True
    if state.get("phase") != "uploading":
        return False
    deadline = state.get("expires_at")
    return isinstance(deadline, int) and not isinstance(deadline, bool) and deadline <= now
