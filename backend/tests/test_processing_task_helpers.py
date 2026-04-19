from __future__ import annotations

import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock

from backend.app.api.endpoints import processing_tasks, videos
from backend.app.core import auth as backend_auth
from backend.app.core import config
from backend.app.core.database import Database
from backend.app.services import jobs
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


def test_run_video_processing_continues_when_gcs_upload_fails(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config.settings, "project_root", tmp_path)

    db = Database()
    job_store = jobs.JobStore(db)
    user_id = backend_auth.UserStore(db=db).register_local_user(
        f"gcs_warn_{uuid.uuid4().hex}@example.com", "testpassword123", "Runner"
    ).id
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

    monkeypatch.setattr(processing_tasks, "normalize_and_stub_subtitles", fake_normalize)
    monkeypatch.setattr(processing_tasks, "get_gcs_settings", lambda: types.SimpleNamespace(static_prefix="static"))
    monkeypatch.setattr(processing_tasks, "upload_object", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("upload failed")))
    warning_spy = MagicMock()
    monkeypatch.setattr(processing_tasks, "logger", types.SimpleNamespace(debug=lambda *args, **kwargs: None, warning=warning_spy))

    processing_tasks.run_video_processing(
        job.id,
        input_path,
        output_path,
        artifact_dir,
        videos.ProcessingSettings(),
        job_store,
    )

    finished = job_store.get_job(job.id)
    assert finished and finished.status == "completed"
    warning_spy.assert_called_once()


def test_run_gcs_video_processing_fails_fast_without_configuration() -> None:
    job_store = MagicMock()
    ledger_store = MagicMock()
    charge_plan = ChargePlan(transcription=types.SimpleNamespace(user_id="u1", action="transcription"), social_copy=None)

    processing_tasks.run_gcs_video_processing(
        job_id="job-1",
        gcs_object_name="uploads/file.mp4",
        input_path=Path("input.mp4"),
        output_path=Path("output.mp4"),
        artifact_dir=Path("artifacts"),
        settings=videos.ProcessingSettings(),
        job_store=job_store,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
    )

    job_store.update_job.assert_called_once_with("job-1", status="failed", message="GCS is not configured")
    ledger_store.refund_if_reserved.assert_called_once()
