from __future__ import annotations

import base64
import errno
import json
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.app.api.endpoints.settings import ProcessingSettings
from backend.app.services.usage_ledger import ChargePlan


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
def test_rejected_media_is_journaled_before_pre_job_workspace_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    probe_result: object,
) -> None:
    job_id = "rejected-media-job"
    user_id = "rejected-media-user"
    input_path, artifacts_root, partial_artifact = _saved_workspace(tmp_path, job_id)
    journal = _journal_asserting_source_exists(input_path, partial_artifact)
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
            proc_settings=ProcessingSettings(),
            current_user=types.SimpleNamespace(id=user_id),
            job_store=job_store,
            history_store=MagicMock(),
            ledger_store=MagicMock(),
            db=MagicMock(),
        )

    journal.append.assert_called_once_with(
        kind="workspace",
        user_id=user_id,
        job_ids=[job_id],
    )
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


def test_stream_save_error_is_journaled_before_partial_file_cleanup(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    captured: dict[str, object] = {}
    journal = MagicMock()

    async def fail_save(
        _request: object,
        destination: Path,
        *,
        expected_size: int | None,
        cleanup_on_error: bool,
    ) -> None:
        assert expected_size == len(b"video")
        assert cleanup_on_error is False
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"partial private upload")
        captured["path"] = destination
        raise OSError(errno.ENOSPC, "disk full")

    def append(**kwargs: object) -> None:
        path = captured["path"]
        assert isinstance(path, Path) and path.is_file()
        captured["tombstone"] = kwargs

    metadata = base64.b64encode(json.dumps({"filename": "video.mp4"}).encode("utf-8")).decode("ascii")
    journal.append.side_effect = append
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
    assert captured["tombstone"] == {
        "kind": "workspace",
        "user_id": user_id,
        "job_ids": [path.name.removesuffix("_input.mp4")],
    }
