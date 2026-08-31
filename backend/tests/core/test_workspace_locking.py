from __future__ import annotations

import hashlib
import multiprocessing
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import pytest

from backend.app.core import cleanup, workspace_deletion
from backend.app.core.erasure_journal import ErasureJournal
from backend.app.core.workspace_deletion import (
    JobWorkspaceLockTimeoutError,
    lock_job_workspace,
    lock_job_workspaces,
    reclaim_abandoned_lifecycle_locks,
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


def _hold_job_lock(data_dir: str, job_id: str, ready_path: str) -> None:
    with lock_job_workspace(data_dir=Path(data_dir), job_id=job_id):
        Path(ready_path).write_text("ready", encoding="utf-8")
        Event().wait()


def test_job_workspace_lock_serializes_separate_processes(tmp_path: Path) -> None:
    # REGRESSION: in-memory synchronization cannot protect a shared Docker
    # volume when two backend worker processes export and erase the same job.
    same_job_result = tmp_path / "same-job-result.txt"
    different_job_result = tmp_path / "different-job-result.txt"
    process_context = multiprocessing.get_context("fork")

    first_job_id = "shared-job"
    # These IDs collided under the former 256-stripe implementation. A
    # long-lived worker for one must never suppress the other worker.
    colliding_job_id = "collision-31"
    assert workspace_deletion._job_workspace_lock_name(
        first_job_id,
    ) != workspace_deletion._job_workspace_lock_name(colliding_job_id)

    with lock_job_workspace(data_dir=tmp_path, job_id=first_job_id):
        same_job_contender = process_context.Process(
            target=_attempt_job_lock,
            args=(str(tmp_path), first_job_id, str(same_job_result)),
        )
        different_job_contender = process_context.Process(
            target=_attempt_job_lock,
            args=(str(tmp_path), colliding_job_id, str(different_job_result)),
        )
        same_job_contender.start()
        different_job_contender.start()
        same_job_contender.join(timeout=5)
        different_job_contender.join(timeout=5)

    assert same_job_contender.exitcode == 0
    assert different_job_contender.exitcode == 0
    assert same_job_result.read_text(encoding="utf-8") == "timed-out"
    assert different_job_result.read_text(encoding="utf-8") == "acquired"

    successor = process_context.Process(
        target=_attempt_job_lock,
        args=(str(tmp_path), first_job_id, str(same_job_result)),
    )
    successor.start()
    successor.join(timeout=5)

    assert successor.exitcode == 0
    assert same_job_result.read_text(encoding="utf-8") == "acquired"


def test_multiple_job_locks_are_deduplicated_and_sorted_by_lock_name(
    monkeypatch,
    tmp_path: Path,
) -> None:
    acquired: list[str] = []
    lock_names = {
        "job-z": "09.lock",
        "job-a": "02.lock",
        "job-m": "05.lock",
        "job-collision": "02.lock",
    }

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
        "_job_workspace_lock_name",
        lock_names.__getitem__,
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


def test_job_workspace_lock_files_are_per_job_and_opaque(tmp_path: Path) -> None:
    # A long-lived processing lock must not collide with an unrelated job.
    # Hash filenames avoid exposing the server-generated job identifier.
    job_ids = [f"admitted-job-{index}" for index in range(32)]
    lock_root = tmp_path / ".job-locks"
    with ExitStack() as stack:
        for job_id in job_ids:
            stack.enter_context(lock_job_workspace(data_dir=tmp_path, job_id=job_id))

        lock_files = list(lock_root.glob("*.lock"))
        assert len(lock_files) == len(job_ids)
        assert {path.name for path in lock_files} == {
            f"{hashlib.sha256(job_id.encode('utf-8')).hexdigest()}.lock" for job_id in job_ids
        }

    # Normal releases retire per-identity inodes safely; only one bounded
    # registry inode remains for the namespace.
    assert list(lock_root.glob("*.lock")) == []
    assert {path.name for path in lock_root.iterdir()} == {".registry"}


def test_startup_scavenger_reclaims_sigkill_lock_without_unlinking_live_holder(
    tmp_path: Path,
) -> None:
    process_context = multiprocessing.get_context("fork")
    abandoned_job_id = "killed-writer"
    live_job_id = "live-writer"
    abandoned_ready = tmp_path / "abandoned-ready"
    live_ready = tmp_path / "live-ready"

    abandoned = process_context.Process(
        target=_hold_job_lock,
        args=(str(tmp_path), abandoned_job_id, str(abandoned_ready)),
    )
    abandoned.start()
    for _ in range(500):
        if abandoned_ready.exists():
            break
        abandoned.join(timeout=0.01)
    assert abandoned_ready.exists()
    assert abandoned.pid is not None
    os.kill(abandoned.pid, 9)
    abandoned.join(timeout=5)
    assert abandoned.exitcode == -9

    live = process_context.Process(
        target=_hold_job_lock,
        args=(str(tmp_path), live_job_id, str(live_ready)),
    )
    live.start()
    for _ in range(500):
        if live_ready.exists():
            break
        live.join(timeout=0.01)
    assert live_ready.exists()

    try:
        assert reclaim_abandoned_lifecycle_locks(data_dir=tmp_path) == 1
        lock_names = {path.name for path in (tmp_path / ".job-locks").glob("*.lock")}
        assert lock_names == {
            workspace_deletion._job_workspace_lock_name(live_job_id),
        }
    finally:
        live.terminate()
        live.join(timeout=5)

    assert reclaim_abandoned_lifecycle_locks(data_dir=tmp_path) == 1
    assert list((tmp_path / ".job-locks").glob("*.lock")) == []


def test_startup_scavenger_preserves_unknown_entries(tmp_path: Path) -> None:
    lock_root = tmp_path / ".job-locks"
    lock_root.mkdir()
    unknown = lock_root / "manual-review.lock"
    unknown.write_text("do not remove", encoding="utf-8")

    assert reclaim_abandoned_lifecycle_locks(data_dir=tmp_path) == 0
    assert unknown.read_text(encoding="utf-8") == "do not remove"


def test_retention_scavenger_reclaims_lock_left_by_cleanup_starvation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    job_id = "cleanup-starved-writer"
    with monkeypatch.context() as patch_context:
        patch_context.setattr(
            workspace_deletion,
            "_acquire_registry_for_cleanup",
            lambda *_args, **_kwargs: False,
        )
        with lock_job_workspace(data_dir=tmp_path, job_id=job_id):
            pass

    lock_root = tmp_path / ".job-locks"
    assert {path.name for path in lock_root.glob("*.lock")} == {
        workspace_deletion._job_workspace_lock_name(job_id),
    }
    assert reclaim_abandoned_lifecycle_locks(data_dir=tmp_path) == 1
    assert list(lock_root.glob("*.lock")) == []


def test_scavenger_reaches_stale_tail_past_multiple_live_holders(
    tmp_path: Path,
) -> None:
    live_job_ids = ["live-prefix-a", "live-prefix-b"]
    stale_job_id = "stale-tail"
    lock_root = tmp_path / ".job-locks"

    with ExitStack() as stack:
        for job_id in live_job_ids:
            stack.enter_context(lock_job_workspace(data_dir=tmp_path, job_id=job_id))
        stale_path = lock_root / workspace_deletion._job_workspace_lock_name(
            stale_job_id,
        )
        stale_path.touch(mode=0o600)

        assert reclaim_abandoned_lifecycle_locks(data_dir=tmp_path) == 1
        assert not stale_path.exists()
        assert {path.name for path in lock_root.glob("*.lock")} == {
            workspace_deletion._job_workspace_lock_name(job_id) for job_id in live_job_ids
        }


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


def test_account_registry_retries_transient_first_use_enoent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: five first-time uploads could race while creating the shared
    # registry on Darwin, returning a 500 to one otherwise valid customer.
    real_open = workspace_deletion.os.open
    transient_failures = 0

    def transient_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal transient_failures
        if path == ".registry" and transient_failures == 0:
            transient_failures += 1
            raise FileNotFoundError(2, "synthetic concurrent create")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(workspace_deletion.os, "open", transient_open)

    with workspace_deletion.lock_account_lifecycle(
        data_dir=tmp_path,
        user_id="parallel-customer",
        shared=True,
    ):
        pass

    assert transient_failures == 1


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
