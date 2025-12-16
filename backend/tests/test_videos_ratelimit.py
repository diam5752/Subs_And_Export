import os
from unittest.mock import MagicMock

from backend.app.api.endpoints import videos


def test_process_rate_limit(client, user_auth_headers):
    """Verify rate limiting prevents flooding the process endpoint."""

    # Create a dummy file content
    file_content = b"dummy content"

    # We need to send form data for required fields
    data = {
        "transcribe_model": "tiny",
        "video_quality": "balanced"
    }

    # 1. First 10 requests should succeed (limit is 10)
    for i in range(10):
        # Create a new file tuple for each request to avoid seek issues
        files = {"file": ("test.mp4", file_content, "video/mp4")}
        res = client.post(
            "/videos/process",
            headers=user_auth_headers,
            files=files,
            data=data
        )
        # We expect 200 OK because the mock environment handles the processing logic
        assert res.status_code == 200, f"Request {i+1} failed: {res.text}"

    # 2. 11th request should be BLOCKED
    files = {"file": ("test.mp4", file_content, "video/mp4")}
    res = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files,
        data=data
    )
    assert res.status_code == 429, f"Expected 429, got {res.status_code}"
    assert "Too many requests" in res.json()["detail"]


def test_viral_metadata_rate_limit(client, user_auth_headers, monkeypatch, tmp_path):
    """Verify rate limiting on viral metadata generation."""
    # Mock data roots to use tmp_path
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    # Mock generate_viral_metadata to avoid LLM calls
    mock_metadata = MagicMock()
    mock_metadata.hooks = ["Hook 1"]
    mock_metadata.caption_hook = "Caption Hook"
    mock_metadata.caption_body = "Body"
    mock_metadata.cta = "CTA"
    mock_metadata.hashtags = ["#tag"]
    monkeypatch.setattr(videos, "generate_viral_metadata", lambda *args, **kwargs: mock_metadata)

    # 1. Create a dummy job
    # Mock run_video_processing to avoid background task errors/delays
    monkeypatch.setattr(videos, "run_video_processing", lambda *args: None)

    res = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("test.mp4", b"content", "video/mp4")},
    )
    assert res.status_code == 200
    job_id = res.json()["id"]

    # 2. Manually set job to completed and create transcript
    from backend.app.core.database import Database
    from backend.app.services.jobs import JobStore

    db_path = os.environ.get("GSP_DATABASE_PATH")
    db = Database(db_path)
    store = JobStore(db)

    store.update_job(job_id, status="completed", progress=100)

    # Create transcript file
    artifacts_dir = tmp_path / "data" / "artifacts" / job_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "transcript.txt").write_text("Dummy transcript content")

    # 3. Hit viral-metadata 10 times (should succeed)
    for i in range(10):
        res = client.post(f"/videos/jobs/{job_id}/viral-metadata", headers=user_auth_headers)
        assert res.status_code == 200, f"Request {i+1} failed: {res.text}"

    # 4. 11th request should fail
    res = client.post(f"/videos/jobs/{job_id}/viral-metadata", headers=user_auth_headers)
    assert res.status_code == 429
