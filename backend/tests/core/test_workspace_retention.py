from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from backend.app.core import cleanup as cleanup_module
from backend.app.core.cleanup import (
    cleanup_expired_workspaces,
    ensure_storage_capacity,
    run_configured_retention,
)
from backend.app.services import billing_retention
from backend.app.services.jobs import Job


@dataclass
class FakeJobStore:
    jobs: dict[str, Job]

    def list_jobs_updated_before(
        self,
        timestamp: int,
        statuses: set[str] | frozenset[str],
    ) -> list[Job]:
        return [job for job in self.jobs.values() if job.updated_at < timestamp and job.status in statuses]

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def delete_job(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)


@dataclass
class FakeHistoryStore:
    deleted_job_ids: list[str]

    def delete_job_events(self, job_ids: list[str]) -> int:
        self.deleted_job_ids.extend(job_ids)
        return len(job_ids)


def _job(job_id: str, *, status: str, updated_at: int) -> Job:
    return Job(
        id=job_id,
        user_id="user-1",
        status=status,
        progress=100 if status == "completed" else 25,
        message=None,
        created_at=updated_at - 60,
        updated_at=updated_at,
        result_data={"original_filename": f"{job_id}.mp4"},
    )


def _workspace(uploads_dir: Path, artifacts_dir: Path, job_id: str) -> None:
    (uploads_dir / f"{job_id}_input.mp4").write_bytes(b"upload")
    artifact_dir = artifacts_dir / job_id
    artifact_dir.mkdir()
    (artifact_dir / "processed.mp4").write_bytes(b"result")


def test_terminal_job_exposes_activity_based_expiry() -> None:
    terminal_job = _job("done", status="completed", updated_at=1_800_000_000)
    active_job = _job("working", status="processing", updated_at=1_800_000_000)

    assert terminal_job.expires_at == 1_800_086_400
    assert active_job.expires_at is None


def test_cleanup_uses_job_activity_and_preserves_active_work(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()
    now = 1_800_000_000

    jobs = {
        "expired": _job("expired", status="completed", updated_at=now - 25 * 3600),
        "recent": _job("recent", status="completed", updated_at=now - 23 * 3600),
        "active": _job("active", status="processing", updated_at=now - 5 * 3600),
        "abandoned": _job("abandoned", status="processing", updated_at=now - 7 * 3600),
    }
    for job_id in jobs:
        _workspace(uploads_dir, artifacts_dir, job_id)

    orphan_old = uploads_dir / "orphan_input.mov"
    orphan_old.write_bytes(b"old")
    orphan_recent = artifacts_dir / "recent-orphan"
    orphan_recent.mkdir()
    gitkeep = uploads_dir / ".gitkeep"
    gitkeep.touch()
    old_timestamp = now - 2 * 3600
    os.utime(orphan_old, (old_timestamp, old_timestamp))
    os.utime(orphan_recent, (now, now))
    os.utime(gitkeep, (old_timestamp, old_timestamp))

    job_store = FakeJobStore(jobs)
    history_store = FakeHistoryStore([])

    # REGRESSION: filesystem mtime cleanup previously deleted uploads without
    # respecting refreshed project activity and never removed generated exports.
    report = cleanup_expired_workspaces(
        job_store=job_store,
        history_store=history_store,
        uploads_dir=uploads_dir,
        artifacts_dir=artifacts_dir,
        workspace_retention_hours=24,
        stale_job_retention_hours=6,
        orphan_retention_hours=1,
        now=now,
    )

    assert report.deleted_job_ids == ["abandoned", "expired"]
    assert set(job_store.jobs) == {"active", "recent"}
    assert history_store.deleted_job_ids == ["abandoned", "expired"]
    for removed_id in ("expired", "abandoned"):
        assert not (uploads_dir / f"{removed_id}_input.mp4").exists()
        assert not (artifacts_dir / removed_id).exists()
    for preserved_id in ("recent", "active"):
        assert (uploads_dir / f"{preserved_id}_input.mp4").is_file()
        assert (artifacts_dir / preserved_id).is_dir()
    assert not orphan_old.exists()
    assert orphan_recent.exists()
    assert gitkeep.exists()


def test_cleanup_rechecks_activity_before_deleting_candidate(tmp_path: Path) -> None:
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()
    now = 1_800_000_000
    job_store = FakeJobStore({"refreshed": _job("refreshed", status="completed", updated_at=now - 25 * 3600)})
    history_store = FakeHistoryStore([])
    _workspace(uploads_dir, artifacts_dir, "refreshed")

    original_list = job_store.list_jobs_updated_before

    def list_then_refresh(
        timestamp: int,
        statuses: set[str] | frozenset[str],
    ) -> list[Job]:
        candidates = original_list(timestamp, statuses)
        if candidates:
            job_store.jobs["refreshed"].updated_at = now
        return candidates

    job_store.list_jobs_updated_before = list_then_refresh  # type: ignore[method-assign]

    # REGRESSION: an export or edit may refresh a project after candidate
    # selection but before deletion. The cleanup pass must honor that activity.
    report = cleanup_expired_workspaces(
        job_store=job_store,
        history_store=history_store,
        uploads_dir=uploads_dir,
        artifacts_dir=artifacts_dir,
        workspace_retention_hours=24,
        stale_job_retention_hours=6,
        orphan_retention_hours=1,
        now=now,
    )

    assert report.deleted_job_ids == []
    assert "refreshed" in job_store.jobs
    assert (uploads_dir / "refreshed_input.mp4").is_file()
    assert (artifacts_dir / "refreshed").is_dir()
    assert history_store.deleted_job_ids == []


def test_cleanup_keeps_database_row_when_file_removal_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()
    now = 1_800_000_000
    job_store = FakeJobStore({"retry-me": _job("retry-me", status="completed", updated_at=now - 25 * 3600)})
    history_store = FakeHistoryStore([])
    _workspace(uploads_dir, artifacts_dir, "retry-me")

    original_unlink = Path.unlink

    def fail_target(path: Path, *args, **kwargs):
        if path.name == "retry-me_input.mp4":
            raise PermissionError("read-only")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_target)

    report = cleanup_expired_workspaces(
        job_store=job_store,
        history_store=history_store,
        uploads_dir=uploads_dir,
        artifacts_dir=artifacts_dir,
        workspace_retention_hours=24,
        stale_job_retention_hours=6,
        orphan_retention_hours=1,
        now=now,
    )

    assert report.deleted_job_ids == []
    assert report.failed_job_ids == ["retry-me"]
    assert "retry-me" in job_store.jobs
    assert history_store.deleted_job_ids == []


