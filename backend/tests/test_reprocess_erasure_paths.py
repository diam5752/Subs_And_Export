from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError

from backend.app.api.endpoints import reprocess_routes
from backend.app.api.endpoints.reprocess_routes import ReprocessRequest
from backend.app.core.auth import User, UserStore
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournal
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.core.workspace_ownership import get_workspace_owner
from backend.app.services.history import HistoryStore
from backend.app.services.jobs import Job, JobStore
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import ChargePlan, UsageLedgerStore


@pytest.mark.parametrize(
    "payload",
    (
        {},
        {"authorized_credits": True},
        {"authorized_credits": "25"},
        {"authorized_credits": 24},
    ),
)
def test_reprocess_requires_a_strict_canonical_authorized_credit_tier(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        ReprocessRequest.model_validate(payload)


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
        reprocess_routes,
        "preflight_processing_charges",
        MagicMock(),
    )
    monkeypatch.setattr(
        "backend.app.api.endpoints.reprocess_routes.uuid.uuid4",
        lambda: new_job_uuid,
    )

    if failure_stage == "copy":

        def fail_copy(_source: Path, destination: Path) -> None:
            assert get_workspace_owner(data_dir=data_dir, job_id=new_job_id) == user_id
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
                {
                    "authorized_credits": 100,
                    "transcribe_provider": "mock",
                    "use_llm": False,
                },
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
    assert get_workspace_owner(data_dir=data_dir, job_id=new_job_id) is None


