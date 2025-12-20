
import time
import uuid

from backend.app.db.models import DbJob, DbUser
from backend.app.services.jobs import JobStore


def test_job_store_retention(tmp_path):
    """Unit test for JobStore filtering."""
    from backend.app.core.database import Database

    db = Database()
    user_id = uuid.uuid4().hex
    with db.session() as session:
        if not session.get(DbUser, user_id):
            session.add(DbUser(id=user_id, email=f"{user_id}@test.com", name="Test User", provider="local"))

    store = JobStore(db)

    # Create jobs
    recent_id = f"recent-{uuid.uuid4().hex}"
    old_id = f"old-{uuid.uuid4().hex}"
    store.create_job(recent_id, user_id)
    store.create_job(old_id, user_id)

    # Manually age "old"
    now = int(time.time())
    old_time = now - (31 * 24 * 3600)
    with db.session() as session:
        job = session.get(DbJob, old_id)
        assert job is not None
        job.created_at = old_time

    # Test query
    cutoff = now - (30 * 24 * 3600)
    old_jobs = store.list_jobs_created_before(cutoff)

    # Assert
    # Note: list_jobs_created_before returns list of Job objects
    assert len(old_jobs) == 1
    assert old_jobs[0].id == old_id

def test_cleanup_api_integration(client, user_auth_headers):
    """Full integration test mocking the DB state."""
    import os
    from unittest.mock import patch

    # Create job
    files = {"file": ("immediate_delete.mp4", b"data", "video/mp4")}
    resp = client.post("/videos/process", headers=user_auth_headers, files=files)
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    admin_email = me.json()["email"]

    # Call cleanup with days=-1 (cutoff = NOW + 24h) to delete everything
    with patch.dict(os.environ, {"GSP_ADMIN_EMAILS": admin_email}):
        cleanup_resp = client.post("/videos/jobs/cleanup?days=-1", headers=user_auth_headers)
        assert cleanup_resp.status_code == 200
        assert cleanup_resp.json()["deleted_count"] >= 1

    # Verify job gone
    job_resp = client.get(f"/videos/jobs/{job_id}", headers=user_auth_headers)
    # Depending on implementation, get_job might return 404 or just fail auth if user deleted?
    # Actually delete_job removes from DB, so 404.
    assert job_resp.status_code == 404
