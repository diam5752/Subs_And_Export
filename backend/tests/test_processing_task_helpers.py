from __future__ import annotations

import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from backend.app.api.endpoints import processing_tasks
from backend.app.api.endpoints.settings import ProcessingSettings
from backend.app.core import auth as backend_auth
from backend.app.core import config
from backend.app.core.database import Database
from backend.app.db.models import DbHistoryEvent, DbUser
from backend.app.services import jobs
from backend.app.services.history import HistoryStore
from backend.app.services.usage_ledger import ChargePlan


def test_refund_charge_best_effort_handles_missing_inputs_and_errors(monkeypatch) -> None:
    ledger_store = MagicMock()
    processing_tasks.refund_charge_best_effort(None, None, status="failed", error="boom")

    reservation_a = types.SimpleNamespace(user_id="user-1", action="transcription")
    reservation_b = types.SimpleNamespace(user_id="user-1", action="social")
    charge_plan = ChargePlan(transcription=reservation_a, social_copy=reservation_b)
    ledger_store.refund_if_reserved.side_effect = [None, RuntimeError("refund failed")]
    logger_spy = MagicMock()
    monkeypatch.setattr(processing_tasks, "logger", types.SimpleNamespace(exception=logger_spy))

    processing_tasks.refund_charge_best_effort(ledger_store, charge_plan, status="cancelled", error="cancelled")

    assert ledger_store.refund_if_reserved.call_count == 2
    logger_spy.assert_called_once()


def test_record_event_safe_swallow_failures() -> None:
    history_store = MagicMock()
    user = types.SimpleNamespace(id="user-1")

    processing_tasks.record_event_safe(None, user, "kind", "summary", {})
    processing_tasks.record_event_safe(history_store, None, "kind", "summary", {})

    history_store.record_event.side_effect = RuntimeError("boom")
    processing_tasks.record_event_safe(history_store, user, "kind", "summary", {"x": 1})

    history_store.record_event.assert_called_once_with(user, "kind", "summary", {"x": 1})


def test_history_store_never_recreates_user_for_late_worker_event() -> None:
    db = Database()
    user_store = backend_auth.UserStore(db)
    user = user_store.register_local_user(
        f"late-history-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Late History",
    )
    history_store = HistoryStore(db)
    user_store.delete_user(user.id)

    with pytest.raises(
        ValueError,
        match="account that no longer exists",
    ):
        history_store.record_event(
            user,
            "process_completed",
            "Late completion",
            {"job_id": "deleted-job"},
        )

    with db.session() as session:
        assert session.get(DbUser, user.id) is None
        assert session.scalar(select(DbHistoryEvent).where(DbHistoryEvent.user_id == user.id).limit(1)) is None


def test_run_video_processing_continues_when_gcs_upload_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config.settings, "project_root", tmp_path)

    db = Database()
    job_store = jobs.JobStore(db)
    user_id = (
        backend_auth.UserStore(db=db)
        .register_local_user(f"gcs_warn_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner")
        .id
    )
    job = job_store.create_job(f"job-gcs-warn-{uuid.uuid4().hex}", user_id)

    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"data")
    output_path = tmp_path / "artifacts" / "out.mp4"
    artifact_dir = output_path.parent

    def fake_normalize(*_args, **_kwargs):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        (artifact_dir / "transcription.json").write_text("[]", encoding="utf-8")
        return output_path

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", fake_normalize)
    monkeypatch.setattr(processing_tasks, "get_gcs_settings", lambda: types.SimpleNamespace(static_prefix="static"))
    monkeypatch.setattr(
        processing_tasks, "upload_object", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("upload failed"))
    )
    warning_spy = MagicMock()
    monkeypatch.setattr(
        processing_tasks, "logger", types.SimpleNamespace(debug=lambda *args, **kwargs: None, warning=warning_spy)
    )

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
    )

    finished = job_store.get_job(job.id)
    assert finished and finished.status == "completed"
    warning_spy.assert_called_once()


