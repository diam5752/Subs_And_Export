"""Real authenticated uploads, durable offsets, refunds, and erasure."""

import hashlib
import uuid
from unittest.mock import MagicMock

import pytest

from backend.app.api.endpoints import resumable_upload_io, videos
from backend.app.core.cleanup import run_configured_retention
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.upload_session import UPLOAD_CHUNK_BYTES, UPLOAD_SESSION_KEY
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore


def start_upload(client, headers, size=8, **metadata):
    return client.post(
        "/videos/uploads",
        headers=headers,
        json={
            "size": size,
            "metadata": {"filename": "clip.mp4", "authorized_credits": 30, **metadata},
            "content_type": "video/mp4",
        },
    )


def send_chunk(client, headers, upload_id, offset, body, digest=None):
    return client.post(
        f"/videos/uploads/{upload_id}/chunks",
        headers={
            **headers,
            "Content-Type": "application/octet-stream",
            "X-Gsubs-Upload-Offset": str(offset),
            "X-Gsubs-Chunk-SHA256": digest or hashlib.sha256(body).hexdigest(),
        },
        content=body,
    )


def wallet(client, headers):
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    points = PointsStore(Database())
    return user_id, points, points.get_balance(user_id)


def test_chunks_assemble_and_completion_retries_only_queue_once(client, funded_user_auth_headers, monkeypatch):
    headers = funded_user_auth_headers
    user_id, points, balance = wallet(client, headers)
    dispatch = MagicMock()
    monkeypatch.setattr(videos, "run_video_processing", dispatch)
    response = start_upload(client, headers)
    assert response.status_code == 200
    session = response.json()
    upload_id = session["upload_id"]
    assert session["chunk_size"] == UPLOAD_CHUNK_BYTES
    assert points.get_balance(user_id) == balance - 30
    assert send_chunk(client, headers, upload_id, 0, b"abcd").json()["offset"] == 4
    assert send_chunk(client, headers, upload_id, 4, b"efgh").json()["offset"] == 8
    assert (settings.data_dir / "uploads" / f"{upload_id}_input.mp4").read_bytes() == b"abcdefgh"
    for _ in range(2):
        finished = client.post(f"/videos/uploads/{upload_id}/complete", headers=headers)
        assert finished.status_code == 200
        assert finished.json()["id"] == upload_id
        assert UPLOAD_SESSION_KEY not in (finished.json()["result_data"] or {})
    assert dispatch.call_count == 1
    assert points.get_balance(user_id) == balance - 30


def test_lost_chunk_ack_is_replayed_without_duplicate_bytes_or_credits(client, funded_user_auth_headers):
    headers = funded_user_auth_headers
    upload_id = start_upload(client, headers).json()["upload_id"]
    for _ in range(2):
        response = send_chunk(client, headers, upload_id, 0, b"abcd")
        assert response.status_code == 200
        assert response.json()["offset"] == 4
    assert (settings.data_dir / "uploads" / f"{upload_id}_input.mp4").read_bytes() == b"abcd"
    assert send_chunk(client, headers, upload_id, 0, b"xxxx").status_code == 409
    assert client.get(f"/videos/uploads/{upload_id}", headers=headers).json()["offset"] == 4


@pytest.mark.parametrize("offset,body,status", [(5, b"x", 409), (0, b"x" * 9, 409), (-1, b"x", 400)])
def test_out_of_order_and_overflow_never_append(client, funded_user_auth_headers, offset, body, status):
    headers = funded_user_auth_headers
    upload_id = start_upload(client, headers).json()["upload_id"]
    response = send_chunk(client, headers, upload_id, offset, body)
    assert response.status_code == status
    assert client.get(f"/videos/uploads/{upload_id}", headers=headers).json()["offset"] == 0