def test_storage_guard_runs_cleanup_once_before_rejecting_or_accepting(
    tmp_path: Path,
    monkeypatch,
) -> None:
    free_bytes = iter((2_100_000_000, 3_000_000_000))
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        "backend.app.core.cleanup.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=10_000_000_000, used=7_000_000_000, free=next(free_bytes)),
    )

    # REGRESSION: uploads previously started without reserving room for the
    # source plus generated exports, allowing the server to fill mid-process.
    assert ensure_storage_capacity(
        tmp_path,
        required_bytes=500_000_000,
        minimum_free_mb=2048,
        cleanup_callback=lambda: cleanup_calls.append("cleanup"),
    )
    assert cleanup_calls == ["cleanup"]


def test_storage_guard_rejects_when_cleanup_cannot_free_enough_space(
    tmp_path: Path,
    monkeypatch,
) -> None:
    cleanup_calls: list[str] = []
    monkeypatch.setattr(
        "backend.app.core.cleanup.shutil.disk_usage",
        lambda _path: SimpleNamespace(total=10_000, used=9_500, free=500),
    )

    assert not ensure_storage_capacity(
        tmp_path,
        required_bytes=1_000,
        minimum_free_mb=1,
        cleanup_callback=lambda: cleanup_calls.append("cleanup"),
    )
    assert cleanup_calls == ["cleanup"]


def test_configured_retention_runs_media_and_billing_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(cleanup_module.settings, "data_dir", tmp_path)
    monkeypatch.setattr(
        cleanup_module,
        "cleanup_expired_workspaces",
        lambda **_kwargs: (
            calls.append("media")
            or SimpleNamespace(
                deleted_job_ids=[],
                failed_job_ids=[],
                deleted_orphan_items=0,
            )
        ),
    )
    monkeypatch.setattr(
        billing_retention,
        "cleanup_expired_billing_records",
        lambda _db: (
            calls.append("billing")
            or SimpleNamespace(
                deleted_unpaid_attempts=0,
                deleted_financial_records=0,
            )
        ),
    )
    run_configured_retention(object())  # type: ignore[arg-type]

    assert calls == ["media", "billing"]
