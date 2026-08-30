from __future__ import annotations

import threading
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.api.endpoints import processing_tasks
from backend.app.api.endpoints.settings import ProcessingSettings
from backend.app.core import auth as backend_auth
from backend.app.core import config
from backend.app.core.database import Database
from backend.app.core.workspace_deletion import (
    JobWorkspaceLockTimeoutError,
    lock_job_workspace,
)
from backend.app.core.workspace_ownership import (
    get_workspace_owner,
    record_workspace_ownership,
)
from backend.app.services import jobs
from backend.app.services.usage_ledger import ChargePlan


def test_cleanup_journal_failure_observes_concurrent_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A stale processing snapshot must not fail/refund over a winning cancel."""
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user = backend_auth.UserStore(db=db).register_local_user(
        f"cleanup-race-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Cleanup Race",
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(f"cleanup-race-{uuid.uuid4().hex}", user.id)
    input_path = tmp_path / "uploads" / f"{job.id}_input.mp4"
    artifact_dir = tmp_path / "artifacts" / job.id
    output_path = artifact_dir / "processed.mp4"
    input_path.parent.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    input_path.write_bytes(b"private input")
    output_path.write_bytes(b"private output")

    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        MagicMock(side_effect=RuntimeError("provider failed")),
    )
    journal = MagicMock()

    def cancel_then_fail(**_payload: object) -> None:
        assert job_store.update_job_if_status(
            job.id,
            expected_statuses={"processing"},
            status="cancelling",
            message="Cancellation requested",
        )
        raise RuntimeError("journal unavailable")

    journal.append_job_terminal.side_effect = cancel_then_fail
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id=user.id,
            action="transcription",
        ),
    )

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    latest = job_store.get_job(job.id)
    assert latest is not None and latest.status == "cancelling"
    journal.append_job_terminal.assert_called_once_with(
        user_id=user.id,
        job_ids=[job.id],
        terminal_status="failed",
    )
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status="cancelled",
        error="provider failed",
    )
    assert input_path.is_file()
    assert output_path.is_file()


def test_failure_records_cancelled_precedence_when_cancel_wins_after_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A raced cancellation gets its own durable tombstone before terminal state."""
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user = backend_auth.UserStore(db=db).register_local_user(
        f"terminal-race-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Terminal Race",
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(f"terminal-race-{uuid.uuid4().hex}", user.id)
    input_path = tmp_path / "uploads" / f"{job.id}_input.mp4"
    artifact_dir = tmp_path / "artifacts" / job.id
    output_path = artifact_dir / "processed.mp4"
    input_path.parent.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    input_path.write_bytes(b"private input")
    output_path.write_bytes(b"private output")

    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        MagicMock(side_effect=RuntimeError("provider failed")),
    )
    journal = MagicMock()
    recorded_statuses: list[str] = []

    def record_and_race(*, terminal_status: str, **_payload: object) -> None:
        recorded_statuses.append(terminal_status)
        if terminal_status == "failed":
            assert job_store.update_job_if_status(
                job.id,
                expected_statuses={"processing"},
                status="cancelling",
                message="Cancellation requested",
            )

    journal.append_job_terminal.side_effect = record_and_race
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )
    ledger_store = MagicMock()
    charge_plan = ChargePlan(
        transcription=types.SimpleNamespace(
            user_id=user.id,
            action="transcription",
        ),
    )

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    latest = job_store.get_job(job.id)
    assert latest is not None and latest.status == "cancelled"
    assert recorded_statuses == ["failed", "cancelled"]
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status="cancelled",
        error="provider failed",
    )
    assert not input_path.exists()
    assert not artifact_dir.exists()


