import types
import uuid
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.api.endpoints import export_routes, processing_tasks, videos
from backend.app.api.endpoints.settings import ProcessingSettings
from backend.app.core import auth as backend_auth
from backend.app.core import config
from backend.app.core.database import Database
from backend.app.db.models import DbJob
from backend.app.services import jobs, pricing
from backend.app.services.charge_plans import reserve_processing_charges
from backend.app.services.history import HistoryStore
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


def test_job_store_lifecycle(tmp_path: Path):
    db = Database()
    store = jobs.JobStore(db)

    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(f"job_{uuid.uuid4().hex}@example.com", "testpassword123", "Job")
        .id
    )

    job_id = f"job-{uuid.uuid4().hex}"
    job = store.create_job(job_id, user_id, result_data={"private": 1})
    assert job.result_data == {"private": 1}
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


def test_job_store_compare_and_set_preserves_cancelled_as_terminal() -> None:
    db = Database()
    store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(
            f"job-cas-{uuid.uuid4().hex}@example.com",
            "testpassword123",
            "Job CAS",
        )
        .id
    )
    job = store.create_job(f"job-cas-{uuid.uuid4().hex}", user_id)

    # REGRESSION: separate read/write worker updates could overwrite a
    # concurrent cancellation with processing, completion, or failure.
    assert store.update_job_if_status(
        job.id,
        expected_statuses={"pending"},
        status="processing",
        progress=1,
        message="Started",
    )
    assert store.update_job_if_status(
        job.id,
        expected_statuses={"pending", "processing"},
        status="cancelled",
        message="Cancelled by user",
    )
    assert not store.update_job_if_status(
        job.id,
        expected_statuses={"processing"},
        status="completed",
        progress=100,
        message="Done!",
        result_data={"video_path": "late.mp4"},
    )
    assert not store.update_job_if_status(
        job.id,
        expected_statuses={"processing"},
        status="failed",
        message="late failure",
    )
    assert not store.update_job_if_status(
        job.id,
        expected_statuses=set(),
        progress=75,
    )

    cancelled = store.get_job(job.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.progress == 1
    assert cancelled.message == "Cancelled by user"
    assert cancelled.result_data is None


def test_job_store_lists_are_scoped_unbounded_and_deterministic() -> None:
    db = Database()
    store = jobs.JobStore(db)
    user_store = backend_auth.UserStore(db)
    user_id = user_store.register_local_user(
        f"job-list-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Job List",
    ).id
    other_user_id = user_store.register_local_user(
        f"job-list-other-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Other Job List",
    ).id
    prefix = f"job-list-{uuid.uuid4().hex[:8]}"
    job_ids = [f"{prefix}-{sequence:02d}" for sequence in range(12)]
    for job_id in job_ids:
        store.create_job(job_id, user_id)
    other_job_id = f"{prefix}-other"
    store.create_job(other_job_id, other_user_id)
    with db.session() as session:
        for sequence, job_id in enumerate(job_ids):
            row = session.get(DbJob, job_id)
            assert row is not None
            row.created_at = 1_900_000_000
            row.updated_at = 1_900_000_000 + sequence
            row.status = "completed" if sequence % 2 == 0 else "processing"
        other_row = session.get(DbJob, other_job_id)
        assert other_row is not None
        other_row.created_at = 1_900_000_000
        other_row.updated_at = 1_900_000_000
        other_row.status = "completed"

    expected_ids = sorted(job_ids, reverse=True)
    assert [job.id for job in store.list_jobs_for_user(user_id)] == expected_ids[:10]
    assert [job.id for job in store.list_all_jobs_for_user(user_id)] == expected_ids
    assert store.count_jobs_for_user(user_id) == len(job_ids)
    assert store.count_active_jobs_for_user(user_id) == len(job_ids) // 2
    # REGRESSION: second-resolution timestamps previously left pagination
    # ordering nondeterministic and could duplicate or skip jobs across pages.
    assert [
        job.id
        for job in store.list_jobs_for_user_paginated(
            user_id,
            offset=2,
            limit=4,
        )
    ] == expected_ids[2:6]

    assert store.get_jobs([], user_id) == []
    owned = store.get_jobs(
        [job_ids[0], other_job_id],
        user_id,
    )
    assert [job.id for job in owned] == [job_ids[0]]

    assert (
        store.list_jobs_updated_before(
            2_000_000_000,
            set(),
        )
        == []
    )
    completed = store.list_jobs_updated_before(
        2_000_000_000,
        {"completed"},
    )
    assert {job.id for job in completed} >= {job_ids[sequence] for sequence in range(0, len(job_ids), 2)}
    assert other_job_id in {job.id for job in completed}
    created_before = store.list_jobs_created_before(1_900_000_001)
    created_before_ids = {job.id for job in created_before if job.id.startswith(prefix)}
    assert created_before_ids == {*job_ids, other_job_id}

    assert store.delete_jobs([], user_id) == 0
    assert (
        store.delete_jobs(
            [job_ids[0], other_job_id],
            user_id,
        )
        == 1
    )
    assert store.get_job(job_ids[0]) is None
    assert store.get_job(other_job_id) is not None
    store.update_job(f"missing-{uuid.uuid4().hex}", status="failed")


def test_history_store_purges_expired_job_payloads_only() -> None:
    db = Database()
    user = backend_auth.UserStore(db=db).register_local_user(
        f"history_{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "History",
    )
    history_store = HistoryStore(db)
    target_job_id = f"expired-{uuid.uuid4().hex}"
    retained_job_id = f"retained-{uuid.uuid4().hex}"
    history_store.record_event(
        user,
        "process_started",
        "Expired media",
        {"job_id": target_job_id},
    )
    history_store.record_event(
        user,
        "process_started",
        "Recent media",
        {"job_id": retained_job_id},
    )
    history_store.record_event(user, "login", "Signed in", {})

    # REGRESSION: deleting a project previously left its filename-bearing
    # processing history behind indefinitely.
    assert history_store.delete_job_events([target_job_id]) == 1
    remaining = history_store.recent_for_user(user)
    remaining_job_ids = {event.data.get("job_id") for event in remaining if event.data.get("job_id")}
    assert target_job_id not in remaining_job_ids
    assert retained_job_id in remaining_job_ids
    assert any(event.kind == "login" for event in remaining)


def test_history_store_empty_or_unmatched_purge_is_a_noop() -> None:
    db = Database()
    user = backend_auth.UserStore(db).register_local_user(
        f"history-noop-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "History Noop",
    )
    history_store = HistoryStore(db)
    event = history_store.record_event(
        user,
        "login",
        "Signed in",
        {"scope": "account"},
    )

    assert history_store.delete_job_events([]) == 0
    assert history_store.delete_job_events(["unknown-job"]) == 0
    remaining = history_store.all_for_user(user)
    assert [item.summary for item in remaining] == [event.summary]


def test_run_video_processing_success(monkeypatch, tmp_path: Path):
    # Keep paths relative to tmp_path so relative_to() succeeds
    monkeypatch.setattr(config.settings, "project_root", tmp_path)

    db = Database()
    store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(f"runner_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner")
        .id
    )
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

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", fake_normalize)
    settings = ProcessingSettings()
    processing_tasks.run_video_processing(job.id, input_path, output_path, output_path.parent, settings, store)

    finished = store.get_job(job.id)
    assert finished and finished.status == "completed"
    assert finished.progress == 100
    assert finished.result_data["video_path"].endswith("out.mp4")
    assert finished.result_data["transcribe_provider"] == "local"


