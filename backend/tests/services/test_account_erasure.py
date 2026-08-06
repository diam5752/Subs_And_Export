from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest

from backend.app.core.auth import UserStore
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournal, ErasureTombstone
from backend.app.core.workspace_deletion import delete_job_workspace
from backend.app.core.workspace_ownership import (
    get_workspace_owner,
    record_workspace_ownership,
)
from backend.app.db.models import DbJob, DbUser
from backend.app.services.account_erasure import (
    AccountErasureReport,
    ErasureReplayConflictError,
    erase_account_and_media,
)
from backend.app.services.billing import BillingService
from backend.app.services.erasure_reconciliation import reconcile_erasure_journal
from backend.app.services.points import PointsStore


def _create_user(db: Database, *, label: str) -> str:
    user = UserStore(db=db).register_local_user(
        email=f"{label}-{uuid.uuid4().hex}@example.com",
        password="testpassword123",
        name=label,
    )
    return user.id


def _create_terminal_job(
    db: Database,
    *,
    job_id: str,
    user_id: str,
) -> None:
    now = int(time.time())
    with db.session() as session:
        session.add(
            DbJob(
                id=job_id,
                user_id=user_id,
                status="failed",
                created_at=now,
                updated_at=now,
                progress=0,
                message="Failed",
                result_data=None,
            ),
        )


def _create_workspace(data_dir: Path, *, job_id: str, marker: bytes) -> None:
    uploads_dir = data_dir / "uploads"
    artifact_dir = data_dir / "artifacts" / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / f"{job_id}_input.mp4").write_bytes(marker)
    (artifact_dir / "private.txt").write_bytes(marker)


def _erase(
    *,
    db: Database,
    user_id: str,
    data_dir: Path,
    journal: ErasureJournal,
) -> AccountErasureReport:
    points_store = PointsStore(db=db)
    return erase_account_and_media(
        db=db,
        billing_service=BillingService(db=db, points_store=points_store),
        user_store=UserStore(db=db),
        user_id=user_id,
        data_dir=data_dir,
        journal=journal,
    )