def test_run_gcs_video_processing_fails_fast_without_configuration() -> None:
    job_store = MagicMock()
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(user_id="u1", action="transcription"), social_copy=None
    )

    processing_tasks.run_gcs_video_processing(
        job_id="job-1",
        gcs_object_name="uploads/file.mp4",
        input_path=Path("input.mp4"),
        output_path=Path("output.mp4"),
        artifact_dir=Path("artifacts"),
        settings=ProcessingSettings(),
        job_store=job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    job_store.update_job.assert_called_once_with("job-1", status="failed", message="GCS is not configured")
    ledger_store.refund_if_reserved.assert_called_once()


def test_run_video_processing_aborts_missing_job_without_recreating_user(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user_store = backend_auth.UserStore(db=db)
    user = user_store.register_local_user(
        f"deleted-worker-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Deleted Worker",
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(
        f"job-deleted-worker-{uuid.uuid4().hex}",
        user.id,
    )
    user_store.delete_user(user.id)

    uploads_dir = tmp_path / "uploads"
    artifact_dir = tmp_path / "artifacts" / job.id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    input_path = uploads_dir / f"{job.id}_input.mp4"
    output_path = artifact_dir / "processed.mp4"
    input_path.write_bytes(b"late upload")
    output_path.write_bytes(b"late artifact")
    unrelated_upload = uploads_dir / "unrelated_input.mp4"
    unrelated_artifact = tmp_path / "artifacts" / "unrelated" / "keep.txt"
    unrelated_upload.write_bytes(b"keep")
    unrelated_artifact.parent.mkdir(parents=True)
    unrelated_artifact.write_text("keep", encoding="utf-8")

    history_store = HistoryStore(db)
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id=user.id,
            action="transcription",
        ),
        social_copy=None,
    )
    pipeline = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        pipeline,
    )

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        history_store,
        user,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    pipeline.assert_not_called()
    ledger_store.refund_if_reserved.assert_called_once()
    assert not input_path.exists()
    assert not artifact_dir.exists()
    assert unrelated_upload.exists()
    assert unrelated_artifact.exists()
    with db.session() as session:
        assert session.get(DbUser, user.id) is None
        assert session.scalar(select(DbHistoryEvent).where(DbHistoryEvent.user_id == user.id).limit(1)) is None


def test_run_video_processing_cleans_up_if_job_disappears_mid_run(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user_store = backend_auth.UserStore(db=db)
    user = user_store.register_local_user(
        f"mid-run-delete-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Mid-run Delete",
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(
        f"job-mid-run-delete-{uuid.uuid4().hex}",
        user.id,
    )
    uploads_dir = tmp_path / "uploads"
    artifact_dir = tmp_path / "artifacts" / job.id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    input_path = uploads_dir / f"{job.id}_input.mp4"
    output_path = artifact_dir / "processed.mp4"
    input_path.write_bytes(b"input")

    def delete_during_pipeline(*_args, **kwargs):
        user_store.delete_user(user.id)
        output_path.write_bytes(b"late artifact")
        kwargs["check_cancelled"]()
        raise AssertionError("missing job should abort processing")

    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        delete_during_pipeline,
    )
    history_store = HistoryStore(db)
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id=user.id,
            action="transcription",
        ),
        social_copy=None,
    )

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        history_store,
        user,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    ledger_store.refund_if_reserved.assert_called_once()
    assert not input_path.exists()
    assert not artifact_dir.exists()
    with db.session() as session:
        assert session.get(DbUser, user.id) is None
        assert session.scalar(select(DbHistoryEvent).where(DbHistoryEvent.user_id == user.id).limit(1)) is None


