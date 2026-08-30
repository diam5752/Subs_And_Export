from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from backend.app.services.product_feedback import FeedbackNotificationWorker
from backend.app.services.social_intelligence import SocialContent, SocialCopy
from backend.cli import app


class _FakeDatabase:
    def dispose(self) -> None:
        return None


class _TrackingDatabase:
    def __init__(self, *, dispose_error: Exception | None = None) -> None:
        self.dispose_calls = 0
        self._dispose_error = dispose_error

    def dispose(self) -> None:
        self.dispose_calls += 1
        if self._dispose_error is not None:
            raise self._dispose_error


def _raise_sensitive_privacy_error() -> NoReturn:
    try:
        raise RuntimeError(
            "xi-api-key=fake-provider-key Authorization=Bearer-fake-header "
            "transcript_id=fake-provider-id "
            "url=https://provider.invalid/transcripts/fake-provider-id",
        )
    except RuntimeError as exc:
        raise RuntimeError("privacy provider operation failed") from exc


@pytest.mark.parametrize(
    ("command", "operation_name", "failure_message"),
    [
        ("run-retention", "run_configured_retention", "Retention command failed."),
        (
            "reconcile-erasures",
            "reconcile_erasure_journal",
            "Erasure reconciliation command failed.",
        ),
    ],
)
def test_privacy_commands_redact_chained_operation_errors(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    operation_name: str,
    failure_message: str,
) -> None:
    database = _TrackingDatabase()

    def fail_operation(*_args: object, **_kwargs: object) -> NoReturn:
        _raise_sensitive_privacy_error()

    monkeypatch.setattr("backend.cli.Database", lambda: database)
    monkeypatch.setattr(f"backend.cli.{operation_name}", fail_operation)
    monkeypatch.setattr("backend.cli.configured_erasure_journal", lambda: object())

    # REGRESSION: uncaught privacy-operation exceptions used Typer's rich
    # traceback renderer, which could expose provider credentials and IDs.
    result = CliRunner().invoke(app, [command])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"{failure_message}\n"
    assert database.dispose_calls == 1
    for marker in (
        "fake-provider-key",
        "Bearer-fake-header",
        "fake-provider-id",
        "provider.invalid",
        "Traceback",
    ):
        assert marker not in result.output


