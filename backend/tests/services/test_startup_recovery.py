from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from backend.app.core.auth import UserStore
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournal
from backend.app.core.workspace_ownership import record_workspace_ownership
from backend.app.services.charge_plans import reserve_transcription_charge
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore
from backend.app.services.startup_recovery import reconcile_interrupted_media_jobs
from backend.app.services.usage_ledger import UsageLedgerStore


def test_startup_recovery_fails_job_refunds_and_deletes_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # REGRESSION: a container restart previously left paid pending/processing
    # jobs stuck until the six-hour stale-retention pass.
    db = Database()
    user = UserStore(db=db).register_local_user(
        f"restart-{uuid.uuid4().hex}@example.com",
        "testpassword123",
        "Restart Recovery",
    )
    points_store = PointsStore(db=db)
    points_store.credit(
        user.id,
        100,
        reason="test_restart_recovery_funding",
    )
    job_id = f"restart-{uuid.uuid4().hex}"
    job_store = JobStore(db=db)
    job_store.create_job(job_id, user.id)
    job_store.update_job(job_id, status="processing", progress=42)

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts" / job_id
    uploads_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)
    upload_path = uploads_dir / f"{job_id}_input.mp4"
    output_path = artifacts_dir / "processed.mp4"
    upload_path.write_bytes(b"source")
    output_path.write_bytes(b"partial")
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=job_id,
        user_id=user.id,
    )

    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reserve_transcription_charge(
        ledger_store=ledger_store,
        user_id=user.id,
        job_id=job_id,
        tier="standard",
        duration_seconds=30.0,
        provider="mock",
        model="mock-caption-v1",
        enforce_budget=False,
        require_paid_credits=False,
    )
    assert points_store.get_balance(user.id) == 70

    journal = ErasureJournal(tmp_path / "journal", retention_days=30)
    journal.initialize()
    monkeypatch.setattr(
        "backend.app.services.startup_recovery.configured_erasure_journal",
        lambda: journal,
    )

    # The canonical PostgreSQL quality gate shares one database across tests.
    # Restrict this regression to its own job so invoking the global startup
    # reconciler cannot mutate unrelated fixtures created earlier in the suite.
    original_list_jobs = JobStore.list_jobs_with_statuses

    def list_only_target_job(self: JobStore, statuses: set[str] | frozenset[str]):
        return [job for job in original_list_jobs(self, statuses) if job.id == job_id]

    monkeypatch.setattr(
        JobStore,
        "list_jobs_with_statuses",
        list_only_target_job,
    )

    assert reconcile_interrupted_media_jobs(db) == 1

    recovered_job = job_store.get_job(job_id)
    assert recovered_job is not None
    assert recovered_job.status == "failed"
    assert "service restart" in (recovered_job.message or "")
    assert points_store.get_balance(user.id) == 100
    assert not upload_path.exists()
    assert not output_path.exists()

    # Re-running startup recovery must be idempotent.
    assert reconcile_interrupted_media_jobs(db) == 0
    assert points_store.get_balance(user.id) == 100