def test_run_gcs_video_processing_missing_job_refunds_once_without_download(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    job_store = MagicMock()
    job_store.get_job.return_value = None
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id="deleted-user",
            action="transcription",
        ),
        social_copy=None,
    )
    settings_loader = MagicMock()
    download = MagicMock()
    inner_worker = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "get_gcs_settings",
        settings_loader,
    )
    monkeypatch.setattr(processing_tasks, "download_object", download)
    monkeypatch.setattr(
        processing_tasks,
        "run_video_processing",
        inner_worker,
    )

    processing_tasks.run_gcs_video_processing(
        job_id="deleted-gcs-job",
        gcs_object_name="uploads/deleted-user/input.mp4",
        input_path=tmp_path / "uploads" / "deleted-gcs-job_input.mp4",
        output_path=(tmp_path / "artifacts" / "deleted-gcs-job" / "processed.mp4"),
        artifact_dir=tmp_path / "artifacts" / "deleted-gcs-job",
        settings=ProcessingSettings(),
        job_store=job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    settings_loader.assert_not_called()
    download.assert_not_called()
    inner_worker.assert_not_called()
    ledger_store.refund_if_reserved.assert_called_once()


def test_source_upload_is_erased_if_job_disappears_during_upload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    job_store = MagicMock()
    job_store.get_job.side_effect = [
        types.SimpleNamespace(status="pending"),
        None,
    ]
    upload = MagicMock()
    erase = MagicMock()
    monkeypatch.setattr(processing_tasks, "upload_object", upload)
    monkeypatch.setattr(processing_tasks, "delete_object", erase)
    source = tmp_path / "input.mp4"
    source.write_bytes(b"input")
    gcs_settings = types.SimpleNamespace(bucket="test")

    processing_tasks.upload_source_for_active_job(
        job_id="job-upload-race",
        job_store=job_store,
        gcs_settings=gcs_settings,
        object_name="uploads/user/job-upload-race.mp4",
        source=source,
        content_type="video/mp4",
    )

    upload.assert_called_once()
    erase.assert_called_once_with(
        settings=gcs_settings,
        object_name="uploads/user/job-upload-race.mp4",
    )


def test_abort_deleted_job_refunds_when_local_cleanup_fails(
    monkeypatch,
) -> None:
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id="deleted-user",
            action="transcription",
        ),
        social_copy=None,
    )
    cleanup_error = RuntimeError("workspace unavailable")
    monkeypatch.setattr(
        processing_tasks,
        "data_roots",
        MagicMock(side_effect=cleanup_error),
    )
    exception_spy = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "logger",
        types.SimpleNamespace(exception=exception_spy),
    )

    processing_tasks.abort_deleted_job(
        job_id="deleted-job",
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        error="Job was deleted",
    )

    exception_spy.assert_called_once()
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status="cancelled",
        error="Job was deleted",
    )


@pytest.mark.parametrize(
    "current_job",
    [
        None,
        types.SimpleNamespace(status="cancelled"),
    ],
)
def test_source_upload_is_skipped_for_inactive_job(
    monkeypatch,
    tmp_path: Path,
    current_job: object,
) -> None:
    job_store = MagicMock()
    job_store.get_job.return_value = current_job
    upload = MagicMock()
    erase = MagicMock()
    monkeypatch.setattr(processing_tasks, "upload_object", upload)
    monkeypatch.setattr(processing_tasks, "delete_object", erase)

    processing_tasks.upload_source_for_active_job(
        job_id="inactive-job",
        job_store=job_store,
        gcs_settings=types.SimpleNamespace(bucket="test"),
        object_name="uploads/user/inactive-job.mp4",
        source=tmp_path / "input.mp4",
        content_type="video/mp4",
    )

    upload.assert_not_called()
    erase.assert_not_called()