def test_privacy_command_redacts_database_initialization_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_database_initialization() -> NoReturn:
        _raise_sensitive_privacy_error()

    monkeypatch.setattr("backend.cli.Database", fail_database_initialization)

    result = CliRunner().invoke(app, ["run-retention"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Retention command failed.\n"
    assert "fake-provider-key" not in result.output
    assert "fake-provider-id" not in result.output
    assert "Traceback" not in result.output


def test_privacy_command_redacts_database_disposal_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    try:
        raise RuntimeError(
            "Authorization=Bearer-fake-header url=https://provider.invalid/transcripts/fake-provider-id",
        )
    except RuntimeError as exc:
        dispose_error = RuntimeError("database disposal failed")
        dispose_error.__cause__ = exc
    database = _TrackingDatabase(dispose_error=dispose_error)
    monkeypatch.setattr("backend.cli.Database", lambda: database)
    monkeypatch.setattr(
        "backend.cli.run_configured_retention",
        lambda _db: SimpleNamespace(
            deleted_job_ids=[],
            failed_job_ids=[],
            deleted_orphan_items=0,
            failed_orphan_items=0,
        ),
    )

    result = CliRunner().invoke(app, ["run-retention"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Retention command failed.\n"
    assert database.dispose_calls == 1
    assert "Bearer-fake-header" not in result.output
    assert "fake-provider-id" not in result.output
    assert "provider.invalid" not in result.output
    assert "Traceback" not in result.output


def test_typer_disables_pretty_exception_locals() -> None:
    assert app.pretty_exceptions_show_locals is False


def test_retention_command_reports_success_and_disposes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _TrackingDatabase()
    monkeypatch.setattr("backend.cli.Database", lambda: database)
    monkeypatch.setattr(
        "backend.cli.run_configured_retention",
        lambda _db: SimpleNamespace(
            deleted_job_ids=["deleted"],
            failed_job_ids=[],
            deleted_orphan_items=2,
            failed_orphan_items=0,
        ),
    )

    result = CliRunner().invoke(app, ["run-retention"])

    assert result.exit_code == 0
    assert result.stdout == ("Retention complete: deleted_jobs=1 failed_jobs=0 deleted_orphans=2 failed_orphans=0\n")
    assert result.stderr == ""
    assert database.dispose_calls == 1


def test_reconciliation_command_reports_success_and_disposes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _TrackingDatabase()
    monkeypatch.setattr("backend.cli.Database", lambda: database)
    monkeypatch.setattr("backend.cli.configured_erasure_journal", lambda: object())
    monkeypatch.setattr(
        "backend.cli.reconcile_erasure_journal",
        lambda **_kwargs: SimpleNamespace(replayed_events=3, pruned_events=2),
    )

    result = CliRunner().invoke(app, ["reconcile-erasures"])

    assert result.exit_code == 0
    assert result.stdout == ("Erasure reconciliation complete: events=3 pruned=2\n")
    assert result.stderr == ""
    assert database.dispose_calls == 1


def test_retention_command_fails_closed_when_any_job_cannot_be_erased(
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.cli.Database", _FakeDatabase)
    monkeypatch.setattr(
        "backend.cli.run_configured_retention",
        lambda _db: SimpleNamespace(
            deleted_job_ids=["deleted"],
            failed_job_ids=["privacy-failure"],
            deleted_orphan_items=0,
            failed_orphan_items=0,
        ),
    )

    result = CliRunner().invoke(app, ["run-retention"])

    assert result.exit_code == 1
    assert "failed_jobs=1" in result.stdout


def test_retention_command_fails_closed_when_an_orphan_cannot_be_erased(
    monkeypatch,
) -> None:
    monkeypatch.setattr("backend.cli.Database", _FakeDatabase)
    monkeypatch.setattr(
        "backend.cli.run_configured_retention",
        lambda _db: SimpleNamespace(
            deleted_job_ids=[],
            failed_job_ids=[],
            deleted_orphan_items=0,
            failed_orphan_items=1,
        ),
    )

    result = CliRunner().invoke(app, ["run-retention"])

    assert result.exit_code == 1
    assert "failed_orphans=1" in result.stdout


def test_feedback_worker_health_reports_ready_and_disposes_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _TrackingDatabase()
    configuration_check = Mock()
    queue = SimpleNamespace(assert_queue_available=Mock())
    monkeypatch.setattr(
        "backend.cli.settings",
        SimpleNamespace(assert_feedback_worker_configuration=configuration_check),
    )
    monkeypatch.setattr("backend.cli.Database", lambda: database)
    monkeypatch.setattr("backend.cli._configured_feedback_store", lambda _db: queue)

    result = CliRunner().invoke(app, ["check-feedback-worker"])

    assert result.exit_code == 0
    assert result.stdout == "Feedback worker ready.\n"
    assert result.stderr == ""
    configuration_check.assert_called_once_with()
    queue.assert_queue_available.assert_called_once_with()
    assert database.dispose_calls == 1


def test_feedback_worker_health_redacts_configuration_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_configuration() -> NoReturn:
        raise RuntimeError("smtp-password=must-not-leak")

    monkeypatch.setattr(
        "backend.cli.settings",
        SimpleNamespace(assert_feedback_worker_configuration=fail_configuration),
    )

    result = CliRunner().invoke(app, ["check-feedback-worker"])

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == "Feedback worker health check failed.\n"
    assert "must-not-leak" not in result.output
    assert "Traceback" not in result.output


def test_feedback_worker_wires_queue_and_disposes_after_runner_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _TrackingDatabase()
    configuration_check = Mock()
    queue = SimpleNamespace(assert_queue_available=Mock())
    notifier = Mock()
    captured: dict[str, object] = {}
    worker_settings = SimpleNamespace(
        assert_feedback_worker_configuration=configuration_check,
        feedback_retention_days=180,
        feedback_worker_batch_size=7,
        feedback_worker_poll_seconds=3,
    )

    def capture_runner(*, worker: object, poll_seconds: int) -> None:
        captured.update(worker=worker, poll_seconds=poll_seconds)

    monkeypatch.setattr("backend.cli.settings", worker_settings)
    monkeypatch.setattr("backend.cli.Database", lambda: database)
    monkeypatch.setattr("backend.cli._configured_feedback_store", lambda _db: queue)
    monkeypatch.setattr("backend.cli._configured_feedback_notifier", lambda: notifier)
    monkeypatch.setattr("backend.cli.run_feedback_worker", capture_runner)

    result = CliRunner().invoke(app, ["feedback-worker"])

    assert result.exit_code == 0
    assert result.stderr == ""
    configuration_check.assert_called_once_with()
    queue.assert_queue_available.assert_called_once_with()
    assert captured["poll_seconds"] == 3
    worker = captured["worker"]
    assert isinstance(worker, FeedbackNotificationWorker)
    assert worker.store is queue
    assert worker.notifier is notifier
    assert worker.retention_days == 180
    assert worker.batch_size == 7
    assert database.dispose_calls == 1


def test_process_command_invokes_pipeline(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"dummy video content")

    output_file = tmp_path / "output.mp4"
    sample_social = SocialCopy(
        generic=SocialContent(
            title_el="Test Title Greek",
            title_en="Test Title English",
            description_el="Test desc Greek",
            description_en="Test desc English",
            hashtags=["#test"],
        ),
    )

    def fake_process(input_video, output_video, **kwargs):
        output_video.write_bytes(b"done")
        if kwargs.get("generate_social_copy"):
            return output_video, sample_social
        return output_video

    monkeypatch.setattr("backend.cli.process_video_pipeline", fake_process)
    result = runner.invoke(
        app,
        ["process", str(input_file), "--output", str(output_file)],
    )

    assert result.exit_code == 0
    assert output_file.exists()
    assert "Processed video saved to" in result.stdout
    assert "Test Title English" in result.stdout


def test_process_command_rejects_retired_text_generation_flag(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"dummy video content")
    output_file = tmp_path / "output.mp4"

    process_pipeline = Mock()
    monkeypatch.setattr("backend.cli.process_video_pipeline", process_pipeline)
    result = runner.invoke(
        app,
        [
            "process",
            str(input_file),
            "--output",
            str(output_file),
            "--llm-social-copy",
        ],
    )

    assert result.exit_code == 2
    assert "No such option" in result.output
    process_pipeline.assert_not_called()
