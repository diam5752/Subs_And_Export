import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app
from backend.app.core import config
from backend.app.api.endpoints import videos


def test_upload_limit_exceeded(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test that uploading a file larger than the limit raises 413."""
    # Create a mock/copy of settings with revised limit
    from backend.app.core.settings import AppSettings
    # Assuming we can instantiate it or copy
    new_settings = AppSettings(max_upload_mb=1)
    monkeypatch.setattr(videos, "APP_SETTINGS", new_settings)
    monkeypatch.setattr(videos, "MAX_UPLOAD_BYTES", 1024 * 1024)

    # Create a dummy file > 1MB
    large_content = b"0" * (1024 * 1024 + 100)
    files = {"file": ("large.mp4", large_content, "video/mp4")}
    
    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files
    )
    assert response.status_code == 413
    assert "Request too large" in response.json()["detail"]

def test_process_video_content_length_error(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test 413 based on Content-Length header check."""
    from backend.app.core.settings import AppSettings
    new_settings = AppSettings(max_upload_mb=1)
    monkeypatch.setattr(videos, "APP_SETTINGS", new_settings)
    monkeypatch.setattr(videos, "MAX_UPLOAD_BYTES", 1024 * 1024)

    # We can't easily fake Content-Length with TestClient in a way that the Starlette Request sees it 
    # before stream consumption without some trickery, but we can verify logic via unit test or
    # by passing a header if the backend checks `request.headers`.
    
    headers = user_auth_headers.copy()
    headers["content-length"] = str(1024 * 1024 + 100)
    
    # Just need a valid file for the multipart to form
    files = {"file": ("test.mp4", b"data", "video/mp4")}
    
    response = client.post(
        "/videos/process",
        headers=headers,
        files=files
    )
    assert response.status_code == 413
    assert "Request too large" in response.json()["detail"]

def test_record_event_safe_exception(monkeypatch):
    """Verify that _record_event_safe suppresses exceptions."""
    from backend.app.api.endpoints.videos import _record_event_safe
    from backend.app.core.auth import User
    
    def mock_record(*args, **kwargs):
        raise ValueError("DB Error")
    
    class MockHistoryStore:
        record_event = mock_record

    user = User(id="1", email="test@test.com", name="Test", provider="local")
    
    # Should not raise
    _record_event_safe(MockHistoryStore(), user, "test", "summary", {})

def test_parse_resolution():
    """Unit tests for _parse_resolution helper."""
    from backend.app.api.endpoints.videos import _parse_resolution
    
    assert _parse_resolution(None) == (config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT)
    assert _parse_resolution("") == (config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT)
    assert _parse_resolution("1080x1920") == (1080, 1920)
    assert _parse_resolution("2160×3840") == (2160, 3840) # Mixed char
    assert _parse_resolution("invalid") == (config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT)
    assert _parse_resolution("-100x100") == (config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT)

def test_ensure_job_size_logic():
    """Test _ensure_job_size backfill logic."""
    from backend.app.api.endpoints.videos import _ensure_job_size
    from backend.app.services.jobs import Job
    import time
    
    # Case 1: Already has size
    job_with_size = Job(
        id="j1", user_id="u1", status="completed", progress=100, message="done",
        created_at=0, updated_at=0,
        result_data={"output_size": 12345, "video_path": "foo.mp4"}
    )
    assert _ensure_job_size(job_with_size).result_data["output_size"] == 12345
    
    # Case 2: Missing size, file missing
    job_missing_file = Job(
        id="j2", user_id="u1", status="completed", progress=100, message="done",
        created_at=0, updated_at=0,
        result_data={"video_path": "nonexistent.mp4"}
    )
    # create a dummy non-existent path structure for logic check
    # In real execution, config.PROJECT_ROOT might point to where `nonexistent.mp4` isn't.
    # It should just pass and remain unset or unchanged.
    res = _ensure_job_size(job_missing_file)
    assert "output_size" not in res.result_data

    # Case 3: Error handling
    job_bad_data = Job(
        id="j3", user_id="u1", status="completed", progress=100, message="done",
        created_at=0, updated_at=0,
        result_data={"video_path": 123} # Invalid path type
    )
    res = _ensure_job_size(job_bad_data)
    assert "output_size" not in res.result_data

def test_create_viral_metadata_error(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test error handling in viral metadata generation."""
    # 1. Job not completed
    # Mock job store to return a processing job
    from backend.app.services.jobs import JobStore, Job
    
    def mock_get_job(self, job_id):
        # Ensure we return the job even if it thinks it's not found
        # (Though logic relies on job_id)
        return Job(
            id=job_id, user_id="test_user_id", status="processing", progress=50, 
            message="...", created_at=0, updated_at=0, result_data={}
        )
        
    monkeypatch.setattr(JobStore, "get_job", mock_get_job)
    
    # Check if dependency overrides are needed.
    # The endpoint calls get_current_user. If we use user_auth_headers, we get a real user.
    # But job.user_id must match current_user.id.
    # `user_auth_headers` creates "Test User" with email "test@example.com".
    # We need to know the ID of that user.
    # Easier: Mock get_current_user to return a user with known ID "test_user_id".
    from backend.app.core.auth import User
    from backend.app.api import deps
    
    # Mock current user dependency
    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
        
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user
    
    try:
        response = client.post("/videos/jobs/fake_id/viral-metadata", headers=user_auth_headers)
        assert response.status_code == 400
        assert "Job must be completed" in response.json()["detail"]
    finally:
         app.dependency_overrides = {}

    # 2. Transcript not found
    def mock_get_job_completed(self, job_id):
        return Job(
            id=job_id, user_id="test_user_id", status="completed", progress=100, 
            message="...", created_at=0, updated_at=0, result_data={}
        )
    monkeypatch.setattr(JobStore, "get_job", mock_get_job_completed)
    
    # Mock _data_roots to point to temp
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tpath = Path(td)
        monkeypatch.setattr("backend.app.api.endpoints.videos._data_roots", lambda: (tpath, tpath, tpath))
        
        # Override dependency again just to be safe (it was cleared)
        app.dependency_overrides[deps.get_current_user] = mock_get_current_user
        try:
            response = client.post("/videos/jobs/fake_id/viral-metadata", headers=user_auth_headers)
            assert response.status_code == 404
            assert "Transcript not found" in response.json()["detail"]
        finally:
             app.dependency_overrides = {}

def test_delete_job(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test deleting a job and its artifacts."""
    from backend.app.services.jobs import JobStore, Job
    from backend.app.core.auth import User
    from backend.app.api import deps
    import shutil
    
    # Mock user dependency
    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user
    
    try:
        # Mock JobStore
        deleted_ids = []
        class MockJobStore:
            def get_job(self, job_id):
                if job_id == "job1":
                    return Job(
                        id="job1", user_id="test_user_id", status="completed", progress=100,
                        message="done", created_at=0, updated_at=0, result_data={}
                    )
                return None
            def delete_job(self, job_id):
                deleted_ids.append(job_id)
        
        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()
        
        # Mock file system
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            data_root = tpath / "data"
            uploads_root = tpath / "uploads"
            artifacts_root = tpath / "artifacts"
            
            for p in [data_root, uploads_root, artifacts_root]:
                p.mkdir()
                
            monkeypatch.setattr("backend.app.api.endpoints.videos._data_roots", lambda: (data_root, uploads_root, artifacts_root))
            
            # Create dummy artifacts
            job_artifact_dir = artifacts_root / "job1"
            job_artifact_dir.mkdir()
            (job_artifact_dir / "file.txt").touch()
            
            input_file = uploads_root / "job1_input.mp4"
            input_file.touch()
            
            response = client.delete("/videos/jobs/job1", headers=user_auth_headers)
            assert response.status_code == 200
            assert response.json()["status"] == "deleted"
            
            assert "job1" in deleted_ids
            assert not job_artifact_dir.exists()
            assert not input_file.exists()
            
    finally:
        app.dependency_overrides = {}

def test_create_viral_metadata_success(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test successful generation of viral metadata."""
    from backend.app.services.jobs import JobStore, Job
    from backend.app.core.auth import User
    from backend.app.api import deps
    from backend.app.services.subtitles import ViralMetadata
    
    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user
    
    try:
        # Mock JobStore
        class MockJobStore:
            def get_job(self, job_id):
                return Job(
                    id="job1", user_id="test_user_id", status="completed", progress=100,
                    message="done", created_at=0, updated_at=0, result_data={}
                )

        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()

        # Mock generate_viral_metadata
        def mock_gen(*args, **kwargs):
            return ViralMetadata(
                hooks=["Hook 1"], 
                caption_hook="Caption Hook",
                caption_body="Caption Body",
                cta="Follow",
                hashtags=["#tag"]
            )
        monkeypatch.setattr("backend.app.api.endpoints.videos.generate_viral_metadata", mock_gen)

        # Mock file system
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            artifacts_root = tpath / "artifacts"
            artifacts_root.mkdir()
            job_dir = artifacts_root / "job1"
            job_dir.mkdir()
            (job_dir / "transcript.txt").write_text("transcript")
            
            monkeypatch.setattr("backend.app.api.endpoints.videos._data_roots", lambda: (tpath, tpath, artifacts_root))
            
            response = client.post("/videos/jobs/job1/viral-metadata", headers=user_auth_headers)
            assert response.status_code == 200
            data = response.json()
            assert data["hooks"] == ["Hook 1"]
            assert data["caption_hook"] == "Caption Hook"
    finally:
        app.dependency_overrides = {}