def test_source_upload_failure_is_nonfatal_and_never_erases_unknown_object(
    monkeypatch,
    tmp_path: Path,
) -> None:
    job_store = MagicMock()
    job_store.get_job.return_value = types.SimpleNamespace(status="pending")
    upload = MagicMock(side_effect=RuntimeError("provider unavailable"))
    erase = MagicMock()
    warning_spy = MagicMock()
    monkeypatch.setattr(processing_tasks, "upload_object", upload)
    monkeypatch.setattr(processing_tasks, "delete_object", erase)
    monkeypatch.setattr(
        processing_tasks,
        "logger",
        types.SimpleNamespace(warning=warning_spy),
    )

    processing_tasks.upload_source_for_active_job(
        job_id="upload-failure",
        job_store=job_store,
        gcs_settings=types.SimpleNamespace(bucket="test"),
        object_name="uploads/user/upload-failure.mp4",
        source=tmp_path / "input.mp4",
        content_type="video/mp4",
    )

    upload.assert_called_once()
    warning_spy.assert_called_once()
    erase.assert_not_called()
    job_store.get_job.assert_called_once_with("upload-failure")


def test_source_upload_is_retained_only_while_job_stays_active(
    monkeypatch,
    tmp_path: Path,
) -> None:
    job_store = MagicMock()
    job_store.get_job.side_effect = [
        types.SimpleNamespace(status="pending"),
        types.SimpleNamespace(status="processing"),
    ]
    upload = MagicMock()
    erase = MagicMock()
    monkeypatch.setattr(processing_tasks, "upload_object", upload)
    monkeypatch.setattr(processing_tasks, "delete_object", erase)

    processing_tasks.upload_source_for_active_job(
        job_id="active-job",
        job_store=job_store,
        gcs_settings=types.SimpleNamespace(bucket="test"),
        object_name="uploads/user/active-job.mp4",
        source=tmp_path / "input.mp4",
        content_type="video/mp4",
    )

    upload.assert_called_once()
    erase.assert_not_called()


def test_source_upload_cleanup_failure_is_reported_without_masking_worker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    job_store = MagicMock()
    job_store.get_job.side_effect = [
        types.SimpleNamespace(status="processing"),
        types.SimpleNamespace(status="cancelled"),
    ]
    erase = MagicMock(side_effect=RuntimeError("delete unavailable"))
    exception_spy = MagicMock()
    monkeypatch.setattr(processing_tasks, "upload_object", MagicMock())
    monkeypatch.setattr(processing_tasks, "delete_object", erase)
    monkeypatch.setattr(
        processing_tasks,
        "logger",
        types.SimpleNamespace(exception=exception_spy),
    )

    processing_tasks.upload_source_for_active_job(
        job_id="cancelled-during-upload",
        job_store=job_store,
        gcs_settings=types.SimpleNamespace(bucket="test"),
        object_name="uploads/user/cancelled-during-upload.mp4",
        source=tmp_path / "input.mp4",
        content_type="video/mp4",
    )

    erase.assert_called_once()
    exception_spy.assert_called_once()


