
import time

from backend.app.db.models import DbJob, DbUser
from backend.app.services.jobs import JobStore


def test_job_store_retention(tmp_path):
    """Unit test for JobStore filtering."""
    from backend.app.core.database import Database

    # Use file DB to ensure persistence across connections
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    with db.session() as session:
        if not session.get(DbUser, "u1"):
            session.add(DbUser(id="u1", email="test@test.com", name="Test User", provider="local"))

    store = JobStore(db)

    # Create jobs
    store.create_job("recent", "u1")
    store.create_job("old", "u1")

    # Manually age "old"
    now = int(time.time())
    old_time = now - (31 * 24 * 3600)
    with db.session() as session:
        job = session.get(DbJob, "old")
        assert job is not None
        job.created_at = old_time

    # Test query
    cutoff = now - (30 * 24 * 3600)
    old_jobs = store.list_jobs_created_before(cutoff)

    # Assert
    # Note: list_jobs_created_before returns list of Job objects
    assert len(old_jobs) == 1
    assert old_jobs[0].id == "old"

def test_cleanup_api_integration(client, user_auth_headers):
    """Full integration test mocking the DB state."""
    import os
    from unittest.mock import patch

    # Create job
    files = {"file": ("immediate_delete.mp4", b"data", "video/mp4")}
    resp = client.post("/videos/process", headers=user_auth_headers, files=files)
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    # Call cleanup with days=-1 (cutoff = NOW + 24h) to delete everything
    # We must patch GSP_ADMIN_EMAILS to allow the test user (test@example.com)
    with patch.dict(os.environ, {"GSP_ADMIN_EMAILS": "test@example.com"}):
        cleanup_resp = client.post("/videos/jobs/cleanup?days=-1", headers=user_auth_headers)
        assert cleanup_resp.status_code == 200
        assert cleanup_resp.json()["deleted_count"] >= 1

    # Verify job gone
    job_resp = client.get(f"/videos/jobs/{job_id}", headers=user_auth_headers)
    # Depending on implementation, get_job might return 404 or just fail auth if user deleted?
    # Actually delete_job removes from DB, so 404.
    assert job_resp.status_code == 404
