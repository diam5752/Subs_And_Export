import json
import uuid
from pathlib import Path
from fastapi.testclient import TestClient
from backend.app.api.endpoints import videos
from backend.app.core import auth as backend_auth
from backend.app.core.database import Database
from backend.app.services import jobs

def _auth_header(client: TestClient, email: str) -> dict[str, str]:
    try:
        client.post("/auth/register", json={"email": email, "password": "testpassword123", "name": "Test"})
    except:
        pass
    token = client.post("/auth/token", data={"username": email, "password": "testpassword123"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}

def test_srt_export_success(client: TestClient, monkeypatch, tmp_path: Path):
    # Setup environment
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(videos, "_data_roots", lambda: (tmp_path, tmp_path / "uploads", tmp_path / "artifacts"))
    
    # Setup DB
    db = Database(tmp_path / "srt_test.db")
    store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user("srt@example.com", "testpassword123", "User").id
    
    # Create Job
    job = store.create_job("srt-job", user_id)
    artifact_dir = tmp_path / "artifacts" / job.id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    
    # Add dummy transcription
    cues = [
        {"start": 0.5, "end": 1.5, "text": "Hello world"},
        {"start": 2.0, "end": 3.0, "text": "Testing SRT"}
    ]
    (artifact_dir / "transcription.json").write_text(json.dumps(cues))
    job.status = "completed" # Must be completed
    store.update_job(job.id, status="completed", result_data={}) # Ensure result_data dict exists

    # Override get_job_store dep
    from backend.app.api.deps import get_job_store, get_db
    from backend.main import app
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        headers = _auth_header(client, "srt@example.com")
        
        # Trigger export
        resp = client.post(
            f"/videos/jobs/{job.id}/export",
            headers=headers,
            json={"resolution": "srt"}
        )
        
        assert resp.status_code == 200, f"Status: {resp.status_code}, Body: {resp.text}"
        
        # Verify file creation
        srt_path = artifact_dir / "processed.srt"
        assert srt_path.exists()
        content = srt_path.read_text()
        assert "Hello world" in content
        assert "0:00:00,50" in content # Check basic formatting

        # Verify job update
        updated_job = store.get_job(job.id)
        assert updated_job.result_data["variants"]["srt"].endswith("/processed.srt")

    finally:
        app.dependency_overrides = {}
