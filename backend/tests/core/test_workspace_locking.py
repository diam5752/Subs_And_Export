from __future__ import annotations

import multiprocessing
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from backend.app.core import cleanup, workspace_deletion
from backend.app.core.erasure_journal import ErasureJournal
from backend.app.core.workspace_deletion import (
    JOB_WORKSPACE_LOCK_STRIPES,
    JobWorkspaceLockTimeoutError,
    lock_job_workspace,
    lock_job_workspaces,
)


def _attempt_job_lock(data_dir: str, job_id: str, result_path: str) -> None:
    result = Path(result_path)
    try:
        with lock_job_workspace(
            data_dir=Path(data_dir),
            job_id=job_id,
            timeout_seconds=0.2,
        ):
            result.write_text("acquired", encoding="utf-8")
    except JobWorkspaceLockTimeoutError:
        result.write_text("timed-out", encoding="utf-8")


def test_job_workspace_lock_serializes_separate_processes(tmp_path: Path) -> None:
    # REGRESSION: in-memory synchronization cannot protect a shared Docker
    # volume when two backend worker processes export and erase the same job.
    result_path = tmp_path / "child-result.txt"
    process_context = multiprocessing.get_context("fork")

    first_job_id = "shared-job"
    colliding_job_id = "collision-31"
    assert workspace_deletion._job_workspace_lock_stripe(
        first_job_id,
    ) == workspace_deletion._job_workspace_lock_stripe(colliding_job_id)

    with lock_job_workspace(data_dir=tmp_path, job_id=first_job_id):
        contender = process_context.Process(
            target=_attempt_job_lock,
            args=(str(tmp_path), colliding_job_id, str(result_path)),
        )
        contender.start()
        contender.join(timeout=5)

    assert contender.exitcode == 0
    assert result_path.read_text(encoding="utf-8") == "timed-out"

    successor = process_context.Process(
        target=_attempt_job_lock,
        args=(str(tmp_path), "shared-job", str(result_path)),
    )
    successor.start()
    successor.join(timeout=5)

    assert successor.exitcode == 0
    assert result_path.read_text(encoding="utf-8") == "acquired"


def test_multiple_job_locks_are_deduplicated_and_sorted_by_stripe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    acquired: list[str] = []
    stripes = {"job-z": 9, "job-a": 2, "job-m": 5, "job-collision": 2}

    @contextmanager
    def record_lock(
        *,
        data_dir: Path,
        job_id: str,
        timeout_seconds: float,
    ) -> Iterator[None]:
        assert data_dir == tmp_path
        assert 0 < timeout_seconds <= 1.0
        acquired.append(job_id)
        yield

    monkeypatch.setattr(workspace_deletion, "lock_job_workspace", record_lock)
    monkeypatch.setattr(
        workspace_deletion,
        "_job_workspace_lock_stripe",
        stripes.__getitem__,
    )

    with lock_job_workspaces(
        data_dir=tmp_path,
        job_ids=["job-z", "job-a", "job-z", "job-m", "job-collision"],
        timeout_seconds=1.0,
    ):
        assert acquired == ["job-a", "job-m", "job-z"]

    with pytest.raises(ValueError, match="cannot be negative"):
        with lock_job_workspaces(
            data_dir=tmp_path,
            job_ids=["job-a"],
            timeout_seconds=-1,
        ):
            pass


def test_job_workspace_lock_files_have_bounded_cardinality(tmp_path: Path) -> None:
    # REGRESSION: one persistent lock inode per rejected UUID allowed an
    # authenticated caller to grow the local volume without a fixed bound.
    for index in range(JOB_WORKSPACE_LOCK_STRIPES * 4):
        with lock_job_workspace(data_dir=tmp_path, job_id=f"attempt-{index}"):
            pass

    lock_files = list((tmp_path / ".job-locks").glob("*.lock"))
    assert 1 < len(lock_files) <= JOB_WORKSPACE_LOCK_STRIPES
    assert all(path.name.startswith("stripe-") for path in lock_files)


def test_job_workspace_lock_repairs_private_permissions(tmp_path: Path) -> None:
    # REGRESSION: mkdir(mode=...) does not tighten an existing directory, so a
    # restored or misconfigured volume could leave lock metadata world-readable.
    lock_root = tmp_path / ".job-locks"
    lock_root.mkdir(mode=0o777)
    lock_root.chmod(0o777)

    with lock_job_workspace(data_dir=tmp_path, job_id="private-job"):
        lock_file = next(lock_root.glob("*.lock"))
        assert lock_root.stat().st_mode & 0o777 == 0o700
        assert lock_file.stat().st_mode & 0o777 == 0o600


@dataclass
class _RetentionJob:
    id: str
    user_id: str
    status: str
    updated_at: int


class _RetentionStore:
    def __init__(self, job: _RetentionJob) -> None:
        self.job = job

    def list_jobs_updated_before(
        self,
        timestamp: int,
        statuses: set[str] | frozenset[str],
    ) -> list[_RetentionJob]:
        if self.job.updated_at < timestamp and self.job.status in statuses:
            return [self.job]
        return []

    def get_job(self, job_id: str) -> _RetentionJob | None:
        return self.job if self.job.id == job_id else None

    def delete_job(self, job_id: str) -> None:
        if self.job.id == job_id:
            self.job = _RetentionJob("deleted", "deleted", "failed", 0)


class _RetentionHistory:
    def delete_job_events(self, job_ids: list[str]) -> int:
        return len(job_ids)


def test_retention_waits_for_workspace_writer_before_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: retention could delete an expired project while an exporter
    # was paused, allowing that exporter to recreate personal data afterward.
    job_id = "expired-export"
    now = 1_800_000_000
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    artifact_dir = artifacts_dir / job_id
    uploads_dir.mkdir()
    artifact_dir.mkdir(parents=True)
    (uploads_dir / f"{job_id}_input.mp4").write_bytes(b"private video")
    (artifact_dir / "transcription.json").write_text("private", encoding="utf-8")
    store = _RetentionStore(
        _RetentionJob(
            id=job_id,
            user_id="user-1",
            status="completed",
            updated_at=now - (25 * 3600),
        ),
    )
    cleanup_waiting = Event()
    real_lock = workspace_deletion.lock_job_workspace

    @contextmanager
    def track_cleanup_lock(**kwargs) -> Iterator[None]:
        cleanup_waiting.set()
        with real_lock(**kwargs):
            yield

    monkeypatch.setattr(cleanup, "lock_job_workspace", track_cleanup_lock)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with real_lock(data_dir=tmp_path, job_id=job_id):
            cleanup_request = executor.submit(
                cleanup.cleanup_expired_workspaces,
                job_store=store,
                history_store=_RetentionHistory(),
                uploads_dir=uploads_dir,
                artifacts_dir=artifacts_dir,
                workspace_retention_hours=24,
                stale_job_retention_hours=6,
                orphan_retention_hours=1,
                erasure_journal=ErasureJournal(
                    tmp_path / "privacy-journal",
                    retention_days=30,
                ),
                now=now,
            )
            assert cleanup_waiting.wait(timeout=5)
            assert not cleanup_request.done()

        report = cleanup_request.result(timeout=5)
    assert report.deleted_job_ids == [job_id]
    assert not artifact_dir.exists()
    assert not (uploads_dir / f"{job_id}_input.mp4").exists()
