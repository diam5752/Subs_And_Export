import io
import types
import uuid
from pathlib import Path

from backend.app.services import jobs
from backend.app.core import auth as backend_auth
from backend.app.core.database import Database
from backend.app.api.endpoints import videos
from fastapi.testclient import TestClient
from backend.main import app


def _auth_header(client: TestClient, email: str = "video@example.com") -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "password": "testpassword123", "name": "Video"})
    token = client.post(
        "/auth/token",
        data={"username": email, "password": "testpassword123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_job_store_lifecycle(tmp_path: Path):
    db = Database(tmp_path / "jobs.db")
    store = jobs.JobStore(db)

    user_id = backend_auth.UserStore(db=db).register_local_user(
        "job@example.com", "testpassword123", "Job"
    ).id

    job = store.create_job("j1", user_id)
    store.update_job(job.id, status="processing", progress=25, message="start", result_data={"a": 1})
    updated = store.get_job(job.id)
    assert updated and updated.status == "processing"
    assert updated.progress == 25
    assert updated.result_data["a"] == 1


    # Calling update with no changes is a no-op
    store.update_job(job.id)
    listed = store.list_jobs_for_user(user_id)
    assert listed and listed[0].id == job.id

    # Test delete_job
    store.delete_job(job.id)
    assert store.get_job(job.id) is None
    
    # Test delete_jobs_for_user
    j2 = store.create_job("j2", user_id)
    j3 = store.create_job("j3", user_id)
    store.delete_jobs_for_user(user_id)
    assert store.get_job("j2") is None
    assert store.get_job("j3") is None
    assert len(store.list_jobs_for_user(user_id)) == 0


def test_run_video_processing_success(monkeypatch, tmp_path: Path):
    # Keep paths relative to tmp_path so relative_to() succeeds
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    db = Database(tmp_path / "vid.db")
    store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user(
        "runner@example.com", "testpassword123", "Runner"
    ).id
    job = store.create_job("job-success", user_id)

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts" / "out.mp4"

    def fake_normalize(input_path, output_path, **kwargs):
        kwargs["progress_callback"]("halfway", 50)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        social = types.SimpleNamespace(tiktok=types.SimpleNamespace(title="hi"))
        return output_path, social

    monkeypatch.setattr(videos, "normalize_and_stub_subtitles", fake_normalize)
    settings = videos.ProcessingSettings()
    videos.run_video_processing(job.id, input_path, output_path, output_path.parent, settings, store)

    finished = store.get_job(job.id)
    assert finished and finished.status == "completed"
    assert finished.progress == 100
    assert finished.result_data["video_path"].endswith("out.mp4")


def test_run_video_processing_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    db = Database(tmp_path / "vid_fail.db")
    store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user(
        "runner2@example.com", "testpassword123", "Runner"
    ).id
    job = store.create_job("job-fail", user_id)

    input_path = tmp_path / "input2.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "out2.mp4"

    def boom(*args, **kwargs):
        raise RuntimeError("explode")

    monkeypatch.setattr(videos, "normalize_and_stub_subtitles", boom)
    settings = videos.ProcessingSettings()
    videos.run_video_processing(job.id, input_path, output_path, tmp_path / "artifacts2", settings, store)

    failed = store.get_job(job.id)
    assert failed and failed.status == "failed"
    assert "explode" in (failed.message or "")


def test_run_video_processing_handles_path_only(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)
    db = Database(tmp_path / "vid_path.db")
    store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user(
        "runner3@example.com", "testpassword123", "Runner"
    ).id
    job = store.create_job("job-path", user_id)

    input_path = tmp_path / "input3.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts3" / "out3.mp4"

    def fake_normalize(*_args, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        return output_path

    monkeypatch.setattr(videos, "normalize_and_stub_subtitles", fake_normalize)
    settings = videos.ProcessingSettings()
    videos.run_video_processing(job.id, input_path, output_path, output_path.parent, settings, store)

    finished = store.get_job(job.id)
    assert finished and finished.status == "completed"


def test_process_video_rejects_invalid_extension(client: TestClient):
    headers = _auth_header(client, email="reject@example.com")
    resp = client.post(
        "/videos/process",
        headers=headers,
        files={"file": ("notes.txt", b"nope", "text/plain")},
    )
    assert resp.status_code == 400


def test_process_video_creates_job(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="process@example.com")
    called: dict[str, str] = {}

    def fake_run(job_id, *_args, **_kwargs):
        called["job"] = job_id

    monkeypatch.setattr(videos, "run_video_processing", fake_run)
    resp = client.post(
        "/videos/process",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(b"123"), "video/mp4")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]
    assert called["job"] == body["id"]

    detail = client.get(f"/videos/jobs/{body['id']}", headers=headers)
    assert detail.status_code == 200


def test_get_job_not_found(client: TestClient):
    headers = _auth_header(client, email="fetch@example.com")
    resp = client.get(f"/videos/jobs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_backend_wrappers_import():
    from backend.app.common import metrics as backend_metrics
    from backend.app.services import subtitles as backend_subtitles

    assert hasattr(backend_metrics, "should_log_metrics")
    assert hasattr(backend_subtitles, "create_styled_subtitle_file")