def test_run_video_processing_uploads_exact_artifacts_and_persists_source_reference(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user_id = (
        backend_auth.UserStore(db)
        .register_local_user(
            f"gcs-artifacts-{uuid.uuid4().hex}@example.com",
            "testpassword123",
            "GCS Artifacts",
        )
        .id
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(
        f"job-gcs-artifacts-{uuid.uuid4().hex}",
        user_id,
    )
    input_path = tmp_path / "uploads" / f"{job.id}_input.mp4"
    artifact_dir = tmp_path / "artifacts" / job.id
    output_path = artifact_dir / "processed.mp4"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(b"input")

    def process(*_args, **_kwargs):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"video")
        (artifact_dir / "transcription.json").write_text(
            "[]",
            encoding="utf-8",
        )
        return output_path

    gcs_settings = types.SimpleNamespace(static_prefix="static")
    upload = MagicMock()
    monkeypatch.setattr(processing_tasks, "process_video_pipeline", process)
    monkeypatch.setattr(
        processing_tasks,
        "get_gcs_settings",
        lambda: gcs_settings,
    )
    monkeypatch.setattr(processing_tasks, "upload_object", upload)

    source_object = f"uploads/{user_id}/{job.id}.mp4"
    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        source_gcs_object_name=source_object,
    )

    assert [call.kwargs["object_name"] for call in upload.call_args_list] == [
        f"static/artifacts/{job.id}/processed.mp4",
        f"static/artifacts/{job.id}/transcription.json",
    ]
    completed = job_store.get_job(job.id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.result_data is not None
    assert completed.result_data["source_gcs_object"] == source_object


@pytest.mark.parametrize(
    ("pipeline_error", "expected_status"),
    [
        (InterruptedError("cancelled after erasure"), "cancelled"),
        (RuntimeError("failed after erasure"), "cancelled"),
    ],
)
def test_run_video_processing_refunds_when_job_disappears_on_worker_error(
    monkeypatch,
    tmp_path: Path,
    pipeline_error: Exception,
    expected_status: str,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    current = types.SimpleNamespace(status="processing")
    job_store = MagicMock()
    job_store.get_job.side_effect = [current, None]
    job_store.update_job.return_value = None
    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        MagicMock(side_effect=pipeline_error),
    )
    cleanup = MagicMock()
    monkeypatch.setattr(processing_tasks, "delete_job_workspace", cleanup)
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id="deleted-user",
            action="transcription",
        ),
        social_copy=None,
    )

    processing_tasks.run_video_processing(
        "deleted-on-error",
        tmp_path / "uploads" / "input.mp4",
        tmp_path / "artifacts" / "deleted-on-error" / "processed.mp4",
        tmp_path / "artifacts" / "deleted-on-error",
        ProcessingSettings(),
        job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    cleanup.assert_called_once()
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status=expected_status,
        error=str(pipeline_error),
    )
    failed_updates = [
        call for call in job_store.update_job.call_args_list if call.kwargs.get("status") in {"failed", "cancelled"}
    ]
    assert failed_updates == []


def test_run_gcs_video_processing_fails_closed_when_job_disappears_during_download(
    monkeypatch,
    tmp_path: Path,
) -> None:
    job_store = MagicMock()
    job_store.get_job.side_effect = [
        types.SimpleNamespace(status="pending"),
        None,
    ]
    monkeypatch.setattr(
        processing_tasks,
        "get_gcs_settings",
        lambda: types.SimpleNamespace(keep_uploads=True),
    )
    input_path = tmp_path / "uploads" / "input.mp4"
    input_path.parent.mkdir(parents=True)
    input_path.write_bytes(b"partial")
    monkeypatch.setattr(
        processing_tasks,
        "download_object",
        MagicMock(side_effect=RuntimeError("download interrupted")),
    )
    cleanup = MagicMock()
    monkeypatch.setattr(processing_tasks, "delete_job_workspace", cleanup)
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id="deleted-user",
            action="transcription",
        ),
        social_copy=None,
    )

    processing_tasks.run_gcs_video_processing(
        job_id="deleted-during-download",
        gcs_object_name="uploads/deleted-user/input.mp4",
        input_path=input_path,
        output_path=tmp_path / "artifacts" / "processed.mp4",
        artifact_dir=tmp_path / "artifacts",
        settings=ProcessingSettings(),
        job_store=job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    assert not input_path.exists()
    cleanup.assert_called_once()
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status="cancelled",
        error="download interrupted",
    )


