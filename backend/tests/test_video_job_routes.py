import types
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.endpoints import export_routes, videos
from backend.app.core import config
from backend.app.core.database import Database
from backend.app.services import jobs
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import ChargePlan, UsageLedgerStore
from backend.tests.process_stream import post_process_stream


def _auth_header(client: TestClient, email: str | None = None) -> dict[str, str]:
    if email:
        local, _, domain = email.partition("@")
        resolved_email = f"{local}_{uuid.uuid4().hex}@{domain or 'example.com'}"
    else:
        resolved_email = f"video_{uuid.uuid4().hex}@example.com"
    client.post("/auth/register", json={"email": resolved_email, "password": "testpassword123", "name": "Video"})
    token_resp = client.post(
        "/auth/token",
        data={"username": resolved_email, "password": "testpassword123"},
    )
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Ensure user has sufficient credits for testing
    me_resp = client.get("/auth/me", headers=headers)
    if me_resp.status_code == 200:
        user_id = me_resp.json().get("id")
        if user_id:
            db = Database()
            points_store = PointsStore(db=db)
            points_store.ensure_account(user_id)
            # Grant additional credits for tests (in case user already existed with low balance)
            points_store.credit(
                user_id,
                1000,
                "test_credit",
                {"source": "unit_tests"},
                paid_credit_delta=1000,
            )

    return headers


def test_process_video_rejects_invalid_extension(client: TestClient):
    headers = _auth_header(client, email="reject@example.com")
    resp = post_process_stream(
        client,
        headers,
        filename="notes.txt",
        content=b"nope",
        content_type="text/plain",
    )
    assert resp.status_code == 400


def test_process_video_creates_job(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="process@example.com")
    called: dict[str, str] = {}

    def fake_run(job_id, *_args, **_kwargs):
        called["job"] = job_id

    monkeypatch.setattr(videos, "run_video_processing", fake_run)
    resp = post_process_stream(client, headers, content=b"123")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"]
    assert called["job"] == body["id"]

    detail = client.get(f"/videos/jobs/{body['id']}", headers=headers)
    assert detail.status_code == 200


def test_process_video_accepts_openai_provider_override(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="process-openai@example.com")
    captured: dict[str, object] = {}
    monkeypatch.setattr(videos.settings, "mock_external_services", False)

    monkeypatch.setattr(videos, "run_video_processing", lambda *args, **kwargs: None)

    def fake_reserve_processing_charges(*args, **kwargs):
        captured.update(kwargs)
        return ChargePlan(), 5000

    monkeypatch.setattr(videos, "reserve_processing_charges", fake_reserve_processing_charges)

    resp = post_process_stream(
        client,
        headers,
        content=b"123",
        metadata={
            "transcribe_tier": "pro",
            "transcribe_provider": "openai",
            "openai_model": "whisper-1",
        },
    )

    assert resp.status_code == 200
    assert captured["provider"] == "openai"
    assert captured["stt_model"] == "whisper-1"


def test_process_video_forces_mock_before_charge_planning(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="process-forced-mock@example.com")
    captured: dict[str, object] = {}
    monkeypatch.setattr(videos.settings, "mock_external_services", True)
    monkeypatch.setattr(videos, "run_video_processing", lambda *args, **kwargs: None)

    def fake_reserve_processing_charges(*args, **kwargs):
        captured.update(kwargs)
        return ChargePlan(), 5000

    monkeypatch.setattr(videos, "reserve_processing_charges", fake_reserve_processing_charges)

    response = post_process_stream(
        client,
        headers,
        content=b"123",
        metadata={
            "transcribe_tier": "pro",
            "transcribe_provider": "openai",
            "openai_model": "gpt-4o-transcribe",
        },
    )

    assert response.status_code == 200
    assert captured["provider"] == "mock"
    assert captured["stt_model"] == "mock-caption-v1"