def test_run_video_processing_failure(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config.settings, "project_root", tmp_path)

    db = Database()
    store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(f"runner_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner")
        .id
    )
    job = store.create_job(f"job-fail-{uuid.uuid4().hex}", user_id)

    input_path = tmp_path / "input2.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "out2.mp4"

    def boom(*args, **kwargs):
        raise RuntimeError("explode")

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", boom)
    settings = ProcessingSettings()
    processing_tasks.run_video_processing(job.id, input_path, output_path, tmp_path / "artifacts2", settings, store)

    failed = store.get_job(job.id)
    assert failed and failed.status == "failed"
    # Note: sanitize_message only masks paths, not generic errors, so "explode" persists.
    assert failed.message is not None and "explode" in failed.message


def test_run_video_processing_handles_path_only(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    db = Database()
    store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(f"runner_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner")
        .id
    )
    job = store.create_job(f"job-path-{uuid.uuid4().hex}", user_id)

    input_path = tmp_path / "input3.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts3" / "out3.mp4"

    def fake_normalize(*_args, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        return output_path

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", fake_normalize)
    settings = ProcessingSettings()
    processing_tasks.run_video_processing(job.id, input_path, output_path, output_path.parent, settings, store)

    finished = store.get_job(job.id)
    assert finished and finished.status == "completed"


def test_run_video_processing_records_duration_and_empty_resolution(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    db = Database()
    store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(f"runner_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner")
        .id
    )
    job = store.create_job(f"job-duration-{uuid.uuid4().hex}", user_id)

    input_path = tmp_path / "input-duration.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts-duration" / "out.mp4"

    monkeypatch.setattr(
        processing_tasks,
        "probe_media",
        lambda _path: types.SimpleNamespace(duration_s=12.5, width=1920, height=1080),
    )

    def fake_normalize(*_args, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        return output_path

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", fake_normalize)
    settings = ProcessingSettings()
    processing_tasks.run_video_processing(job.id, input_path, output_path, output_path.parent, settings, store)

    finished = store.get_job(job.id)
    assert finished and finished.status == "completed"
    assert finished.result_data["duration_seconds"] == 12.5
    assert finished.result_data["resolution"] == ""


def test_run_video_processing_does_not_restart_cancelled_job_and_refunds(monkeypatch, tmp_path: Path):
    # REGRESSION: a cancelled job must never flip back to processing, and charges must be refunded.
    monkeypatch.setattr(config.settings, "project_root", tmp_path)

    db = Database()
    job_store = jobs.JobStore(db)
    points_store = PointsStore(db=db)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(f"cancelled_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner")
        .id
    )
    job = job_store.create_job(f"job-cancelled-{uuid.uuid4().hex}", user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
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
    expected_charge = pricing.credits_for_video_duration(60.0)
    assert points_store.get_balance(user_id) == starting_balance - expected_charge

    job_store.update_job(job.id, status="cancelled", message="Cancelled by user")

    input_path = tmp_path / "input_cancel.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts_cancel" / "out.mp4"

    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not process cancelled jobs")),
    )

    settings = ProcessingSettings()
    processing_tasks.run_video_processing(
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


def test_run_video_processing_failure_cannot_overwrite_concurrent_cancellation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: a worker exception after cancellation used to replace the
    # terminal cancelled state with failed through an unconditional update.
    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    db = Database()
    store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(
            f"cancel-failure-race-{uuid.uuid4().hex}@example.com",
            "testpassword123",
            "Cancellation Race",
        )
        .id
    )
    job = store.create_job(f"job-cancel-failure-{uuid.uuid4().hex}", user_id)
    input_path = tmp_path / "cancel-failure-input.mp4"
    input_path.write_bytes(b"data")
    artifact_dir = tmp_path / "cancel-failure-artifacts"
    output_path = artifact_dir / "out.mp4"

    def cancel_then_fail(*_args, **_kwargs):
        store.update_job(job.id, status="cancelled", message="Cancelled by user")
        raise RuntimeError("late worker failure")

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", cancel_then_fail)

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        store,
    )

    cancelled = store.get_job(job.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.message == "Cancelled by user"


def test_run_video_processing_completion_cannot_overwrite_concurrent_cancellation(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: cancellation could win after the worker's final status read
    # but lose to its later unconditional completed write.
    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    db = Database()
    store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(
            f"cancel-completion-race-{uuid.uuid4().hex}@example.com",
            "testpassword123",
            "Completion Race",
        )
        .id
    )
    job = store.create_job(f"job-cancel-completion-{uuid.uuid4().hex}", user_id)
    input_path = tmp_path / "cancel-completion-input.mp4"
    input_path.write_bytes(b"data")
    artifact_dir = tmp_path / "cancel-completion-artifacts"
    output_path = artifact_dir / "out.mp4"

    def cancel_after_final_check(*_args, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"late output")
        return output_path

    original_update = store.update_job_if_status

    def race_completion(job_id: str, **kwargs):
        if kwargs.get("status") == "completed":
            store.update_job(job_id, status="cancelled", message="Cancelled by user")
        return original_update(job_id, **kwargs)

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", cancel_after_final_check)
    monkeypatch.setattr(store, "update_job_if_status", race_completion)

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        store,
    )

    cancelled = store.get_job(job.id)
    assert cancelled is not None
    assert cancelled.status == "cancelled"
    assert cancelled.message == "Cancelled by user"
    assert cancelled.result_data is None


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
            "use_llm": True,
        },
    )

    assert response.status_code == 200
    assert captured["provider"] == "mock"
    assert captured["stt_model"] == "mock-caption-v1"
    assert captured["use_llm"] is False


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


def test_reprocess_rejects_authoritative_quote_increase_before_financial_or_provider_work(
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
        metadata={"authorized_credits": 25},
    )
    assert source.status_code == 200
    source_job_id = source.json()["id"]
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    points_store = PointsStore(Database())
    balance_before = points_store.get_balance(user_id)

    # REGRESSION: a stored source confirmed at 180.000 seconds can be resolved
    # by the authoritative reprocess probe as 180.001. Reprocess must require a
    # new confirmation without creating or reserving a second job.
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
        json={"authorized_credits": 25},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "Processing quote changed",
        "code": "PROCESSING_QUOTE_CHANGED",
        "details": {
            "duration_seconds": 180.001,
            "required_credits": 60,
        },
    }
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