@pytest.mark.parametrize(
    "duration",
    [None, 0, -1],
)
def test_run_gcs_video_processing_rejects_missing_or_nonpositive_duration(
    monkeypatch,
    tmp_path: Path,
    duration: float | None,
) -> None:
    job_store = MagicMock()
    job_store.get_job.return_value = types.SimpleNamespace(status="pending")
    monkeypatch.setattr(
        processing_tasks,
        "get_gcs_settings",
        lambda: types.SimpleNamespace(keep_uploads=True),
    )
    monkeypatch.setattr(processing_tasks, "download_object", MagicMock())
    monkeypatch.setattr(
        processing_tasks,
        "probe_media",
        lambda _path: types.SimpleNamespace(duration_s=duration),
    )
    inner_worker = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "run_video_processing",
        inner_worker,
    )

    processing_tasks.run_gcs_video_processing(
        job_id="invalid-duration",
        gcs_object_name="uploads/user/input.mp4",
        input_path=tmp_path / "input.mp4",
        output_path=tmp_path / "output.mp4",
        artifact_dir=tmp_path / "artifacts",
        settings=ProcessingSettings(),
        job_store=job_store,
    )

    inner_worker.assert_not_called()
    job_store.update_job.assert_any_call(
        "invalid-duration",
        status="failed",
        message="Could not determine video duration",
    )


def test_run_gcs_video_processing_deletes_exact_source_after_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    job = types.SimpleNamespace(status="pending")
    completed = types.SimpleNamespace(status="completed")
    job_store = MagicMock()
    job_store.get_job.side_effect = [job, completed]
    gcs_settings = types.SimpleNamespace(keep_uploads=False)
    monkeypatch.setattr(
        processing_tasks,
        "get_gcs_settings",
        lambda: gcs_settings,
    )
    monkeypatch.setattr(processing_tasks, "download_object", MagicMock())
    probe = types.SimpleNamespace(duration_s=2.0)
    monkeypatch.setattr(processing_tasks, "probe_media", lambda _path: probe)
    inner_worker = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "run_video_processing",
        inner_worker,
    )
    erase = MagicMock()
    monkeypatch.setattr(processing_tasks, "delete_object", erase)
    object_name = "uploads/user/exact-source.mp4"

    processing_tasks.run_gcs_video_processing(
        job_id="gcs-success",
        gcs_object_name=object_name,
        input_path=tmp_path / "input.mp4",
        output_path=tmp_path / "output.mp4",
        artifact_dir=tmp_path / "artifacts",
        settings=ProcessingSettings(),
        job_store=job_store,
    )

    inner_worker.assert_called_once()
    assert inner_worker.call_args.kwargs["source_probe"] is probe
    erase.assert_called_once_with(
        settings=gcs_settings,
        object_name=object_name,
    )


def test_run_video_processing_observes_cancellation_during_pipeline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing")
    cancelled = types.SimpleNamespace(status="cancelled")
    job_store = MagicMock()
    job_store.get_job.side_effect = [active, cancelled, cancelled]

    def cancel_during_pipeline(*_args, **kwargs):
        kwargs["check_cancelled"](force=True)
        raise AssertionError("cancellation check must interrupt the pipeline")

    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        cancel_during_pipeline,
    )
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id="cancelled-user",
            action="transcription",
        ),
        social_copy=None,
    )

    processing_tasks.run_video_processing(
        "cancelled-during-pipeline",
        tmp_path / "input.mp4",
        tmp_path / "artifacts" / "processed.mp4",
        tmp_path / "artifacts",
        ProcessingSettings(),
        job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    job_store.update_job.assert_any_call(
        "cancelled-during-pipeline",
        status="cancelled",
        message="Cancelled by user",
    )
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status="cancelled",
        error="Job cancelled by user",
    )