def test_duplicate_paid_dispatch_does_not_fail_or_refund_winner(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing")
    job_store = MagicMock()
    job_store.get_job.return_value = active
    job_store.update_job_if_status.return_value = True
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

    assert not any(call.kwargs.get("status") == "failed" for call in job_store.update_job_if_status.call_args_list)
    ledger_store.refund_if_reserved.assert_not_called()


def test_run_video_processing_refunds_if_job_disappears_after_completion_update(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    active = types.SimpleNamespace(status="processing")
    job_store = MagicMock()
    job_store.get_job.side_effect = [active, None]
    job_store.update_job_if_status.return_value = True
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
        call for call in job_store.update_job_if_status.call_args_list if call.kwargs.get("status") == "completed"
    ]
    assert len(completion_updates) == 1
    cleanup.assert_called_once()
    ledger_store.refund_if_reserved.assert_called_once_with(
        charge_plan.transcription,
        status="cancelled",
        error="Job was deleted",
    )


def test_cancelling_worker_holds_lifetime_lock_until_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user = backend_auth.UserStore(db=db).register_local_user(
        f"cancel-barrier-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Cancel Barrier",
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(f"cancel-barrier-{uuid.uuid4().hex}", user.id)
    uploads_dir = tmp_path / "uploads"
    artifact_dir = tmp_path / "artifacts" / job.id
    input_path = uploads_dir / f"{job.id}_input.mp4"
    output_path = artifact_dir / "processed.mp4"
    uploads_dir.mkdir(parents=True)
    input_path.write_bytes(b"private input")
    started = threading.Event()
    release = threading.Event()
    journal = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )

    def paused_pipeline(*_args, **kwargs):
        started.set()
        assert release.wait(3)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"late private output")
        kwargs["check_cancelled"](force=True)
        raise AssertionError("cancellation must interrupt the pipeline")

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", paused_pipeline)
    worker = threading.Thread(
        target=processing_tasks.run_video_processing,
        args=(
            job.id,
            input_path,
            output_path,
            artifact_dir,
            ProcessingSettings(),
            job_store,
        ),
        kwargs={"source_probe": types.SimpleNamespace(duration_s=1.0)},
    )
    worker.start()
    assert started.wait(3)
    assert job_store.update_job_if_status(
        job.id,
        expected_statuses={"processing"},
        status="cancelling",
        message="Cancellation requested",
    )
    assert job_store.get_job(job.id).status == "cancelling"

    with pytest.raises(JobWorkspaceLockTimeoutError):
        with lock_job_workspace(
            data_dir=tmp_path,
            job_id=job.id,
            timeout_seconds=0.1,
        ):
            raise AssertionError("eraser must not enter while worker can write")

    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    cancelled = job_store.get_job(job.id)
    assert cancelled is not None and cancelled.status == "cancelled"
    assert not input_path.exists()
    assert not artifact_dir.exists()
    journal.append_job_terminal.assert_called_once_with(
        user_id=user.id,
        job_ids=[job.id],
        terminal_status="cancelled",
    )


def test_cancellation_journal_failure_stays_nonterminal_for_recovery(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user = backend_auth.UserStore(db=db).register_local_user(
        f"cancel-journal-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Cancel Journal",
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(f"cancel-journal-{uuid.uuid4().hex}", user.id)
    job_store.update_job(
        job.id,
        status="cancelling",
        message="Cancellation requested",
    )
    input_path = tmp_path / "uploads" / f"{job.id}_input.mp4"
    artifact_dir = tmp_path / "artifacts" / job.id
    output_path = artifact_dir / "processed.mp4"
    input_path.parent.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    input_path.write_bytes(b"private input")
    output_path.write_bytes(b"private output")
    journal = MagicMock()
    journal.append_job_terminal.side_effect = RuntimeError("journal unavailable")
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        ProcessingSettings(),
        job_store,
        source_probe=types.SimpleNamespace(duration_s=1.0),
    )

    stranded = job_store.get_job(job.id)
    assert stranded is not None and stranded.status == "cancelling"
    assert input_path.is_file()
    assert output_path.is_file()


def test_startup_reconciles_stranded_cancellation_before_health(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(config.settings, "data_dir", tmp_path)
    db = Database()
    user = backend_auth.UserStore(db=db).register_local_user(
        f"cancel-recovery-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Cancel Recovery",
    )
    job_store = jobs.JobStore(db)
    job = job_store.create_job(f"cancel-recovery-{uuid.uuid4().hex}", user.id)
    job_store.update_job(
        job.id,
        status="cancelling",
        message="Cancellation requested",
    )
    input_path = tmp_path / "uploads" / f"{job.id}_input.mp4"
    artifact_dir = tmp_path / "artifacts" / job.id
    input_path.parent.mkdir(parents=True)
    artifact_dir.mkdir(parents=True)
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=job.id,
        user_id=user.id,
    )
    input_path.write_bytes(b"private input")
    (artifact_dir / "transcription.json").write_text("[]", encoding="utf-8")
    journal = MagicMock()
    monkeypatch.setattr(
        processing_tasks,
        "configured_erasure_journal",
        lambda: journal,
    )

    # The suite intentionally exercises other crash-stranded cancellations in
    # the shared PostgreSQL test database. Startup reconciliation must recover
    # every one it finds, including this exact job.
    assert processing_tasks.reconcile_stranded_cancellations(db) >= 1

    recovered = job_store.get_job(job.id)
    assert recovered is not None and recovered.status == "cancelled"
    assert not input_path.exists()
    assert not artifact_dir.exists()
    assert get_workspace_owner(data_dir=tmp_path, job_id=job.id) is None
    journal.append_job_terminal.assert_any_call(
        user_id=user.id,
        job_ids=[job.id],
        terminal_status="cancelled",
    )
