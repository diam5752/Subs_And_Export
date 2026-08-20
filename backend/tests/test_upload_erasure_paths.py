from __future__ import annotations

import base64
import errno
import json
import threading
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.app.api.endpoints.settings import ProcessingSettings
from backend.app.core.auth import UserStore
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournal
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.core.workspace_deletion import (
    JobWorkspaceLockTimeoutError,
    lock_job_workspace,
)
from backend.app.core.workspace_ownership import get_workspace_owner
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import ChargePlan, UsageLedgerStore


def _saved_workspace(tmp_path: Path, job_id: str) -> tuple[Path, Path, Path]:
    uploads_dir = tmp_path / "uploads"
    artifacts_root = tmp_path / "artifacts"
    input_path = uploads_dir / f"{job_id}_input.mp4"
    partial_artifact = artifacts_root / job_id / "partial.txt"
    uploads_dir.mkdir(parents=True)
    partial_artifact.parent.mkdir(parents=True)
    input_path.write_bytes(b"private upload")
    partial_artifact.write_text("private transcript", encoding="utf-8")
    return input_path, artifacts_root, partial_artifact


def _journal_asserting_source_exists(input_path: Path, partial_artifact: Path) -> MagicMock:
    journal = MagicMock()

    def append(**_kwargs: object) -> None:
        assert input_path.is_file()
        assert partial_artifact.is_file()

    journal.append.side_effect = append
    return journal


@pytest.mark.parametrize(
    "probe_result",
    (
        RuntimeError("invalid media"),
        types.SimpleNamespace(duration_s=None),
        types.SimpleNamespace(duration_s=0),
        types.SimpleNamespace(duration_s=10**9),
    ),
)
def test_rejected_media_with_verified_cleanup_does_not_retain_tombstone(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_result: object,
) -> None:
    job_id = "rejected-media-job"
    user_id = "rejected-media-user"
    input_path, artifacts_root, partial_artifact = _saved_workspace(tmp_path, job_id)
    journal = MagicMock()
    monkeypatch.setattr(videos, "configured_erasure_journal", lambda: journal)
    if isinstance(probe_result, Exception):
        monkeypatch.setattr(videos, "probe_media", MagicMock(side_effect=probe_result))
    else:
        monkeypatch.setattr(videos, "probe_media", lambda _path: probe_result)
    job_store = MagicMock()

    with pytest.raises(HTTPException):
        videos._queue_saved_upload(
            background_tasks=MagicMock(),
            job_id=job_id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            filename="video.mp4",
            video_resolution="",
            authorized_credits=100,
            proc_settings=ProcessingSettings(),
            current_user=types.SimpleNamespace(id=user_id),
            job_store=job_store,
            history_store=MagicMock(),
            ledger_store=MagicMock(),
            db=MagicMock(),
        )

    # REGRESSION: invalid pre-job uploads used to create one retained durable
    # event per request even after their local workspace was fully removed.
    journal.append.assert_not_called()
    job_store.create_job.assert_not_called()
    assert not input_path.exists()
    assert not partial_artifact.parent.exists()


@pytest.mark.parametrize("failure_stage", ("create_job", "reserve", "enqueue"))
def test_post_save_failures_use_the_correct_durable_erasure_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
) -> None:
    job_id = f"failed-{failure_stage}"
    user_id = "failed-upload-user"
    input_path, artifacts_root, partial_artifact = _saved_workspace(tmp_path, job_id)
    journal = _journal_asserting_source_exists(input_path, partial_artifact)
    monkeypatch.setattr(videos, "configured_erasure_journal", lambda: journal)
    monkeypatch.setattr(
        videos,
        "probe_media",
        lambda _path: types.SimpleNamespace(duration_s=30.0),
    )
    monkeypatch.setattr(videos, "preflight_processing_charges", MagicMock())
    job_store = MagicMock()
    job_store.create_job.return_value = types.SimpleNamespace(id=job_id)
    if failure_stage == "create_job":
        job_store.create_job.side_effect = RuntimeError("database unavailable")

    charge_plan = ChargePlan(transcription=None, social_copy=None)
    if failure_stage == "reserve":
        monkeypatch.setattr(
            videos,
            "reserve_processing_charges",
            MagicMock(side_effect=RuntimeError("reservation failed")),
        )
    else:
        monkeypatch.setattr(
            videos,
            "reserve_processing_charges",
            lambda **_kwargs: (charge_plan, 100),
        )

    background_tasks = MagicMock(spec=BackgroundTasks)
    if failure_stage == "enqueue":
        background_tasks.add_task.side_effect = RuntimeError("queue failed")

    with pytest.raises(RuntimeError):
        videos._queue_saved_upload(
            background_tasks=background_tasks,
            job_id=job_id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            filename="video.mp4",
            video_resolution="",
            authorized_credits=100,
            proc_settings=ProcessingSettings(),
            current_user=types.SimpleNamespace(id=user_id),
            job_store=job_store,
            history_store=MagicMock(),
            ledger_store=MagicMock(),
            db=MagicMock(),
        )

    journal.append.assert_called_once_with(
        kind="job",
        user_id=user_id,
        job_ids=[job_id],
    )
    job_store.delete_job.assert_called_once_with(job_id)
    assert not input_path.exists()
    assert not partial_artifact.parent.exists()