def test_duplicate_paid_dispatch_does_not_fail_or_refund_winner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing")
    job_store = MagicMock()
    job_store.get_job.return_value = active
    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        MagicMock(
            side_effect=(
                processing_tasks.ProviderDispatchAlreadyClaimedError(
                    "already claimed",
                )
            )
        ),
    )
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id="duplicate-user",
            action="transcription",
        ),
        social_copy=None,
    )

    processing_tasks.run_video_processing(
        "duplicate-dispatch",
        tmp_path / "input.mp4",
        tmp_path / "artifacts" / "processed.mp4",
        tmp_path / "artifacts",
        ProcessingSettings(),
        job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    assert not any(
        call.kwargs.get("status") == "failed"
        for call in job_store.update_job.call_args_list
    )
    ledger_store.refund_if_reserved.assert_not_called()


def test_run_video_processing_refunds_if_job_disappears_after_completion_update(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing")
    job_store = MagicMock()
    job_store.get_job.side_effect = [active, active, None]
    output_path = tmp_path / "artifacts" / "job" / "processed.mp4"

    def process(*_args, **_kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"result")
        return output_path

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", process)
    cleanup = MagicMock()
    monkeypatch.setattr(processing_tasks, "delete_job_workspace", cleanup)
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id="deleted-user",
            action="transcription",
        ),
        social_copy=None,
    )

    processing_tasks.run_video_processing(
        "deleted-after-completion",
        tmp_path / "uploads" / "input.mp4",
        output_path,
        output_path.parent,
        ProcessingSettings(),
        job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    completion_updates = [
        call for call in job_store.update_job.call_args_list if call.kwargs.get("status") == "completed"
    ]
    assert len(completion_updates) == 1
    cleanup.assert_called_once()
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status="cancelled",
        error="Job was deleted",
    )


def test_run_gcs_video_processing_sanitizes_probe_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    job_store = MagicMock()
    job_store.get_job.return_value = types.SimpleNamespace(status="pending")
    monkeypatch.setattr(
        processing_tasks,
        "get_gcs_settings",
        lambda: types.SimpleNamespace(keep_uploads=True),
    )
    input_path = tmp_path / "input.mp4"
    input_path.write_bytes(b"invalid")
    monkeypatch.setattr(processing_tasks, "download_object", MagicMock())
    monkeypatch.setattr(
        processing_tasks,
        "probe_media",
        MagicMock(side_effect=RuntimeError("ffprobe internals")),
    )

    processing_tasks.run_gcs_video_processing(
        job_id="invalid-media",
        gcs_object_name="uploads/user/input.mp4",
        input_path=input_path,
        output_path=tmp_path / "output.mp4",
        artifact_dir=tmp_path / "artifacts",
        settings=ProcessingSettings(),
        job_store=job_store,
    )

    assert not input_path.exists()
    job_store.update_job.assert_any_call(
        "invalid-media",
        status="failed",
        message="Could not validate uploaded media file",
    )


def test_run_gcs_video_processing_keeps_success_when_source_cleanup_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pending = types.SimpleNamespace(status="pending")
    completed = types.SimpleNamespace(status="completed")
    job_store = MagicMock()
    job_store.get_job.side_effect = [pending, completed]
    gcs_settings = types.SimpleNamespace(keep_uploads=False)
    monkeypatch.setattr(
        processing_tasks,
        "get_gcs_settings",
        lambda: gcs_settings,
    )
    monkeypatch.setattr(processing_tasks, "download_object", MagicMock())
    monkeypatch.setattr(
        processing_tasks,
        "probe_media",
        lambda _path: types.SimpleNamespace(duration_s=2.0),
    )
    inner_worker = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "run_video_processing",
        inner_worker,
    )
    monkeypatch.setattr(
        processing_tasks,
        "delete_object",
        MagicMock(side_effect=RuntimeError("cleanup unavailable")),
    )
    warning_spy = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "logger",
        types.SimpleNamespace(warning=warning_spy),
    )

    processing_tasks.run_gcs_video_processing(
        job_id="gcs-cleanup-warning",
        gcs_object_name="uploads/user/input.mp4",
        input_path=tmp_path / "input.mp4",
        output_path=tmp_path / "output.mp4",
        artifact_dir=tmp_path / "artifacts",
        settings=ProcessingSettings(),
        job_store=job_store,
    )

    inner_worker.assert_called_once()
    warning_spy.assert_called_once()
    failed_updates = [call for call in job_store.update_job.call_args_list if call.kwargs.get("status") == "failed"]
    assert failed_updates == []
