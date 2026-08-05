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


def test_run_video_processing_observes_cancellation_during_pipeline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing", user_id="cancelled-user")
    cancelled = types.SimpleNamespace(status="cancelled", user_id="cancelled-user")
    job_store = MagicMock()
    job_store.get_job.side_effect = [active, cancelled, cancelled]
    job_id = "cancelled-during-pipeline"
    uploads_dir = tmp_path / "uploads"
    artifact_dir = tmp_path / "artifacts" / job_id
    input_path = uploads_dir / f"{job_id}_input.mp4"
    output_path = artifact_dir / "processed.mp4"
    transcription_path = artifact_dir / "transcription.json"
    unrelated_upload = uploads_dir / "unrelated-job_input.mp4"
    unrelated_artifact = tmp_path / "artifacts" / "unrelated-job" / "transcription.json"
    uploads_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    unrelated_artifact.parent.mkdir(parents=True)
    input_path.write_bytes(b"private input")
    output_path.write_bytes(b"partial output")
    transcription_path.write_text("[]", encoding="utf-8")
    unrelated_upload.write_bytes(b"keep")
    unrelated_artifact.write_text("[]", encoding="utf-8")
    journal = MagicMock()

    def record_before_delete(**_kwargs: object) -> None:
        assert input_path.is_file()
        assert transcription_path.is_file()

    journal.append.side_effect = record_before_delete
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )

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
        job_id,
        input_path,
        output_path,
        artifact_dir,
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
    journal.append.assert_called_once_with(
        kind="workspace",
        user_id="cancelled-user",
        job_ids=[job_id],
    )
    assert not input_path.exists()
    assert not artifact_dir.exists()
    assert unrelated_upload.exists()
    assert unrelated_artifact.exists()


def test_run_video_processing_failure_erases_only_failed_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: failed jobs retained the source video and transcription until
    # a later retention pass, leaving avoidable personal data on disk.
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing", user_id="failed-user")
    job_store = MagicMock()
    job_store.get_job.return_value = active
    job_id = "failed-local-job"
    uploads_dir = tmp_path / "uploads"
    artifact_dir = tmp_path / "artifacts" / job_id
    input_path = uploads_dir / f"{job_id}_input.mp4"
    output_path = artifact_dir / "processed.mp4"
    transcription_path = artifact_dir / "transcription.json"
    unrelated_upload = uploads_dir / "unrelated-job_input.mp4"
    unrelated_artifact = tmp_path / "artifacts" / "unrelated-job" / "transcription.json"
    uploads_dir.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    unrelated_artifact.parent.mkdir(parents=True)
    input_path.write_bytes(b"private input")
    output_path.write_bytes(b"partial output")
    transcription_path.write_text("[]", encoding="utf-8")
    unrelated_upload.write_bytes(b"keep")
    unrelated_artifact.write_text("[]", encoding="utf-8")
    journal = MagicMock()

    def record_before_delete(**_kwargs: object) -> None:
        assert input_path.is_file()
        assert transcription_path.is_file()

    journal.append.side_effect = record_before_delete
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )
    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        MagicMock(side_effect=RuntimeError("provider failed")),
    )

    processing_tasks.run_video_processing(
        job_id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    job_store.update_job.assert_any_call(
        job_id,
        status="failed",
        message="provider failed",
    )
    journal.append.assert_called_once_with(
        kind="workspace",
        user_id="failed-user",
        job_ids=[job_id],
    )
    assert not input_path.exists()
    assert not artifact_dir.exists()
    assert unrelated_upload.exists()
    assert unrelated_artifact.exists()


@pytest.mark.parametrize(
    "pipeline_error",
    (InterruptedError("cancelled"), RuntimeError("provider failed")),
)
def test_terminal_workspace_cleanup_fails_closed_when_journal_is_unavailable(
    monkeypatch,
    tmp_path: Path,
    pipeline_error: Exception,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing", user_id="private-user")
    job_store = MagicMock()
    job_store.get_job.return_value = active
    job_id = "unjournaled-terminal-job"
    input_path = tmp_path / "uploads" / f"{job_id}_input.mp4"
    artifact_dir = tmp_path / "artifacts" / job_id
    output_path = artifact_dir / "processed.mp4"
    transcript_path = artifact_dir / "transcription.json"
    input_path.parent.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    input_path.write_bytes(b"private input")
    output_path.write_bytes(b"partial output")
    transcript_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        MagicMock(side_effect=pipeline_error),
    )
    journal = MagicMock()
    journal.append.side_effect = RuntimeError("journal unavailable")
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )

    processing_tasks.run_video_processing(
        job_id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    journal.append.assert_called_once_with(
        kind="workspace",
        user_id="private-user",
        job_ids=[job_id],
    )
    job_store.update_job.assert_any_call(
        job_id,
        status="failed",
        message="Privacy cleanup could not be recorded",
    )
    assert input_path.is_file()
    assert output_path.is_file()
    assert transcript_path.is_file()


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
