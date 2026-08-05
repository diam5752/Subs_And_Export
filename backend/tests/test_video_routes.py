import uuid

from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import app
from backend.tests.process_stream import post_process_stream


def test_stream_upload_writes_the_browser_body_directly_once(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    captured: dict[str, object] = {}

    def capture_processing(_job_id, input_path, *_args, **_kwargs) -> None:
        captured["path"] = input_path
        captured["content"] = input_path.read_bytes()

    monkeypatch.setattr(videos_module, "run_video_processing", capture_processing)
    raw_video = b"direct-stream-video"

    response = post_process_stream(
        client,
        funded_user_auth_headers,
        filename="κινητό.mp4",
        content=raw_video,
        metadata={
            "transcribe_tier": "standard",
            "transcribe_provider": "mock",
        },
    )

    # REGRESSION: multipart parsing first spooled the complete request and then
    # copied it again. The optimized route streams the raw browser body into
    # the canonical upload path consumed by processing.
    assert response.status_code == 200
    assert captured["content"] == raw_video
    assert str(captured["path"]).endswith("_input.mp4")


def test_stream_upload_rejects_invalid_metadata_before_writing(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/videos/process-stream",
        headers={
            **user_auth_headers,
            "Content-Type": "video/mp4",
            "X-Gsubs-Upload-Metadata": "not-base64",
        },
        content=b"video",
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid upload metadata"


def test_stream_upload_cors_preflight_allows_metadata_header(client: TestClient) -> None:
    response = client.options(
        "/videos/process-stream",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": ("authorization,content-type,x-gsubs-upload-metadata"),
        },
    )

    assert response.status_code == 200
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    assert "x-gsubs-upload-metadata" in allowed_headers


def test_legacy_multipart_upload_route_is_absent(client: TestClient) -> None:
    # REGRESSION: UploadFile parsing spooled multipart bodies before bearer
    # authentication and before the backend's byte limit could run.
    route_paths = {path for route in client.app.routes if isinstance(path := getattr(route, "path", None), str)}

    assert "/videos/process" not in route_paths
    response = client.post(
        "/videos/process",
        files={"file": ("legacy.mp4", b"legacy", "video/mp4")},
    )
    assert response.status_code == 404


def test_legacy_manual_admin_routes_are_absent(client: TestClient) -> None:
    # REGRESSION: retention and usage reporting run through the controlled
    # scheduler/CLI paths, not public HTTP routes guarded by an email allowlist.
    route_paths = {path for route in client.app.routes if isinstance(path := getattr(route, "path", None), str)}

    assert "/videos/jobs/cleanup" not in route_paths
    assert "/videos/admin/usage/summary" not in route_paths
    assert client.post("/videos/jobs/cleanup").status_code in {404, 405}
    assert client.get("/videos/admin/usage/summary").status_code == 404


def test_stream_upload_authenticates_before_consuming_body(
    client: TestClient,
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    save_called = False

    async def capture_save(*_args, **_kwargs) -> int:
        nonlocal save_called
        save_called = True
        return 0

    monkeypatch.setattr(videos_module, "save_request_stream_with_limit", capture_save)
    response = post_process_stream(client, {}, content=b"unauthenticated-private-video")

    assert response.status_code == 401
    assert save_called is False


def test_stream_upload_rejects_oversized_content_length(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    monkeypatch.setattr(videos_module, "MAX_UPLOAD_BYTES", 1024)
    response = post_process_stream(
        client,
        user_auth_headers,
        content=b"data",
        extra_headers={"content-length": "1025"},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"]


def test_stream_upload_rejects_malformed_content_length(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    response = post_process_stream(
        client,
        user_auth_headers,
        content=b"data",
        extra_headers={"content-length": "not-a-number"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid Content-Length header"


def test_stream_upload_rejects_before_writing_when_storage_reserve_is_low(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import videos as videos_module

    def reject_storage(*_args, **_kwargs) -> None:
        raise HTTPException(status_code=507, detail="Storage is temporarily busy")

    monkeypatch.setattr(videos_module, "require_storage_capacity", reject_storage)

    response = post_process_stream(client, user_auth_headers, content=b"data")

    # REGRESSION: a low-disk server previously accepted the upload and failed
    # only after it had started consuming storage and user time.
    assert response.status_code == 507
    assert response.json()["detail"] == "Storage is temporarily busy"


def test_record_event_safe_exception(monkeypatch):
    """Verify that _record_event_safe suppresses exceptions."""
    from backend.app.api.endpoints.processing_tasks import record_event_safe
    from backend.app.core.auth import User

    def mock_record(*args, **kwargs):
        raise ValueError("DB Error")

    class MockHistoryStore:
        record_event = mock_record

    user = User(id="1", email="test@test.com", name="Test", provider="local")

    # Should not raise
    record_event_safe(MockHistoryStore(), user, "test", "summary", {})


def test_parse_resolution():
    """Unit tests for _parse_resolution helper."""
    from backend.app.api.endpoints.settings import parse_resolution

    assert parse_resolution(None) == (None, None)
    assert parse_resolution("") == (None, None)
    assert parse_resolution("1080x1920") == (1080, 1920)
    assert parse_resolution("2160×3840") == (2160, 3840)  # Mixed char
    assert parse_resolution("invalid") == (None, None)
    assert parse_resolution("-100x100") == (None, None)


def test_ensure_job_integrity(monkeypatch, tmp_path):
    """Completed jobs expose current local artifact availability and size."""

    from backend.app.api.endpoints import job_routes
    from backend.app.services.jobs import Job

    monkeypatch.setattr(job_routes, "DATA_DIR", tmp_path)
    video_path = tmp_path / "artifacts" / "j1" / "processed.mp4"
    video_path.parent.mkdir(parents=True)
    video_path.write_bytes(b"video")

    job_with_size = Job(
        id="j1",
        user_id="u1",
        status="completed",
        progress=100,
        message="done",
        created_at=0,
        updated_at=0,
        result_data={"output_size": 12345, "video_path": "artifacts/j1/processed.mp4"},
    )
    result = job_routes.ensure_job_integrity(job_with_size)
    assert result.result_data["output_size"] == 5
    assert result.result_data["files_missing"] is False

    job_missing_file = Job(
        id="j2",
        user_id="u1",
        status="completed",
        progress=100,
        message="done",
        created_at=0,
        updated_at=0,
        result_data={"video_path": "nonexistent.mp4"},
    )
    res = job_routes.ensure_job_integrity(job_missing_file)
    assert res.result_data["files_missing"] is True
    assert "output_size" not in res.result_data

    traversal_job = Job(
        id="j3",
        user_id="u1",
        status="completed",
        progress=100,
        message="done",
        created_at=0,
        updated_at=0,
        result_data={"video_path": "../outside.mp4"},
    )
    res = job_routes.ensure_job_integrity(traversal_job)
    assert res.result_data["files_missing"] is True


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
                        id="job1",
                        user_id="test_user_id",
                        status="completed",
                        progress=100,
                        message="done",
                        created_at=0,
                        updated_at=0,
                        result_data={},
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

            monkeypatch.setattr(
                "backend.app.api.endpoints.job_routes.data_roots", lambda: (data_root, uploads_root, artifacts_root)
            )
            monkeypatch.setattr(
                "backend.app.api.endpoints.job_routes.data_roots", lambda: (data_root, uploads_root, artifacts_root)
            )

            # Create dummy artifacts
            job_artifact_dir = artifacts_root / "job1"
            job_artifact_dir.mkdir()
            (job_artifact_dir / "file.txt").touch()
            transcription_file = job_artifact_dir / "transcription.json"
            transcription_file.write_text('[{"text": "private"}]', encoding="utf-8")

            input_file = uploads_root / "job1_input.mp4"
            input_file.touch()

            response = client.delete("/videos/jobs/job1", headers=user_auth_headers)
            assert response.status_code == 200
            assert response.json()["status"] == "deleted"

            assert "job1" in deleted_ids
            assert not job_artifact_dir.exists()
            assert not transcription_file.exists()
            assert not input_file.exists()

    finally:
        app.dependency_overrides = {}


def test_delete_active_job_is_blocked_and_preserves_workspace(
    client: TestClient,
    user_auth_headers: dict,
    monkeypatch,
    tmp_path,
):
    """Pending or processing work must be cancelled before deletion."""
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_get_current_user():
        return User(
            id="active-delete-user",
            email="active-delete@example.com",
            name="Active",
            provider="local",
        )

    status = {"value": "pending"}
    deleted_ids: list[str] = []

    class MockJobStore:
        def get_job(self, job_id):
            return Job(
                id=job_id,
                user_id="active-delete-user",
                status=status["value"],
                progress=10,
                message="active",
                created_at=0,
                updated_at=0,
                result_data={},
            )

        def delete_job(self, job_id):
            deleted_ids.append(job_id)

    app.dependency_overrides[deps.get_current_user] = mock_get_current_user
    app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()

    try:
        uploads_root = tmp_path / "uploads"
        artifacts_root = tmp_path / "artifacts"
        uploads_root.mkdir()
        artifacts_root.mkdir()
        monkeypatch.setattr(
            "backend.app.api.endpoints.job_routes.data_roots",
            lambda: (tmp_path, uploads_root, artifacts_root),
        )

        for active_status in ("pending", "processing"):
            status["value"] = active_status
            job_id = f"active-{active_status}"
            input_file = uploads_root / f"{job_id}_input.mp4"
            artifact_file = artifacts_root / job_id / "processed.mp4"
            input_file.write_bytes(b"keep")
            artifact_file.parent.mkdir()
            artifact_file.write_bytes(b"keep")

            response = client.delete(
                f"/videos/jobs/{job_id}",
                headers=user_auth_headers,
            )

            assert response.status_code == 409
            assert "cancel" in response.json()["detail"].lower()
            assert input_file.exists()
            assert artifact_file.exists()

        assert deleted_ids == []
    finally:
        app.dependency_overrides = {}


def test_delete_job_fails_closed_when_erasure_journal_is_unavailable(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
    tmp_path,
) -> None:
    from backend.app.api.endpoints import job_routes
    from backend.app.core.database import Database
    from backend.app.core.erasure_journal import ErasureJournalError
    from backend.app.services.jobs import JobStore

    user_response = client.get("/auth/me", headers=user_auth_headers)
    assert user_response.status_code == 200
    user_id = user_response.json()["id"]
    job_id = f"journal-failure-{uuid.uuid4().hex}"
    store = JobStore(Database())
    store.create_job(job_id, user_id)
    store.update_job(job_id, status="completed", progress=100)

    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifact_dir = artifacts_dir / job_id
    artifact_dir.mkdir(parents=True)
    upload_path = uploads_dir / f"{job_id}_input.mp4"
    transcript_path = artifact_dir / "transcription.json"
    upload_path.write_bytes(b"private")
    transcript_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        job_routes,
        "data_roots",
        lambda: (tmp_path, uploads_dir, artifacts_dir),
    )

    class BrokenJournal:
        def append(self, **_kwargs: object) -> None:
            raise ErasureJournalError("journal unavailable")

    monkeypatch.setattr(
        job_routes,
        "configured_erasure_journal",
        lambda: BrokenJournal(),
    )

    response = client.delete(f"/videos/jobs/{job_id}", headers=user_auth_headers)

    # REGRESSION: local media must not be destructively removed unless the
    # restore-safe erasure intent has first reached durable storage.
    assert response.status_code == 503
    assert response.json() == {"detail": "Privacy protection is temporarily unavailable. Please try again."}
    assert upload_path.is_file()
    assert transcript_path.is_file()
    assert store.get_job(job_id) is not None


def test_cancel_job_journals_exact_workspace_before_status_transition(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import job_routes
    from backend.app.core.database import Database
    from backend.app.services.jobs import JobStore

    user_response = client.get("/auth/me", headers=user_auth_headers)
    assert user_response.status_code == 200
    user_id = user_response.json()["id"]
    job_id = f"cancel-journal-{uuid.uuid4().hex}"
    store = JobStore(Database())
    store.create_job(job_id, user_id)
    recorded: list[dict[str, object]] = []

    class RecordingJournal:
        def append(self, **payload: object) -> None:
            current = store.get_job(job_id)
            assert current is not None
            assert current.status == "pending"
            recorded.append(payload)

    monkeypatch.setattr(
        job_routes,
        "configured_erasure_journal",
        lambda: RecordingJournal(),
    )

    response = client.post(
        f"/videos/jobs/{job_id}/cancel",
        headers=user_auth_headers,
    )

    assert response.status_code == 200
    assert recorded == [
        {
            "kind": "workspace",
            "user_id": user_id,
            "job_ids": [job_id],
        }
    ]
    updated = store.get_job(job_id)
    assert updated is not None
    assert updated.status == "cancelled"


def test_cancel_job_fails_closed_before_status_transition_when_journal_is_unavailable(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import job_routes
    from backend.app.core.database import Database
    from backend.app.core.erasure_journal import ErasureJournalError
    from backend.app.services.jobs import JobStore

    user_response = client.get("/auth/me", headers=user_auth_headers)
    assert user_response.status_code == 200
    user_id = user_response.json()["id"]
    job_id = f"cancel-journal-failure-{uuid.uuid4().hex}"
    store = JobStore(Database())
    store.create_job(job_id, user_id)

    class BrokenJournal:
        def append(self, **_payload: object) -> None:
            raise ErasureJournalError("secret storage failure")

    monkeypatch.setattr(
        job_routes,
        "configured_erasure_journal",
        lambda: BrokenJournal(),
    )

    response = client.post(
        f"/videos/jobs/{job_id}/cancel",
        headers=user_auth_headers,
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "Privacy protection is temporarily unavailable. Please try again."}
    unchanged = store.get_job(job_id)
    assert unchanged is not None
    assert unchanged.status == "pending"


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
            Job(
                id=f"job{i}",
                user_id="test_user_id",
                status="completed",
                progress=100,
                message="done",
                created_at=i,
                updated_at=i,
                result_data={},
            )
            for i in range(15)
        ]

        class MockJobStore:
            def count_jobs_for_user(self, user_id):
                return len(mock_jobs)

            def list_jobs_for_user_paginated(self, user_id, offset=0, limit=10):
                return mock_jobs[offset : offset + limit]

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
                        id=job_id,
                        user_id="test_user_id",
                        status="completed",
                        progress=100,
                        message="done",
                        created_at=0,
                        updated_at=0,
                        result_data={},
                    )
                elif job_id == "job_other_user":
                    return Job(
                        id=job_id,
                        user_id="other_user",
                        status="completed",
                        progress=100,
                        message="done",
                        created_at=0,
                        updated_at=0,
                        result_data={},
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
                (job_dir / "transcription.json").write_text(
                    '[{"text": "private"}]',
                    encoding="utf-8",
                )
                (uploads_root / f"{jid}_input.mp4").write_bytes(b"private")

            monkeypatch.setattr(
                "backend.app.api.endpoints.job_routes.data_roots", lambda: (tpath, uploads_root, artifacts_root)
            )
            monkeypatch.setattr(
                "backend.app.api.endpoints.job_routes.data_roots", lambda: (tpath, uploads_root, artifacts_root)
            )

            # Test batch delete
            response = client.post(
                "/videos/jobs/batch-delete", headers=user_auth_headers, json={"job_ids": ["job1", "job2", "job3"]}
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "deleted"
            assert data["deleted_count"] == 3
            assert set(data["job_ids"]) == {"job1", "job2", "job3"}

            # REGRESSION: batch erasure must remove every local input and the
            # full artifact tree, including transcription data, for every job.
            for jid in ["job1", "job2", "job3"]:
                assert not (uploads_root / f"{jid}_input.mp4").exists()
                assert not (artifacts_root / jid).exists()
                assert not (artifacts_root / jid / "transcription.json").exists()

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
        response = client.post("/videos/jobs/batch-delete", headers=user_auth_headers, json={"job_ids": []})
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
        response = client.post("/videos/jobs/batch-delete", headers=user_auth_headers, json={"job_ids": job_ids})
        assert response.status_code == 400
        assert "Cannot delete more than 50" in response.json()["detail"]

    finally:
        app.dependency_overrides = {}
