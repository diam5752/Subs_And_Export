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
        job.updated_at = old_time
        job.status = "completed"

    # Test query
    cutoff = now - (30 * 24 * 3600)
    old_jobs = store.list_jobs_created_before(cutoff)

    # Assert
    # Note: list_jobs_created_before returns list of Job objects
    assert any(j.id == old_id for j in old_jobs)
    old_terminal_jobs = store.list_jobs_updated_before(cutoff, {"completed"})
    assert any(j.id == old_id for j in old_terminal_jobs)
    assert all(j.id != recent_id for j in old_terminal_jobs)
    assert store.list_jobs_updated_before(cutoff, set()) == []