def test_repeated_zero_credit_uploads_leave_no_jobs_files_or_tombstones(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db = Database()
    user = UserStore(db=db).register_local_user(
        f"zero-upload-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Zero Upload",
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

    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.initialize()
    monkeypatch.setattr(videos, "configured_erasure_journal", lambda: journal)
    monkeypatch.setattr(
        videos,
        "probe_media",
        lambda _path: types.SimpleNamespace(duration_s=30.0),
    )

    job_store = JobStore(db=db)
    attempted_paths: list[tuple[Path, Path]] = []
    for index in range(25):
        job_id = f"zero-credit-upload-{index}"
        input_path, artifacts_root, partial_artifact = _saved_workspace(
            tmp_path / f"attempt-{index}",
            job_id,
        )
        attempted_paths.append((input_path, partial_artifact))

        with pytest.raises(HTTPException) as exc_info:
            videos._queue_saved_upload(
                background_tasks=BackgroundTasks(),
                job_id=job_id,
                input_path=input_path,
                artifacts_root=artifacts_root,
                filename="video.mp4",
                video_resolution="",
                authorized_credits=100,
                proc_settings=ProcessingSettings(
                    transcribe_provider="local",
                    use_llm=False,
                ),
                current_user=user,
                job_store=job_store,
                history_store=MagicMock(),
                ledger_store=ledger_store,
                db=db,
            )

        assert exc_info.value.status_code == 402
        assert exc_info.value.detail == "Insufficient points"

    assert journal.read_all() == []
    assert job_store.list_jobs_for_user(user.id) == []
    assert all(not input_path.exists() for input_path, _ in attempted_paths)
    assert all(not artifact_path.exists() for _, artifact_path in attempted_paths)
    reserve.assert_not_called()
    budget_reserve.assert_not_called()


def test_rejected_upload_cleanup_fails_closed_if_tombstone_cannot_be_stored(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = "unjournaled-upload"
    input_path, artifacts_root, partial_artifact = _saved_workspace(tmp_path, job_id)
    journal = MagicMock()
    journal.append.side_effect = RuntimeError("journal unavailable")
    monkeypatch.setattr(videos, "configured_erasure_journal", lambda: journal)
    job_store = MagicMock()

    with pytest.raises(RuntimeError, match="journal unavailable"):
        videos._record_and_delete_rejected_upload(
            job_id=job_id,
            user_id="private-user",
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="job",
            job_store=job_store,
        )

    assert input_path.is_file()
    assert partial_artifact.is_file()
    job_store.delete_job.assert_not_called()


def test_incomplete_pre_job_cleanup_retains_retry_intent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = "ambiguous-pre-job-upload"
    user_id = "private-user"
    input_path, artifacts_root, partial_artifact = _saved_workspace(tmp_path, job_id)
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    monkeypatch.setattr(videos, "configured_erasure_journal", lambda: journal)
    monkeypatch.setattr(videos, "delete_job_workspace", lambda **_kwargs: None)

    # REGRESSION: skipping durable intent is safe only after exact absence has
    # been verified; a no-op or partial deletion must remain replayable.
    with pytest.raises(RuntimeError, match="could not be verified"):
        videos._record_and_delete_rejected_upload(
            job_id=job_id,
            user_id=user_id,
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )

    entries = journal.read_all()
    assert len(entries) == 1
    assert entries[0].kind == "workspace"
    assert entries[0].user_id == user_id
    assert entries[0].job_ids == [job_id]
    assert input_path.is_file()
    assert partial_artifact.is_file()


def test_many_verified_pre_job_cleanups_do_not_grow_durable_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.initialize()
    monkeypatch.setattr(videos, "configured_erasure_journal", lambda: journal)

    # REGRESSION: attacker-controlled invalid uploads previously increased
    # retained journal cardinality even when every exact cleanup succeeded.
    for index in range(50):
        job_id = f"rejected-{index}"
        input_path, artifacts_root, _partial_artifact = _saved_workspace(
            tmp_path / f"attempt-{index}",
            job_id,
        )
        videos._record_and_delete_rejected_upload(
            job_id=job_id,
            user_id="private-user",
            input_path=input_path,
            artifacts_root=artifacts_root,
            kind="workspace",
        )

    assert journal.read_all() == []


def test_stream_save_error_with_verified_cleanup_does_not_retain_tombstone(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    journal = MagicMock()
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    async def fail_save(
        _request: object,
        destination: Path,
        *,
        expected_size: int | None,
        cleanup_on_error: bool,
    ) -> None:
        assert expected_size == len(b"video")
        assert cleanup_on_error is False
        job_id = destination.stem.removesuffix("_input")
        assert (
            get_workspace_owner(
                data_dir=destination.parent.parent,
                job_id=job_id,
            )
            == user_id
        )
        lock_result: list[str] = []

        def contend_for_retention_lock() -> None:
            try:
                with lock_job_workspace(
                    data_dir=destination.parent.parent,
                    job_id=job_id,
                    timeout_seconds=0.05,
                ):
                    lock_result.append("acquired")
            except JobWorkspaceLockTimeoutError:
                lock_result.append("blocked")

        contender = threading.Thread(target=contend_for_retention_lock)
        contender.start()
        contender.join(timeout=2)
        assert not contender.is_alive()
        assert lock_result == ["blocked"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"partial private upload")
        captured["path"] = destination
        raise OSError(errno.ENOSPC, "disk full")

    metadata = base64.b64encode(
        json.dumps(
            {"filename": "video.mp4", "authorized_credits": 100},
        ).encode("utf-8"),
    ).decode("ascii")
    monkeypatch.setattr(videos, "save_request_stream_with_limit", fail_save)
    monkeypatch.setattr(videos, "configured_erasure_journal", lambda: journal)

    response = client.post(
        "/videos/process-stream",
        headers={
            **user_auth_headers,
            "content-type": "video/mp4",
            "x-gsubs-upload-metadata": metadata,
        },
        content=b"video",
    )

    assert response.status_code == 507
    path = captured["path"]
    assert isinstance(path, Path) and not path.exists()
    job_id = path.stem.removesuffix("_input")
    assert get_workspace_owner(data_dir=path.parent.parent, job_id=job_id) is None
    journal.append.assert_not_called()


def test_stream_budget_preflight_rejects_before_uuid_or_workspace_write(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = MagicMock(
        side_effect=ProviderBudgetExceededError("Daily external provider budget exceeded"),
    )
    uuid4 = MagicMock(side_effect=AssertionError("budget preflight must precede UUID allocation"))
    save = MagicMock(side_effect=AssertionError("budget preflight must precede upload writes"))
    monkeypatch.setattr(videos, "preflight_processing_provider_budget", preflight)
    monkeypatch.setattr(videos.uuid, "uuid4", uuid4)
    monkeypatch.setattr(videos, "save_request_stream_with_limit", save)

    metadata = base64.b64encode(
        json.dumps(
            {
                "filename": "video.mp4",
                "authorized_credits": 100,
                "transcribe_provider": "elevenlabs",
                "transcribe_tier": "pro",
            },
        ).encode("utf-8"),
    ).decode("ascii")
    response = client.post(
        "/videos/process-stream",
        headers={
            **user_auth_headers,
            "content-type": "video/mp4",
            "x-gsubs-upload-metadata": metadata,
        },
        content=b"private-video",
    )

    assert response.status_code == 503
    assert response.json()["code"] == "PROVIDER_BUDGET_REACHED"
    preflight.assert_called_once()
    uuid4.assert_not_called()
    save.assert_not_called()
