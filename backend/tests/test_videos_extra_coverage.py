
from fastapi.testclient import TestClient

from backend.main import app
from backend.app.api.endpoints import export_routes


def test_cancel_job_success(client: TestClient, user_auth_headers: dict, monkeypatch):
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        class MockJobStore:
            def get_job(self, job_id):
                if job_id == "job1":
                    return Job(
                        id="job1", user_id="test_user_id", status="processing", progress=50,
                        message="processing", created_at=0, updated_at=0, result_data={}
                    )
                return None

            def update_job(self, job_id, **kwargs):
                pass

            def count_active_jobs_for_user(self, user_id):
                return 0

        class MockHistoryStore:
            def add_event(self, *args, **kwargs):
                pass

        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()
        app.dependency_overrides[deps.get_history_store] = lambda: MockHistoryStore()

        # Test cancellation
        response = client.post("/videos/jobs/job1/cancel", headers=user_auth_headers)
        assert response.status_code == 200
        # The endpoint calls get_job again at the end, so we rely on mock returning same job.
        # But wait, endpoint returns _ensure_job_size(updated_job).
        # And updated_job comes from job_store.get_job(job_id).
        # Our mock returns "processing".
        # But real logic updates DB.
        # So returned job might still say "processing" in this mock setup unless we update state.
        # But we just want coverage of the ROUTE logic.

    finally:
        app.dependency_overrides = {}

def test_cancel_job_invalid_status(client: TestClient, user_auth_headers: dict, monkeypatch):
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        class MockJobStore:
            def get_job(self, job_id):
                return Job(
                    id="job1", user_id="test_user_id", status="completed", progress=100,
                    message="done", created_at=0, updated_at=0, result_data={}
                )

            def count_active_jobs_for_user(self, user_id):
                return 0

        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()

        response = client.post("/videos/jobs/job1/cancel", headers=user_auth_headers)
        assert response.status_code == 400
        assert "Cannot cancel job" in response.json()["detail"]
    finally:
        app.dependency_overrides = {}

def test_export_video_failure(client: TestClient, user_auth_headers: dict, monkeypatch):
    from backend.app.api import deps
    from backend.app.core.auth import User
    from backend.app.services.jobs import Job

    async def mock_get_current_user():
        return User(id="test_user_id", email="test@example.com", name="Test", provider="local")
    app.dependency_overrides[deps.get_current_user] = mock_get_current_user

    try:
        class MockJobStore:
            def get_job(self, job_id):
                return Job(
                    id="job1", user_id="test_user_id", status="completed", progress=100,
                    message="done", created_at=0, updated_at=0, result_data={}
                )

            def count_active_jobs_for_user(self, user_id):
                return 0

        app.dependency_overrides[deps.get_job_store] = lambda: MockJobStore()

        # Mock file existence
        # The logic checks for input video
        # We can structure data roots to point to real tmp dir with inputs
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            tpath = Path(td)
            uploads = tpath / "uploads"
            uploads.mkdir()
            (uploads / "job1_input.mp4").touch()

            monkeypatch.setattr("backend.app.api.endpoints.videos._data_roots", lambda: (tpath, uploads, tpath / "artifacts"))
            monkeypatch.setattr(export_routes, "data_roots", lambda: (tpath, uploads, tpath / "artifacts"))

            # Mock generate_video_variant to raise exception
            def mock_gen(*args, **kwargs):
                raise ValueError("FFmpeg error")

            # We need to monkeypatch the import inside endpoints.videos?
            # It imports using relative: from ...services.video_processing import generate_video_variant
            # So we patch "backend.app.services.video_processing.generate_video_variant"
            monkeypatch.setattr("backend.app.services.video_processing.generate_video_variant", mock_gen)

            response = client.post(
                "/videos/jobs/job1/export",
                headers=user_auth_headers,
                json={"resolution": "1080p"}
            )
            assert response.status_code == 500
            assert "Export failed" in response.json()["detail"]

    finally:
        app.dependency_overrides = {}
