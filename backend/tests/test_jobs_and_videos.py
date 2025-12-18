import io
import types
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.app.core import auth as backend_auth
from backend.app.core.database import Database
from backend.app.services import jobs
from backend.app.services.points import PointsStore, STARTING_POINTS_BALANCE


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


def test_run_video_processing_does_not_restart_cancelled_job_and_refunds(monkeypatch, tmp_path: Path):
    # REGRESSION: a cancelled job must never flip back to processing, and charges must be refunded.
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    db = Database(tmp_path / "vid_cancel.db")
    job_store = jobs.JobStore(db)
    points_store = PointsStore(db=db)

    user_id = backend_auth.UserStore(db=db).register_local_user(
        "cancelled@example.com", "testpassword123", "Runner"
    ).id
    job = job_store.create_job("job-cancelled", user_id)

    cost = 200
    meta = {"charge_id": job.id, "job_id": job.id, "model": "turbo"}
    points_store.spend(user_id, cost, reason="process_video", meta=meta)
    assert points_store.get_balance(user_id) == STARTING_POINTS_BALANCE - cost

    job_store.update_job(job.id, status="cancelled", message="Cancelled by user")

    input_path = tmp_path / "input_cancel.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts_cancel" / "out.mp4"

    monkeypatch.setattr(
        videos,
        "normalize_and_stub_subtitles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not process cancelled jobs")),
    )

    settings = videos.ProcessingSettings()
    charge = videos._ChargeContext(user_id=user_id, cost=cost, reason="process_video", meta=meta)
    videos.run_video_processing(
        job.id,
        input_path,
        output_path,
        output_path.parent,
        settings,
        job_store,
        points_store=points_store,
        charge=charge,
    )

    assert points_store.get_balance(user_id) == STARTING_POINTS_BALANCE
    cancelled = job_store.get_job(job.id)
    assert cancelled and cancelled.status == "cancelled"


def test_run_gcs_video_processing_does_not_restart_cancelled_job_and_refunds(monkeypatch, tmp_path: Path):
    # REGRESSION: cancelled jobs must not download/process GCS uploads, and charges must be refunded.
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    import types

    monkeypatch.setattr(videos, "get_gcs_settings", lambda: types.SimpleNamespace(keep_uploads=True))
    monkeypatch.setattr(
        videos,
        "download_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not download cancelled jobs")),
    )

    db = Database(tmp_path / "vid_cancel_gcs.db")
    job_store = jobs.JobStore(db)
    points_store = PointsStore(db=db)

    user_id = backend_auth.UserStore(db=db).register_local_user(
        "cancelled_gcs@example.com", "testpassword123", "Runner"
    ).id
    job = job_store.create_job("job-cancelled-gcs", user_id)

    cost = 200
    meta = {"charge_id": job.id, "job_id": job.id, "model": "turbo"}
    points_store.spend(user_id, cost, reason="process_video", meta=meta)
    assert points_store.get_balance(user_id) == STARTING_POINTS_BALANCE - cost

    job_store.update_job(job.id, status="cancelled", message="Cancelled by user")

    settings = videos.ProcessingSettings()
    charge = videos._ChargeContext(user_id=user_id, cost=cost, reason="process_video", meta=meta)

    videos.run_gcs_video_processing(
        job_id=job.id,
        gcs_object_name="uploads/test.mp4",
        input_path=tmp_path / "in.mp4",
        output_path=tmp_path / "out.mp4",
        artifact_dir=tmp_path / "artifacts",
        settings=settings,
        job_store=job_store,
        points_store=points_store,
        charge=charge,
    )

    assert points_store.get_balance(user_id) == STARTING_POINTS_BALANCE
    cancelled = job_store.get_job(job.id)
    assert cancelled and cancelled.status == "cancelled"


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


def test_reprocess_job_creates_new_job(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="reprocess@example.com")
    calls: list[str] = []

    def fake_run(job_id, _input_path, _output_path, _artifact_dir, _settings, job_store, *_args, **_kwargs):
        calls.append(job_id)
        job_store.update_job(job_id, status="completed", progress=100, message="Done!")

    monkeypatch.setattr(videos, "run_video_processing", fake_run)

    source = client.post(
        "/videos/process",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(b"123"), "video/mp4")},
    )
    assert source.status_code == 200
    source_job_id = source.json()["id"]

    resp = client.post(f"/videos/jobs/{source_job_id}/reprocess", headers=headers, json={})
    assert resp.status_code == 200
    new_job_id = resp.json()["id"]
    assert new_job_id != source_job_id

    # Background task should have been scheduled (and executed by the test client)
    assert calls[0] == source_job_id
    assert calls[1] == new_job_id


def test_reprocess_job_requires_completed_source_job(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="reprocess_pending@example.com")

    monkeypatch.setattr(videos, "run_video_processing", lambda *args, **kwargs: None)
    source = client.post(
        "/videos/process",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(b"123"), "video/mp4")},
    )
    assert source.status_code == 200
    source_job_id = source.json()["id"]

    resp = client.post(f"/videos/jobs/{source_job_id}/reprocess", headers=headers, json={})
    assert resp.status_code == 400


def test_get_job_not_found(client: TestClient):
    headers = _auth_header(client, email="fetch@example.com")
    resp = client.get(f"/videos/jobs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_backend_wrappers_import():
    from backend.app.common import metrics as backend_metrics
    from backend.app.services import subtitles as backend_subtitles

    assert hasattr(backend_metrics, "should_log_metrics")
    assert hasattr(backend_subtitles, "create_styled_subtitle_file")


def test_cancel_job_success(client: TestClient, monkeypatch, tmp_path: Path):
    """Test successful job cancellation."""
    headers = _auth_header(client, email="cancel@example.com")
    called: dict[str, str] = {}

    def fake_run(job_id, *_args, **_kwargs):
        called["job"] = job_id

    monkeypatch.setattr(videos, "run_video_processing", fake_run)

    # Create a job via process endpoint
    resp = client.post(
        "/videos/process",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(b"123"), "video/mp4")},
    )
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    # Cancel the job (it should be in pending or processing)
    cancel_resp = client.post(f"/videos/jobs/{job_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert data["id"] == job_id
    assert data["status"] == "cancelled"
    assert data["message"] == "Cancelled by user"


def test_cancel_job_not_found(client: TestClient):
    """Test cancel for non-existent job."""
    headers = _auth_header(client, email="cancel_notfound@example.com")
    resp = client.post(f"/videos/jobs/{uuid.uuid4()}/cancel", headers=headers)
    assert resp.status_code == 404
