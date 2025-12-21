from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.main import app


def test_upload_limit_exceeded(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test that uploading a file larger than the limit raises 413."""
    # Patch MAX_UPLOAD_BYTES to a small value (1MB)
    from backend.app.api.endpoints import file_utils
    monkeypatch.setattr(file_utils, "MAX_UPLOAD_BYTES", 1024 * 1024)

    # Create a dummy file > 1MB
    large_content = b"0" * (1024 * 1024 + 100)
    files = {"file": ("large.mp4", large_content, "video/mp4")}

    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files
    )
    assert response.status_code == 413
    assert "too large" in response.json()["detail"]

def test_process_video_content_length_error(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test 413 based on Content-Length header check."""
    # Patch MAX_UPLOAD_BYTES to a small value (1MB)
    from backend.app.api.endpoints import file_utils
    monkeypatch.setattr(file_utils, "MAX_UPLOAD_BYTES", 1024 * 1024)
    # Also patch the videos module's import of the constant
    from backend.app.api.endpoints import videos as videos_module
    monkeypatch.setattr(videos_module, "MAX_UPLOAD_BYTES", 1024 * 1024)

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
    assert "too large" in response.json()["detail"]

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

    assert _parse_resolution(None) == (None, None)
    assert _parse_resolution("") == (None, None)
    assert _parse_resolution("1080x1920") == (1080, 1920)
    assert _parse_resolution("2160×3840") == (2160, 3840) # Mixed char
    assert _parse_resolution("invalid") == (None, None)
    assert _parse_resolution("-100x100") == (None, None)

def test_ensure_job_size_logic():
    """Test _ensure_job_size backfill logic."""

    from backend.app.api.endpoints.videos import _ensure_job_size
    from backend.app.services.jobs import Job

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
    from backend.app.services.jobs import Job, JobStore

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
    from backend.app.api import deps
    from backend.app.core.auth import User

    # Mock current user dependency
    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")

    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    import pytest
    pytest.skip("viral_metadata endpoint removed")
    return # Unreachable but keeps indent checker happy

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

    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

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
            monkeypatch.setattr("backend.app.api.endpoints.job_routes.data_roots", lambda: (data_root, uploads_root, artifacts_root))

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
    import pytest
    pytest.skip("viral_metadata endpoint removed")
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job
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


def test_list_jobs_paginated(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test paginated jobs endpoint."""
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        # Create mock jobs
        mock_jobs = [
            Job(id=f"job{i}", user_id="test_user_id", status="completed", progress=100,
                message="done", created_at=i, updated_at=i, result_data={})
            for i in range(15)
        ]

        class MockJobStore:
            def count_jobs_for_user(self, user_id):
                return len(mock_jobs)

            def list_jobs_for_user_paginated(self, user_id, offset=0, limit=10):
                return mock_jobs[offset:offset+limit]

        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()

        # Test first page
        response = client.get("/videos/jobs/paginated?page=1&page_size=10", headers=user_auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 15
        assert data["page"] == 1
        assert data["page_size"] == 10
        assert data["total_pages"] == 2
        assert len(data["items"]) == 10

        # Test second page
        response = client.get("/videos/jobs/paginated?page=2&page_size=10", headers=user_auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5
        assert data["page"] == 2

    finally:
        app.dependency_overrides = {}


def test_list_jobs_paginated_validation(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test paginated jobs endpoint handles invalid params."""
    from backend.app.api import deps
    from backend.app.core.auth import User

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        class MockJobStore:
            def count_jobs_for_user(self, user_id):
                return 5

            def list_jobs_for_user_paginated(self, user_id, offset=0, limit=10):
                return []

        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()

        # Test page < 1 defaults to 1
        response = client.get("/videos/jobs/paginated?page=0&page_size=10", headers=user_auth_headers)
        assert response.status_code == 200
        assert response.json()["page"] == 1

        # Test page_size > 100 is capped
        response = client.get("/videos/jobs/paginated?page=1&page_size=200", headers=user_auth_headers)
        assert response.status_code == 200
        assert response.json()["page_size"] == 100

    finally:
        app.dependency_overrides = {}


def test_batch_delete_jobs(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test batch delete endpoint."""
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        deleted_ids = []

        class MockJobStore:
            def get_job(self, job_id):
                if job_id in ["job1", "job2", "job3"]:
                    return Job(
                        id=job_id, user_id="test_user_id", status="completed", progress=100,
                        message="done", created_at=0, updated_at=0, result_data={}
                    )
                elif job_id == "job_other_user":
                    return Job(
                        id=job_id, user_id="other_user", status="completed", progress=100,
                        message="done", created_at=0, updated_at=0, result_data={}
                    )
                return None

            def get_jobs(self, job_ids, user_id):
                return [self.get_job(jid) for jid in job_ids if self.get_job(jid)]

            def delete_jobs(self, job_ids, user_id):
                for jid in job_ids:
                    deleted_ids.append(jid)
                return len(job_ids)

        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()

        # Mock file system
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            uploads_root = tpath / "uploads"
            artifacts_root = tpath / "artifacts"
            uploads_root.mkdir()
            artifacts_root.mkdir()

            # Create dummy artifacts
            for jid in ["job1", "job2", "job3"]:
                job_dir = artifacts_root / jid
                job_dir.mkdir()
                (job_dir / "file.txt").touch()

            monkeypatch.setattr("backend.app.api.endpoints.videos._data_roots", lambda: (tpath, uploads_root, artifacts_root))
            monkeypatch.setattr("backend.app.api.endpoints.job_routes.data_roots", lambda: (tpath, uploads_root, artifacts_root))

            # Test batch delete
            response = client.post(
                "/videos/jobs/batch-delete",
                headers=user_auth_headers,
                json={"job_ids": ["job1", "job2", "job3"]}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "deleted"
            assert data["deleted_count"] == 3
            assert set(data["job_ids"]) == {"job1", "job2", "job3"}

            # Verify artifacts were deleted
            assert not (artifacts_root / "job1").exists()

    finally:
        app.dependency_overrides = {}


def test_batch_delete_empty_list(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test batch delete with empty list returns success."""
    from backend.app.api import deps
    from backend.app.core.auth import User

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        response = client.post(
            "/videos/jobs/batch-delete",
            headers=user_auth_headers,
            json={"job_ids": []}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["deleted_count"] == 0

    finally:
        app.dependency_overrides = {}


def test_batch_delete_limit(client: TestClient, user_auth_headers: dict, monkeypatch):
    """Test batch delete rejects more than 50 jobs."""
    from backend.app.api import deps
    from backend.app.core.auth import User

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        # Try to delete 51 jobs
        job_ids = [f"job{i}" for i in range(51)]
        response = client.post(
            "/videos/jobs/batch-delete",
            headers=user_auth_headers,
            json={"job_ids": job_ids}
        )
        assert response.status_code == 400
        assert "Cannot delete more than 50" in response.json()["detail"]

    finally:
        app.dependency_overrides = {}