def test_account_erasure_includes_only_journal_owned_pre_row_media(
    tmp_path: Path,
) -> None:
    db = Database()
    erased_user_id = _create_user(db, label="orphan-owner")
    other_user_id = _create_user(db, label="other-owner")
    database_job_id = f"database-{uuid.uuid4().hex}"
    pre_row_job_id = f"pre-row-{uuid.uuid4().hex}"
    other_job_id = f"other-{uuid.uuid4().hex}"
    unknown_orphan_id = f"unknown-{uuid.uuid4().hex}"
    _create_terminal_job(
        db,
        job_id=database_job_id,
        user_id=erased_user_id,
    )
    _create_terminal_job(db, job_id=other_job_id, user_id=other_user_id)
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=pre_row_job_id,
        user_id=erased_user_id,
    )
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=other_job_id,
        user_id=other_user_id,
    )
    for job_id, marker in (
        (database_job_id, b"database-owned"),
        (pre_row_job_id, b"journal-owned"),
        (other_job_id, b"other-user"),
        (unknown_orphan_id, b"unknown-owner"),
    ):
        _create_workspace(tmp_path, job_id=job_id, marker=marker)
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append(
        kind="workspace",
        user_id=other_user_id,
        job_ids=[other_job_id],
    )
    journal.append_orphan_workspace(job_ids=[unknown_orphan_id])

    report = _erase(
        db=db,
        user_id=erased_user_id,
        data_dir=tmp_path,
        journal=journal,
    )

    assert report.deleted_job_ids == sorted([database_job_id, pre_row_job_id])
    assert not (tmp_path / "uploads" / f"{database_job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / database_job_id).exists()
    assert not (tmp_path / "uploads" / f"{pre_row_job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / pre_row_job_id).exists()
    assert get_workspace_owner(data_dir=tmp_path, job_id=pre_row_job_id) is None
    assert (tmp_path / "uploads" / f"{other_job_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / other_job_id / "private.txt").is_file()
    assert get_workspace_owner(data_dir=tmp_path, job_id=other_job_id) == other_user_id
    assert (tmp_path / "uploads" / f"{unknown_orphan_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / unknown_orphan_id / "private.txt").is_file()
    account_entries = [
        entry
        for entry in journal.read_all()
        if isinstance(entry, ErasureTombstone) and entry.kind == "account" and entry.user_id == erased_user_id
    ]
    assert len(account_entries) == 1
    assert account_entries[0].job_ids == sorted([database_job_id, pre_row_job_id])
    with db.session() as session:
        assert session.get(DbUser, erased_user_id) is None
        assert session.get(DbUser, other_user_id) is not None
        assert session.get(DbJob, other_job_id) is not None


def test_account_erasure_rejects_foreign_row_for_journal_owned_job_id(
    tmp_path: Path,
) -> None:
    db = Database()
    erased_user_id = _create_user(db, label="claimed-owner")
    actual_user_id = _create_user(db, label="actual-owner")
    collision_job_id = f"collision-{uuid.uuid4().hex}"
    _create_terminal_job(
        db,
        job_id=collision_job_id,
        user_id=actual_user_id,
    )
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=collision_job_id,
        user_id=actual_user_id,
    )
    _create_workspace(tmp_path, job_id=collision_job_id, marker=b"foreign")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append(
        kind="workspace",
        user_id=erased_user_id,
        job_ids=[collision_job_id],
    )

    with pytest.raises(ErasureReplayConflictError, match="ownership conflicts"):
        _erase(
            db=db,
            user_id=erased_user_id,
            data_dir=tmp_path,
            journal=journal,
        )

    assert (tmp_path / "uploads" / f"{collision_job_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / collision_job_id / "private.txt").is_file()
    with db.session() as session:
        assert session.get(DbUser, erased_user_id) is not None
        assert session.get(DbUser, actual_user_id) is not None
        assert session.get(DbJob, collision_job_id) is not None


def test_account_erasure_fails_closed_when_exact_media_absence_is_unverified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database()
    user_id = _create_user(db, label="unverified-cleanup")
    pre_row_job_id = f"unverified-{uuid.uuid4().hex}"
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=pre_row_job_id,
        user_id=user_id,
    )
    _create_workspace(tmp_path, job_id=pre_row_job_id, marker=b"private")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    monkeypatch.setattr(
        "backend.app.services.account_erasure.delete_job_workspace",
        lambda **_kwargs: None,
    )

    with pytest.raises(RuntimeError, match="cleanup could not be verified"):
        _erase(
            db=db,
            user_id=user_id,
            data_dir=tmp_path,
            journal=journal,
        )

    assert (tmp_path / "uploads" / f"{pre_row_job_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / pre_row_job_id / "private.txt").is_file()
    assert get_workspace_owner(data_dir=tmp_path, job_id=pre_row_job_id) == (user_id)
    with db.session() as session:
        assert session.get(DbUser, user_id) is not None
    account_entries = [
        entry
        for entry in journal.read_all()
        if isinstance(entry, ErasureTombstone) and entry.kind == "account" and entry.user_id == user_id
    ]
    assert len(account_entries) == 1
    assert account_entries[0].job_ids == [pre_row_job_id]


def test_crash_after_account_tombstone_replays_pre_row_media_erasure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = Database()
    user_id = _create_user(db, label="crash-replay")
    pre_row_job_id = f"crash-pre-row-{uuid.uuid4().hex}"
    unknown_orphan_id = f"crash-unknown-{uuid.uuid4().hex}"
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=pre_row_job_id,
        user_id=user_id,
    )
    _create_workspace(tmp_path, job_id=pre_row_job_id, marker=b"private")
    _create_workspace(tmp_path, job_id=unknown_orphan_id, marker=b"keep")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)

    def simulate_crash(**_kwargs: object) -> None:
        raise RuntimeError("simulated crash after durable account intent")

    monkeypatch.setattr(
        "backend.app.services.account_erasure.delete_job_workspace",
        simulate_crash,
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        _erase(
            db=db,
            user_id=user_id,
            data_dir=tmp_path,
            journal=journal,
        )
    monkeypatch.setattr(
        "backend.app.services.account_erasure.delete_job_workspace",
        delete_job_workspace,
    )

    with db.session() as session:
        assert session.get(DbUser, user_id) is not None
    assert (tmp_path / "uploads" / f"{pre_row_job_id}_input.mp4").is_file()
    assert get_workspace_owner(data_dir=tmp_path, job_id=pre_row_job_id) == (user_id)
    account_entries = [
        entry
        for entry in journal.read_all()
        if isinstance(entry, ErasureTombstone) and entry.kind == "account" and entry.user_id == user_id
    ]
    assert len(account_entries) == 1
    assert account_entries[0].job_ids == [pre_row_job_id]

    report = reconcile_erasure_journal(
        db=db,
        data_dir=tmp_path,
        journal=journal,
    )

    assert report.account_events == 1
    assert not (tmp_path / "uploads" / f"{pre_row_job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / pre_row_job_id).exists()
    assert get_workspace_owner(data_dir=tmp_path, job_id=pre_row_job_id) is None
    assert (tmp_path / "uploads" / f"{unknown_orphan_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / unknown_orphan_id / "private.txt").is_file()
    with db.session() as session:
        assert session.get(DbUser, user_id) is None