def test_hash_and_actual_chunk_size_are_enforced(client, funded_user_auth_headers, monkeypatch):
    headers = funded_user_auth_headers
    upload_id = start_upload(client, headers).json()["upload_id"]
    assert send_chunk(client, headers, upload_id, 0, b"abcd", "0" * 64).status_code == 400
    monkeypatch.setattr(resumable_upload_io, "UPLOAD_CHUNK_BYTES", 3)
    assert send_chunk(client, headers, upload_id, 0, b"abcd").status_code == 413
    assert not (settings.data_dir / "uploads" / f"{upload_id}_input.mp4").exists()


def test_cancel_refunds_once_and_removes_exact_workspace(client, funded_user_auth_headers):
    headers = funded_user_auth_headers
    user_id, points, balance = wallet(client, headers)
    upload_id = start_upload(client, headers).json()["upload_id"]
    assert send_chunk(client, headers, upload_id, 0, b"abcd").status_code == 200
    assert client.delete(f"/videos/uploads/{upload_id}", headers=headers).status_code == 200
    assert client.delete(f"/videos/uploads/{upload_id}", headers=headers).status_code == 404
    assert points.get_balance(user_id) == balance
    assert JobStore(Database()).get_job(upload_id) is None
    assert not (settings.data_dir / "uploads" / f"{upload_id}_input.mp4").exists()


def test_expiration_releases_credits_capacity_and_media(client, funded_user_auth_headers):
    headers = funded_user_auth_headers
    user_id, points, balance = wallet(client, headers)
    upload_id = start_upload(client, headers).json()["upload_id"]
    assert send_chunk(client, headers, upload_id, 0, b"abcd").status_code == 200
    jobs = JobStore(Database())
    job = jobs.get_job(upload_id)
    result = dict(job.result_data)
    result[UPLOAD_SESSION_KEY]["expires_at"] = 0
    jobs.update_job(upload_id, result_data=result)
    assert send_chunk(client, headers, upload_id, 4, b"efgh").status_code == 410
    report = run_configured_retention(Database())
    assert upload_id in report.deleted_job_ids
    assert points.get_balance(user_id) == balance
    assert not (settings.data_dir / "uploads" / f"{upload_id}_input.mp4").exists()


def test_incomplete_upload_cannot_queue_or_release_its_reservation(client, funded_user_auth_headers, monkeypatch):
    headers = funded_user_auth_headers
    user_id, points, balance = wallet(client, headers)
    dispatch = MagicMock()
    monkeypatch.setattr(videos, "run_video_processing", dispatch)
    upload_id = start_upload(client, headers).json()["upload_id"]
    assert send_chunk(client, headers, upload_id, 0, b"abcd").status_code == 200
    assert client.post(f"/videos/uploads/{upload_id}/complete", headers=headers).status_code == 409
    assert points.get_balance(user_id) == balance - 30
    dispatch.assert_not_called()


def test_rejected_media_refunds_a_complete_upload(client, funded_user_auth_headers, monkeypatch):
    headers = funded_user_auth_headers
    user_id, points, balance = wallet(client, headers)
    upload_id = start_upload(client, headers).json()["upload_id"]
    assert send_chunk(client, headers, upload_id, 0, b"abcdefgh").status_code == 200
    monkeypatch.setattr(videos, "probe_media", MagicMock(side_effect=ValueError("invalid media")))
    assert client.post(f"/videos/uploads/{upload_id}/complete", headers=headers).status_code == 400
    assert points.get_balance(user_id) == balance
    assert JobStore(Database()).get_job(upload_id) is None


