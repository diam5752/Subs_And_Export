import uuid

from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.app.services import jobs


def test_export_video_validation_sentinel(client: TestClient, monkeypatch, tmp_path):
    # Setup DB
    monkeypatch.setenv("GSP_DATABASE_PATH", str(tmp_path / "app.db"))

    from backend.app.core.database import Database
    db_path = tmp_path / "app.db"
    db = Database(db_path)
    job_store = jobs.JobStore(db)
    from backend.app.core.auth import UserStore
    user_store = UserStore(db=db)

    # Register user
    email = "sentinel_export@example.com"
    user = user_store.register_local_user(email, "testpassword123", "Sentinel")

    # Login to get token
    token = client.post(
        "/auth/token",
        data={"username": email, "password": "testpassword123"},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create a job directly in store
    job_id = str(uuid.uuid4())
    job = job_store.create_job(job_id, user.id)
    # Mark it completed
    job_store.update_job(job_id, status="completed", progress=100)

    # Setup file system mocks
    # Mock config.PROJECT_ROOT in videos module so _data_roots uses tmp_path
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    # Create input file so export doesn't 404 on file
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / f"{job_id}_input.mp4").write_text("fake video")

    # Create artifact dir
    artifacts_dir = data_dir / "artifacts" / job_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Also need transcript.srt because export tries to find it
    (artifacts_dir / f"{job_id}_input.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHello")

    # Test Invalid Color
    response = client.post(
        f"/videos/jobs/{job_id}/export",
        headers=headers,
        json={
            "resolution": "1080x1920",
            "subtitle_color": "INVALID_COLOR"
        }
    )

    # We expect 422 Unprocessable Entity due to validation failure
    # Currently it will likely fail with 500 or succeed if validation is missing
    assert response.status_code == 422, f"Expected 422, got {response.status_code}. Body: {response.text}"
    assert "subtitle_color" in response.text
