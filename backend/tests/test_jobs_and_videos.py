import io
import types
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.app.api.endpoints import processing_tasks
from backend.app.core import auth as backend_auth
from backend.app.core import config
from backend.app.core.database import Database
from backend.app.services import jobs
from backend.app.services import pricing
from backend.app.services.charge_plans import reserve_processing_charges
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import UsageLedgerStore


def _auth_header(client: TestClient, email: str | None = None) -> dict[str, str]:
    resolved_email = email or f"video_{uuid.uuid4().hex}@example.com"
    client.post("/auth/register", json={"email": resolved_email, "password": "testpassword123", "name": "Video"})
    token = client.post(
        "/auth/token",
        data={"username": resolved_email, "password": "testpassword123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_job_store_lifecycle(tmp_path: Path):
    db = Database()
    store = jobs.JobStore(db)

    user_id = backend_auth.UserStore(db=db).register_local_user(
        f"job_{uuid.uuid4().hex}@example.com", "testpassword123", "Job"
    ).id

    job_id = f"job-{uuid.uuid4().hex}"
    job = store.create_job(job_id, user_id)
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
    j2 = store.create_job(f"job-{uuid.uuid4().hex}", user_id)
    j3 = store.create_job(f"job-{uuid.uuid4().hex}", user_id)
    store.delete_jobs_for_user(user_id)
    assert store.get_job(j2.id) is None
    assert store.get_job(j3.id) is None
    assert len(store.list_jobs_for_user(user_id)) == 0


def test_run_video_processing_success(monkeypatch, tmp_path: Path):
    # Keep paths relative to tmp_path so relative_to() succeeds
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    db = Database()
    store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user(
        f"runner_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner"
    ).id
    job = store.create_job(f"job-success-{uuid.uuid4().hex}", user_id)

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts" / "out.mp4"

    def fake_normalize(input_path, output_path, **kwargs):
        kwargs["progress_callback"]("halfway", 50)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        # Update mock to match new SocialContent structure (generic.title_en)
        social = types.SimpleNamespace(generic=types.SimpleNamespace(title_en="hi"))
        return output_path, social

    monkeypatch.setattr(processing_tasks, "normalize_and_stub_subtitles", fake_normalize)
    settings = videos.ProcessingSettings()
    videos.run_video_processing(job.id, input_path, output_path, output_path.parent, settings, store)

    finished = store.get_job(job.id)
    assert finished and finished.status == "completed"
    assert finished.progress == 100
    assert finished.result_data["video_path"].endswith("out.mp4")


def test_run_video_processing_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    db = Database()
    store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user(
        f"runner_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner"
    ).id
    job = store.create_job(f"job-fail-{uuid.uuid4().hex}", user_id)

    input_path = tmp_path / "input2.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "out2.mp4"

    def boom(*args, **kwargs):
        raise RuntimeError("explode")

    monkeypatch.setattr(processing_tasks, "normalize_and_stub_subtitles", boom)
    settings = videos.ProcessingSettings()
    videos.run_video_processing(job.id, input_path, output_path, tmp_path / "artifacts2", settings, store)

    failed = store.get_job(job.id)
    assert failed and failed.status == "failed"
    # Note: sanitize_message only masks paths, not generic errors, so "explode" persists.
    assert failed.message is not None and "explode" in failed.message


def test_run_video_processing_handles_path_only(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)
    db = Database()
    store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user(
        f"runner_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner"
    ).id
    job = store.create_job(f"job-path-{uuid.uuid4().hex}", user_id)

    input_path = tmp_path / "input3.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts3" / "out3.mp4"

    def fake_normalize(*_args, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        return output_path

    monkeypatch.setattr(processing_tasks, "normalize_and_stub_subtitles", fake_normalize)
    settings = videos.ProcessingSettings()
    videos.run_video_processing(job.id, input_path, output_path, output_path.parent, settings, store)

    finished = store.get_job(job.id)
    assert finished and finished.status == "completed"


def test_run_video_processing_does_not_restart_cancelled_job_and_refunds(monkeypatch, tmp_path: Path):
    # REGRESSION: a cancelled job must never flip back to processing, and charges must be refunded.
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    db = Database()
    job_store = jobs.JobStore(db)
    points_store = PointsStore(db=db)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    user_id = backend_auth.UserStore(db=db).register_local_user(
        f"cancelled_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner"
    ).id
    job = job_store.create_job(f"job-cancelled-{uuid.uuid4().hex}", user_id)
    starting_balance = points_store.get_balance(user_id)

    llm_models = pricing.resolve_llm_models("standard")
    charge_plan, _ = reserve_processing_charges(
        ledger_store=ledger_store,
        user_id=user_id,
        job_id=job.id,
        tier="standard",
        duration_seconds=60.0,
        use_llm=False,
        llm_model=llm_models.social,
        provider="groq",
        stt_model=pricing.resolve_transcribe_model("standard"),
    )
    expected_charge = pricing.credits_for_minutes(
        tier="standard",
        duration_seconds=60.0,
        min_credits=config.CREDITS_MIN_TRANSCRIBE["standard"],
    )
    assert points_store.get_balance(user_id) == starting_balance - expected_charge

    job_store.update_job(job.id, status="cancelled", message="Cancelled by user")

    input_path = tmp_path / "input_cancel.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts_cancel" / "out.mp4"

    monkeypatch.setattr(
        processing_tasks,
        "normalize_and_stub_subtitles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not process cancelled jobs")),
    )

    settings = videos.ProcessingSettings()
    videos.run_video_processing(
        job.id,
        input_path,
        output_path,
        output_path.parent,
        settings,
        job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    assert points_store.get_balance(user_id) == starting_balance
    cancelled = job_store.get_job(job.id)
    assert cancelled and cancelled.status == "cancelled"


def test_run_gcs_video_processing_does_not_restart_cancelled_job_and_refunds(monkeypatch, tmp_path: Path):
    # REGRESSION: cancelled jobs must not download/process GCS uploads, and charges must be refunded.
    monkeypatch.setattr(videos.config, "PROJECT_ROOT", tmp_path)

    import types

    monkeypatch.setattr(processing_tasks, "get_gcs_settings", lambda: types.SimpleNamespace(keep_uploads=True))
    monkeypatch.setattr(
        processing_tasks,
        "download_object",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not download cancelled jobs")),
    )

    db = Database()
    job_store = jobs.JobStore(db)
    points_store = PointsStore(db=db)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    user_id = backend_auth.UserStore(db=db).register_local_user(
        f"cancelled_gcs_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner"
    ).id
    job = job_store.create_job(f"job-cancelled-gcs-{uuid.uuid4().hex}", user_id)
    starting_balance = points_store.get_balance(user_id)

    llm_models = pricing.resolve_llm_models("standard")
    charge_plan, _ = reserve_processing_charges(
        ledger_store=ledger_store,
        user_id=user_id,
        job_id=job.id,
        tier="standard",
        duration_seconds=60.0,
        use_llm=False,
        llm_model=llm_models.social,
        provider="groq",
        stt_model=pricing.resolve_transcribe_model("standard"),
    )
    expected_charge = pricing.credits_for_minutes(
        tier="standard",
        duration_seconds=60.0,
        min_credits=config.CREDITS_MIN_TRANSCRIBE["standard"],
    )
    assert points_store.get_balance(user_id) == starting_balance - expected_charge

    job_store.update_job(job.id, status="cancelled", message="Cancelled by user")

    settings = videos.ProcessingSettings()
    videos.run_gcs_video_processing(
        job_id=job.id,
        gcs_object_name="uploads/test.mp4",
        input_path=tmp_path / "in.mp4",
        output_path=tmp_path / "out.mp4",
        artifact_dir=tmp_path / "artifacts",
        settings=settings,
        job_store=job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    assert points_store.get_balance(user_id) == starting_balance
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

    # Must patch at the location where the function is CALLED, not where it's defined
    from backend.app.api.endpoints import reprocess_routes
    monkeypatch.setattr(reprocess_routes, "run_video_processing", fake_run)
    monkeypatch.setattr(videos, "run_video_processing", fake_run)
    
    # Mock probe_media to return valid probe result for fake video data
    fake_probe_result = types.SimpleNamespace(duration_s=10.0, width=1920, height=1080)
    monkeypatch.setattr(reprocess_routes, "probe_media", lambda path: fake_probe_result)
    monkeypatch.setattr(videos, "probe_media", lambda path: fake_probe_result)

    # Top up points to avoid 402
    from backend.app.core.database import Database
    from backend.app.services.points import PointsStore
    user_resp = client.get("/auth/me", headers=headers)
    assert user_resp.status_code == 200
    user_id = user_resp.json()["id"]
    PointsStore(db=Database()).credit(user_id, 1000, "test_topup")

    source = client.post(
        "/videos/process",
        headers=headers,
        files={"file": ("clip.mp4", io.BytesIO(b"123"), "video/mp4")},
    )
    assert source.status_code == 200
    source_job_id = source.json()["id"]

    # The fake_run should have been called for the source job, completing it
    assert source_job_id in calls

    resp = client.post(f"/videos/jobs/{source_job_id}/reprocess", headers=headers, json={})
    print(f"DEBUG: reprocess response status={resp.status_code}, body={resp.text}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    new_job_id = resp.json()["id"]
    assert new_job_id != source_job_id

    # Both jobs should have been processed
    assert len(calls) == 2
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
    headers = _auth_header(client)
    resp = client.get(f"/videos/jobs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_backend_wrappers_import():
    from backend.app.core import metrics as backend_metrics
    from backend.app.services import subtitles as backend_subtitles

    assert hasattr(backend_metrics, "should_log_metrics")
    assert hasattr(backend_subtitles, "create_styled_subtitle_file")


def test_cancel_job_success(client: TestClient, monkeypatch, tmp_path: Path):
    """Test successful job cancellation."""
    headers = _auth_header(client)
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
    headers = _auth_header(client)
    resp = client.post(f"/videos/jobs/{uuid.uuid4()}/cancel", headers=headers)
    assert resp.status_code == 404