def test_process_video_rejects_removed_text_generation_setting(
    client: TestClient,
) -> None:
    # REGRESSION: a stale client must not silently re-enable the retired surface.
    headers = _auth_header(client, email="process-retired-setting@example.com")

    response = post_process_stream(
        client,
        headers,
        content=b"123",
        metadata={"use_llm": True},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid upload metadata"


def test_process_video_accepts_local_provider_override(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="process-local@example.com")
    captured: dict[str, object] = {}
    monkeypatch.setattr(videos.settings, "mock_external_services", False)

    monkeypatch.setattr(videos, "run_video_processing", lambda *args, **kwargs: None)

    def fake_reserve_processing_charges(*args, **kwargs):
        captured.update(kwargs)
        return ChargePlan(), 5000

    monkeypatch.setattr(videos, "reserve_processing_charges", fake_reserve_processing_charges)

    resp = post_process_stream(
        client,
        headers,
        content=b"123",
        metadata={
            "transcribe_tier": "standard",
            "transcribe_provider": "local",
        },
    )

    assert resp.status_code == 200
    assert captured["provider"] == "local"
    assert captured["stt_model"] == config.settings.transcribe_tier_model["standard"]


def test_export_video_falls_back_to_result_video_path(client: TestClient, monkeypatch, tmp_path: Path):
    # REGRESSION: completed jobs must remain exportable after uploads cleanup if the preview copy exists.
    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    headers = _auth_header(client, email="export-preview@example.com")
    user = client.get("/auth/me", headers=headers).json()

    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(export_routes, "data_roots", lambda: (data_dir, uploads_dir, artifacts_dir))
    db = Database()
    store = jobs.JobStore(db)
    job_id = f"job-export-{uuid.uuid4().hex}"
    store.create_job(job_id, user["id"])

    artifact_dir = artifacts_dir / job_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    preview_path = artifact_dir / "processed.mp4"
    preview_path.write_bytes(b"preview")

    store.update_job(
        job_id,
        status="completed",
        progress=100,
        message="Done!",
        result_data={
            "video_path": preview_path.relative_to(data_dir).as_posix(),
            "artifacts_dir": artifact_dir.relative_to(data_dir).as_posix(),
            "public_url": f"/static/{preview_path.relative_to(data_dir).as_posix()}",
        },
    )

    captured: dict[str, Path] = {}

    def fake_generate_variant(job_id: str, input_video, artifact_dir, resolution, *_args, **_kwargs):
        captured["input_video"] = input_video
        out = artifact_dir / f"export_{resolution}.mp4"
        out.write_bytes(b"variant")
        return out

    monkeypatch.setattr(export_routes, "generate_video_variant", fake_generate_variant)

    resp = client.post(
        f"/videos/jobs/{job_id}/export",
        headers=headers,
        json={"resolution": "1080x1920"},
    )

    assert resp.status_code == 200
    assert captured["input_video"] == preview_path


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
    PointsStore(db=Database()).credit(
        user_id,
        1000,
        "test_topup",
        paid_credit_delta=1000,
    )

    source = post_process_stream(client, headers, content=b"123")
    assert source.status_code == 200
    source_job_id = source.json()["id"]

    # The fake_run should have been called for the source job, completing it
    assert source_job_id in calls

    resp = client.post(
        f"/videos/jobs/{source_job_id}/reprocess",
        headers=headers,
        json={"authorized_credits": 100},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    new_job_id = resp.json()["id"]
    assert new_job_id != source_job_id

    # Both jobs should have been processed
    assert len(calls) == 2
    assert calls[0] == source_job_id
    assert calls[1] == new_job_id


def test_reprocess_rejects_authoritative_duration_above_launch_cap_before_financial_or_provider_work(
    client: TestClient,
    monkeypatch,
) -> None:
    headers = _auth_header(client, email="reprocess_quote@example.com")
    from unittest.mock import MagicMock

    from backend.app.api.endpoints import reprocess_routes
    from backend.app.services.ffmpeg_utils import MediaProbe
    from backend.app.services.jobs import JobStore

    def complete_source(
        job_id,
        _input_path,
        _output_path,
        _artifact_dir,
        _settings,
        job_store,
        *_args,
        **_kwargs,
    ) -> None:
        job_store.update_job(job_id, status="completed", progress=100, message="Done!")

    monkeypatch.setattr(videos, "run_video_processing", complete_source)
    monkeypatch.setattr(
        videos,
        "probe_media",
        lambda _path: MediaProbe(duration_s=180.000, audio_codec="aac"),
    )
    source = post_process_stream(
        client,
        headers,
        content=b"private-source",
        metadata={"authorized_credits": 30},
    )
    assert source.status_code == 200
    source_job_id = source.json()["id"]
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    points_store = PointsStore(Database())
    balance_before = points_store.get_balance(user_id)

    # REGRESSION: a stored source confirmed at 180.000 seconds can be resolved
    # by the authoritative reprocess probe as 180.001. Reprocess must fail the
    # launch cap without creating or reserving a second job.
    charge_preflight = MagicMock(
        side_effect=AssertionError("quote check must precede wallet preflight"),
    )
    uuid4 = MagicMock(
        side_effect=AssertionError("quote check must precede job id allocation"),
    )
    copy_file = MagicMock(
        side_effect=AssertionError("quote check must precede source copying"),
    )
    create_job = MagicMock(
        side_effect=AssertionError("quote check must precede job creation"),
    )
    reserve_plan = MagicMock(
        side_effect=AssertionError("quote check must precede reservation"),
    )
    ledger_reserve = MagicMock(
        side_effect=AssertionError("quote check must precede ledger reservation"),
    )
    provider_dispatch = MagicMock(
        side_effect=AssertionError("quote check must precede provider dispatch"),
    )
    monkeypatch.setattr(
        reprocess_routes,
        "probe_media",
        lambda _path: MediaProbe(duration_s=180.001, audio_codec="aac"),
    )
    monkeypatch.setattr(reprocess_routes, "preflight_processing_charges", charge_preflight)
    monkeypatch.setattr(reprocess_routes.uuid, "uuid4", uuid4)
    monkeypatch.setattr(reprocess_routes, "link_or_copy_file", copy_file)
    monkeypatch.setattr(JobStore, "create_job", create_job)
    monkeypatch.setattr(reprocess_routes, "reserve_processing_charges", reserve_plan)
    monkeypatch.setattr(UsageLedgerStore, "reserve", ledger_reserve)
    monkeypatch.setattr(reprocess_routes, "run_video_processing", provider_dispatch)

    response = client.post(
        f"/videos/jobs/{source_job_id}/reprocess",
        headers=headers,
        json={"authorized_credits": 30},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Video too long (max 3.0 minutes)"}
    charge_preflight.assert_not_called()
    uuid4.assert_not_called()
    copy_file.assert_not_called()
    create_job.assert_not_called()
    reserve_plan.assert_not_called()
    ledger_reserve.assert_not_called()
    provider_dispatch.assert_not_called()
    assert points_store.get_balance(user_id) == balance_before
    assert [job.id for job in JobStore(Database()).list_jobs_for_user(user_id)] == [
        source_job_id,
    ]


def test_reprocess_job_requires_completed_source_job(client: TestClient, monkeypatch):
    headers = _auth_header(client, email="reprocess_pending@example.com")

    monkeypatch.setattr(videos, "run_video_processing", lambda *args, **kwargs: None)
    source = post_process_stream(client, headers, content=b"123")
    assert source.status_code == 200
    source_job_id = source.json()["id"]

    resp = client.post(
        f"/videos/jobs/{source_job_id}/reprocess",
        headers=headers,
        json={"authorized_credits": 100},
    )
    assert resp.status_code == 400


def test_get_job_not_found(client: TestClient):
    headers = _auth_header(client)
    resp = client.get(f"/videos/jobs/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404


def test_cancel_job_success(client: TestClient, monkeypatch, tmp_path: Path):
    """Test successful job cancellation."""
    headers = _auth_header(client)
    called: dict[str, str] = {}

    def fake_run(job_id, *_args, **_kwargs):
        called["job"] = job_id

    monkeypatch.setattr(videos, "run_video_processing", fake_run)

    # Create a job via process endpoint
    resp = post_process_stream(client, headers, content=b"123")
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    # Cancel the job (it should be in pending or processing)
    cancel_resp = client.post(f"/videos/jobs/{job_id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert data["id"] == job_id
    assert data["status"] == "cancelling"
    assert data["message"] == "Cancellation requested"


def test_cancel_job_not_found(client: TestClient):
    """Test cancel for non-existent job."""
    headers = _auth_header(client)
    resp = client.post(f"/videos/jobs/{uuid.uuid4()}/cancel", headers=headers)
    assert resp.status_code == 404
