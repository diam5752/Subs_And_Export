from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks

from backend.app.api.endpoints import reprocess_routes
from backend.app.api.endpoints.reprocess_routes import ReprocessRequest
from backend.app.core.auth import User
from backend.app.services.jobs import Job
from backend.app.services.usage_ledger import ChargePlan


@pytest.mark.parametrize(
    "failure_stage",
    ("copy", "create_job", "reserve", "enqueue"),
)
def test_reprocess_copy_failures_are_journaled_before_exact_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
) -> None:
    # REGRESSION: once a reprocess copy starts, no exception may leave private
    # media or a partially committed job outside the durable erasure workflow.
    source_job_id = "source-job"
    user_id = "reprocess-user"
    new_job_uuid = uuid.UUID("11111111-1111-4111-8111-111111111111")
    new_job_id = str(new_job_uuid)
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_root.mkdir(parents=True)
    source_input = uploads_dir / f"{source_job_id}_input.mp4"
    source_input.write_bytes(b"source-private-video")
    copied_input = uploads_dir / f"{new_job_id}_input.mp4"
    partial_artifact = artifacts_root / new_job_id / "partial.txt"
    neighbor_input = uploads_dir / "neighbor-job_input.mp4"
    neighbor_artifact = artifacts_root / "neighbor-job" / "keep.txt"
    neighbor_input.write_bytes(b"neighbor-input")
    neighbor_artifact.parent.mkdir(parents=True)
    neighbor_artifact.write_text("neighbor-artifact", encoding="utf-8")

    def create_partial_artifact() -> None:
        partial_artifact.parent.mkdir(parents=True, exist_ok=True)
        partial_artifact.write_text("partial-private-output", encoding="utf-8")

    journal = MagicMock()

    def assert_journal_precedes_cleanup(**_kwargs: object) -> None:
        assert copied_input.is_file()
        assert partial_artifact.is_file()

    journal.append.side_effect = assert_journal_precedes_cleanup
    monkeypatch.setattr(
        reprocess_routes,
        "configured_erasure_journal",
        lambda: journal,
    )
    monkeypatch.setattr(
        reprocess_routes,
        "data_roots",
        lambda: (data_dir, uploads_dir, artifacts_root),
    )
    monkeypatch.setattr(reprocess_routes, "require_storage_capacity", MagicMock())
    monkeypatch.setattr(
        reprocess_routes,
        "probe_media",
        lambda _path: MagicMock(duration_s=30.0),
    )
    monkeypatch.setattr(
        "backend.app.api.endpoints.reprocess_routes.uuid.uuid4",
        lambda: new_job_uuid,
    )

    if failure_stage == "copy":

        def fail_copy(_source: Path, destination: Path) -> None:
            destination.write_bytes(b"partial-copy")
            create_partial_artifact()
            raise OSError("copy failed")

        monkeypatch.setattr(reprocess_routes, "link_or_copy_file", fail_copy)

    source_job = Job(
        id=source_job_id,
        user_id=user_id,
        status="completed",
        progress=100,
        message="done",
        created_at=1,
        updated_at=1,
        result_data={"original_filename": "source.mp4"},
    )
    created_job = Job(
        id=new_job_id,
        user_id=user_id,
        status="pending",
        progress=0,
        message=None,
        created_at=2,
        updated_at=2,
        result_data=None,
    )
    job_store = MagicMock()
    job_store.get_job.return_value = source_job
    job_store.count_active_jobs_for_user.return_value = 0
    job_store.create_job.return_value = created_job

    if failure_stage == "create_job":

        def fail_create_job(_job_id: str, _user_id: str) -> Job:
            create_partial_artifact()
            raise RuntimeError("create failed after a possible commit")

        job_store.create_job.side_effect = fail_create_job

    charge_plan = ChargePlan(transcription=None, social_copy=None)
    if failure_stage == "reserve":

        def fail_reservation(**_kwargs: object) -> tuple[ChargePlan, int]:
            create_partial_artifact()
            raise RuntimeError("reservation failed")

        monkeypatch.setattr(
            reprocess_routes,
            "reserve_processing_charges",
            fail_reservation,
        )
    else:
        monkeypatch.setattr(
            reprocess_routes,
            "reserve_processing_charges",
            lambda **_kwargs: (charge_plan, 100),
        )

    background_tasks = MagicMock(spec=BackgroundTasks)
    if failure_stage == "enqueue":

        def fail_enqueue(*_args: object, **_kwargs: object) -> None:
            create_partial_artifact()
            raise RuntimeError("enqueue failed")

        background_tasks.add_task.side_effect = fail_enqueue

    history_store = MagicMock()
    current_user = User(
        id=user_id,
        email="reprocess@example.com",
        name="Reprocess User",
        provider="local",
    )

    with pytest.raises((OSError, RuntimeError)):
        reprocess_routes.reprocess_job(
            source_job_id,
            ReprocessRequest.model_validate(
                {"transcribe_provider": "mock", "use_llm": False},
            ),
            background_tasks,
            current_user=current_user,
            job_store=job_store,
            history_store=history_store,
            ledger_store=MagicMock(),
            db=MagicMock(),
        )

    expected_kind = "workspace" if failure_stage == "copy" else "job"
    journal.append.assert_called_once_with(
        kind=expected_kind,
        user_id=user_id,
        job_ids=[new_job_id],
    )
    if expected_kind == "job":
        history_store.delete_job_events.assert_called_once_with([new_job_id])
        job_store.delete_job.assert_called_once_with(new_job_id)
    else:
        history_store.delete_job_events.assert_not_called()
        job_store.delete_job.assert_not_called()

    assert source_input.read_bytes() == b"source-private-video"
    assert not copied_input.exists()
    assert not partial_artifact.parent.exists()
    assert neighbor_input.read_bytes() == b"neighbor-input"
    assert neighbor_artifact.read_text(encoding="utf-8") == "neighbor-artifact"