def test_repeated_zero_credit_reprocesses_leave_no_new_jobs_files_or_tombstones(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database()
    user = UserStore(db=db).register_local_user(
        f"zero-reprocess-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Zero Reprocess",
    )
    points_store = PointsStore(db=db)
    points_store.ensure_account(user.id)
    assert points_store.get_balance(user.id) == 0
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reserve = MagicMock(wraps=ledger_store.reserve)
    budget_reserve = MagicMock(
        wraps=ledger_store.provider_budget_store.reserve_in_session,
    )
    monkeypatch.setattr(ledger_store, "reserve", reserve)
    monkeypatch.setattr(
        ledger_store.provider_budget_store,
        "reserve_in_session",
        budget_reserve,
    )

    source_job_id = f"source-{uuid.uuid4().hex}"
    job_store = JobStore(db=db)
    job_store.create_job(source_job_id, user.id)
    job_store.update_job(
        source_job_id,
        status="completed",
        progress=100,
        message="done",
        result_data={"original_filename": "source.mp4"},
    )

    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_root.mkdir(parents=True)
    source_input = uploads_dir / f"{source_job_id}_input.mp4"
    source_input.write_bytes(b"source-private-video")
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.initialize()

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
    uuid4 = MagicMock(side_effect=AssertionError("preflight must precede UUID allocation"))
    copy_file = MagicMock(side_effect=AssertionError("preflight must precede copy"))
    monkeypatch.setattr(reprocess_routes.uuid, "uuid4", uuid4)
    monkeypatch.setattr(reprocess_routes, "link_or_copy_file", copy_file)

    request = ReprocessRequest.model_validate(
        {
            "authorized_credits": 100,
            "transcribe_provider": "local",
            "use_llm": False,
        },
    )
    for _ in range(25):
        with pytest.raises(HTTPException) as exc_info:
            reprocess_routes.reprocess_job(
                source_job_id,
                request,
                BackgroundTasks(),
                current_user=user,
                job_store=job_store,
                history_store=HistoryStore(db=db),
                ledger_store=ledger_store,
                db=db,
            )

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail == "Insufficient points"

    assert journal.read_all() == []
    assert [job.id for job in job_store.list_jobs_for_user(user.id)] == [
        source_job_id,
    ]
    assert list(uploads_dir.iterdir()) == [source_input]
    assert list(artifacts_root.iterdir()) == []
    uuid4.assert_not_called()
    copy_file.assert_not_called()
    reserve.assert_not_called()
    budget_reserve.assert_not_called()


def test_reprocess_rejects_nan_probe_before_copy_or_financial_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user = User(
        id="nan-reprocess-user",
        email="nan-reprocess@example.com",
        name="NaN Reprocess",
        provider="local",
    )
    source_job_id = "nan-source-job"
    source_job = Job(
        id=source_job_id,
        user_id=user.id,
        status="completed",
        progress=100,
        message="done",
        created_at=1,
        updated_at=1,
        result_data={"original_filename": "source.mp4"},
    )
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_root.mkdir(parents=True)
    source_input = uploads_dir / f"{source_job_id}_input.mp4"
    source_input.write_bytes(b"private source")

    job_store = MagicMock()
    job_store.get_job.return_value = source_job
    job_store.count_active_jobs_for_user.return_value = 0
    ledger_store = MagicMock()
    charge_preflight = MagicMock(
        side_effect=AssertionError("invalid duration must precede wallet preflight"),
    )
    uuid_namespace = MagicMock()
    uuid_namespace.uuid4.side_effect = AssertionError(
        "invalid duration must precede job id allocation",
    )
    copy_file = MagicMock(
        side_effect=AssertionError("invalid duration must precede source copying"),
    )
    reserve_plan = MagicMock(
        side_effect=AssertionError("invalid duration must precede reservation"),
    )
    provider_dispatch = MagicMock(
        side_effect=AssertionError("invalid duration must precede provider dispatch"),
    )
    background_tasks = MagicMock(spec=BackgroundTasks)
    monkeypatch.setattr(
        reprocess_routes,
        "data_roots",
        lambda: (data_dir, uploads_dir, artifacts_root),
    )
    monkeypatch.setattr(reprocess_routes, "require_storage_capacity", MagicMock())
    monkeypatch.setattr(
        reprocess_routes,
        "probe_media",
        lambda _path: MagicMock(duration_s=float("nan")),
    )
    monkeypatch.setattr(reprocess_routes, "preflight_processing_charges", charge_preflight)
    monkeypatch.setattr(reprocess_routes, "uuid", uuid_namespace)
    monkeypatch.setattr(reprocess_routes, "link_or_copy_file", copy_file)
    monkeypatch.setattr(reprocess_routes, "reserve_processing_charges", reserve_plan)
    monkeypatch.setattr(reprocess_routes, "run_video_processing", provider_dispatch)

    with pytest.raises(HTTPException) as exc_info:
        reprocess_routes.reprocess_job(
            source_job_id,
            ReprocessRequest.model_validate(
                {
                    "authorized_credits": 25,
                    "transcribe_provider": "local",
                    "use_llm": False,
                },
            ),
            background_tasks,
            current_user=user,
            job_store=job_store,
            history_store=MagicMock(),
            ledger_store=ledger_store,
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Could not determine video duration"
    charge_preflight.assert_not_called()
    uuid_namespace.uuid4.assert_not_called()
    copy_file.assert_not_called()
    job_store.create_job.assert_not_called()
    reserve_plan.assert_not_called()
    ledger_store.reserve.assert_not_called()
    provider_dispatch.assert_not_called()
    background_tasks.add_task.assert_not_called()
    assert source_input.read_bytes() == b"private source"
    assert list(uploads_dir.iterdir()) == [source_input]
    assert list(artifacts_root.iterdir()) == []


def test_reprocess_budget_preflight_rejects_before_uuid_or_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    user = User(
        id="budget-reprocess-user",
        email="budget-reprocess@example.com",
        name="Budget",
        provider="local",
    )
    source_job_id = "budget-source-job"
    source_job = Job(
        id=source_job_id,
        user_id=user.id,
        status="completed",
        progress=100,
        message="done",
        created_at=1,
        updated_at=1,
        result_data={"original_filename": "source.mp4"},
    )
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_root.mkdir(parents=True)
    (uploads_dir / f"{source_job_id}_input.mp4").write_bytes(b"private source")

    job_store = MagicMock()
    job_store.get_job.return_value = source_job
    job_store.count_active_jobs_for_user.return_value = 0
    preflight = MagicMock(
        side_effect=ProviderBudgetExceededError("Daily external provider budget exceeded"),
    )
    uuid4 = MagicMock(side_effect=AssertionError("preflight must precede UUID allocation"))
    copy_file = MagicMock(side_effect=AssertionError("preflight must precede copy"))
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
    monkeypatch.setattr(reprocess_routes, "preflight_processing_charges", preflight)
    monkeypatch.setattr(reprocess_routes.uuid, "uuid4", uuid4)
    monkeypatch.setattr(reprocess_routes, "link_or_copy_file", copy_file)

    with pytest.raises(ProviderBudgetExceededError, match="Daily"):
        reprocess_routes.reprocess_job(
            source_job_id,
            ReprocessRequest.model_validate(
                {
                    "authorized_credits": 100,
                    "transcribe_tier": "pro",
                    "transcribe_provider": "elevenlabs",
                    "use_llm": False,
                },
            ),
            BackgroundTasks(),
            current_user=user,
            job_store=job_store,
            history_store=MagicMock(),
            ledger_store=MagicMock(),
            db=MagicMock(),
        )

    preflight.assert_called_once()
    uuid4.assert_not_called()
    copy_file.assert_not_called()
    job_store.create_job.assert_not_called()