def test_foreign_account_cannot_read_append_complete_or_cancel(client, funded_user_auth_headers):
    upload_id = start_upload(client, funded_user_auth_headers).json()["upload_id"]
    email = f"other-{uuid.uuid4().hex}@example.com"
    password = "valid-test-password123"
    registered = client.post("/auth/register", json={"email": email, "password": password, "name": "Other"})
    assert registered.status_code == 200
    signed_in = client.post("/auth/token", data={"username": email, "password": password})
    assert signed_in.status_code == 200
    token = signed_in.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/videos/uploads/{upload_id}", headers=headers).status_code == 404
    assert send_chunk(client, headers, upload_id, 0, b"abcd").status_code == 404
    assert client.post(f"/videos/uploads/{upload_id}/complete", headers=headers).status_code == 404
    assert client.delete(f"/videos/uploads/{upload_id}", headers=headers).status_code == 404


def test_uncommitted_disk_suffix_is_replaced_on_retry(client, funded_user_auth_headers):
    headers = funded_user_auth_headers
    upload_id = start_upload(client, headers).json()["upload_id"]
    assert send_chunk(client, headers, upload_id, 0, b"abcd").status_code == 200
    path = settings.data_dir / "uploads" / f"{upload_id}_input.mp4"
    with path.open("ab") as target:
        target.write(b"uncommitted")
    assert send_chunk(client, headers, upload_id, 4, b"efgh").status_code == 200
    assert path.read_bytes() == b"abcdefgh"


def test_upload_larger_than_proxy_limit_uses_bounded_requests(client, funded_user_auth_headers):
    headers = funded_user_auth_headers
    body = b"a" * UPLOAD_CHUNK_BYTES
    total = len(body) * 7
    upload_id = start_upload(client, headers, size=total).json()["upload_id"]
    for offset in range(0, total, len(body)):
        response = send_chunk(client, headers, upload_id, offset, body)
        assert response.status_code == 200
        assert response.json()["offset"] == offset + len(body)
    path = settings.data_dir / "uploads" / f"{upload_id}_input.mp4"
    assert path.stat().st_size == total
    assert client.delete(f"/videos/uploads/{upload_id}", headers=headers).status_code == 200
    assert not path.exists()


def test_invalid_size_and_empty_wallet_do_not_create_sessions(client, user_auth_headers):
    assert start_upload(client, user_auth_headers).status_code == 402
    assert start_upload(client, user_auth_headers, size=501 * 1024 * 1024).status_code == 422
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    assert JobStore(Database()).list_jobs_for_user(user_id) == []


def test_retention_recovers_a_cancel_interrupted_before_refund(client, funded_user_auth_headers, monkeypatch):
    from backend.app.api.endpoints import resumable_uploads

    headers = funded_user_auth_headers
    user_id, points, balance = wallet(client, headers)
    upload_id = start_upload(client, headers).json()["upload_id"]
    assert send_chunk(client, headers, upload_id, 0, b"abcd").status_code == 200
    monkeypatch.setattr(resumable_uploads, "_cleanup_upload", MagicMock(side_effect=RuntimeError("interrupted")))
    with pytest.raises(RuntimeError, match="interrupted"):
        client.delete(f"/videos/uploads/{upload_id}", headers=headers)
    assert points.get_balance(user_id) == balance - 30
    assert upload_id in run_configured_retention(Database()).deleted_job_ids
    assert points.get_balance(user_id) == balance
    assert not (settings.data_dir / "uploads" / f"{upload_id}_input.mp4").exists()


def test_competing_chunk_is_rejected_before_reading_its_body(client, funded_user_auth_headers):
    from backend.app.core.workspace_deletion import lock_job_workspace

    headers = funded_user_auth_headers
    upload_id = start_upload(client, headers).json()["upload_id"]
    with lock_job_workspace(data_dir=settings.data_dir, job_id=upload_id):
        response = send_chunk(client, headers, upload_id, 0, b"abcd")
    assert response.status_code == 409
    assert client.get(f"/videos/uploads/{upload_id}", headers=headers).json()["offset"] == 0


def test_general_body_limit_does_not_allow_oversized_upload_metadata(client, funded_user_auth_headers):
    response = client.post("/videos/uploads", headers=funded_user_auth_headers, content=b"x" * 1_000_001)
    assert response.status_code == 413
