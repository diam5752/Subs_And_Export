from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from backend.app.core.auth import UserStore
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournal, JobTerminalStatus
from backend.app.core.workspace_ownership import (
    WorkspaceOwnershipConflictError,
    get_workspace_owner,
    record_workspace_ownership,
)
from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
    DbJob,
    DbPointTransaction,
    DbUsageLedger,
    DbUser,
)
from backend.app.services.account_erasure import ErasureReplayConflictError
from backend.app.services.erasure_reconciliation import reconcile_erasure_journal
from backend.app.services.financial_records import financial_retention_deadline
from backend.app.services.points import PointsStore, make_idempotency_id
from backend.app.services.usage_ledger import UsageLedgerStore


def _create_user(db: Database, *, label: str) -> str:
    user = UserStore(db=db).register_local_user(
        email=f"{label}-{uuid.uuid4().hex}@example.com",
        password="testpassword123",
        name=label,
    )
    return user.id


def _create_job(
    db: Database,
    *,
    job_id: str,
    user_id: str,
    status: str = "completed",
) -> None:
    now = int(time.time())
    with db.session() as session:
        session.add(
            DbJob(
                id=job_id,
                user_id=user_id,
                status=status,
                created_at=now,
                updated_at=now,
                progress=100,
                message=None,
                result_data={
                    "video_path": f"artifacts/{job_id}/processed.mp4",
                    "transcription_url": f"/static/artifacts/{job_id}/transcription.json",
                },
            ),
        )


def _create_workspace(data_dir: Path, *, job_id: str, marker: bytes) -> None:
    uploads_dir = data_dir / "uploads"
    artifact_dir = data_dir / "artifacts" / job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (uploads_dir / f"{job_id}_input.mp4").write_bytes(marker)
    (artifact_dir / "processed.mp4").write_bytes(marker)
    (artifact_dir / "transcription.json").write_text(
        '[{"start": 0, "end": 1, "text": "private transcript"}]',
        encoding="utf-8",
    )


def _create_financial_record(db: Database, *, user_id: str) -> tuple[str, str]:
    now = int(time.time())
    suffix = uuid.uuid4().hex
    purchase_id = suffix[:32]
    invoice_id = uuid.uuid4().hex
    with db.session() as session:
        session.add(
            DbCreditPurchase(
                id=purchase_id,
                user_id=user_id,
                provider="stripe",
                package_key="starter",
                credits=100,
                amount_eur_cents=100,
                currency="eur",
                idempotency_key=f"replay-{suffix}",
                checkout_session_id=f"cs_test_{suffix}",
                checkout_url=None,
                payment_intent_id=f"pi_{suffix}",
                integration_identifier="gsubs_credits_v1",
                status="paid",
                fulfilled_at=now,
                refunded_amount_cents=0,
                dispute_active=False,
                reversed_credits=0,
                reversal_debt_credits=0,
                reversed_amount_cents=0,
                snapshot={"package_key": "starter", "credits": 100},
                payment_snapshot={"payment_intent_id": f"pi_{suffix}"},
                customer_snapshot={"country": "GR"},
                tax_snapshot={"vat_rate_percent": 24},
                financial_retention_until=financial_retention_deadline(now),
                error=None,
                created_at=now,
                updated_at=now,
            ),
        )
    with db.session() as session:
        session.add(
            DbBillingInvoice(
                id=invoice_id,
                purchase_id=purchase_id,
                provider="aade_etimologio",
                document_kind="retail_service_receipt",
                document_status="issued",
                aade_document_type="11.2",
                aade_series="0",
                aade_aa=suffix[:12],
                aade_mark=f"4{suffix[:15]}",
                issued_at=now,
                recorded_by_user_id=user_id,
                recorded_at=now,
                document_snapshot={"gross_amount_cents": 100},
                financial_retention_until=financial_retention_deadline(now),
                created_at=now,
                updated_at=now,
            ),
        )
    return purchase_id, invoice_id


def test_account_replay_is_idempotent_preserves_financial_records_and_other_user(
    tmp_path: Path,
) -> None:
    db = Database()
    erased_user_id = _create_user(db, label="erased")
    other_user_id = _create_user(db, label="other")
    erased_job_id = f"erased-{uuid.uuid4().hex}"
    other_job_id = f"other-{uuid.uuid4().hex}"
    _create_job(db, job_id=erased_job_id, user_id=erased_user_id)
    _create_job(db, job_id=other_job_id, user_id=other_user_id)
    _create_workspace(tmp_path, job_id=erased_job_id, marker=b"erase")
    _create_workspace(tmp_path, job_id=other_job_id, marker=b"keep")
    purchase_id, invoice_id = _create_financial_record(db, user_id=erased_user_id)
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append(
        kind="account",
        user_id=erased_user_id,
        job_ids=[erased_job_id],
    )

    first = reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)
    second = reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)

    assert first.account_events == 1
    assert second.account_events == 1
    assert not (tmp_path / "uploads" / f"{erased_job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / erased_job_id).exists()
    assert (tmp_path / "uploads" / f"{other_job_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / other_job_id / "transcription.json").is_file()
    with db.session() as session:
        assert session.get(DbUser, erased_user_id) is None
        assert session.get(DbJob, erased_job_id) is None
        assert session.get(DbUser, other_user_id) is not None
        assert session.get(DbJob, other_job_id) is not None
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        assert purchase.user_id is None
        assert session.get(DbBillingInvoice, invoice_id) is not None


def test_workspace_replay_removes_media_but_preserves_terminal_job_row(
    tmp_path: Path,
) -> None:
    db = Database()
    user_id = _create_user(db, label="workspace")
    job_id = f"workspace-{uuid.uuid4().hex}"
    _create_job(db, job_id=job_id, user_id=user_id)
    _create_workspace(tmp_path, job_id=job_id, marker=b"erase")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append(kind="workspace", user_id=user_id, job_ids=[job_id])

    report = reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)

    assert report.workspace_events == 1
    assert not (tmp_path / "uploads" / f"{job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / job_id / "transcription.json").exists()
    with db.session() as session:
        assert session.get(DbJob, job_id) is not None


@pytest.mark.parametrize(
    ("restored_status", "terminal_status"),
    [
        ("pending", "cancelled"),
        ("processing", "cancelled"),
        # A user cancellation that reached the restored database remains
        # authoritative even if this journal snapshot only contains the
        # worker's slightly earlier failure intent.
        ("cancelling", "failed"),
    ],
)
def test_job_terminal_replay_cancels_restored_active_job_and_refunds_once(
    tmp_path: Path,
    restored_status: str,
    terminal_status: JobTerminalStatus,
) -> None:
    db = Database()
    user_id = _create_user(db, label=f"terminal-{restored_status}")
    job_id = f"terminal-{restored_status}-{uuid.uuid4().hex}"
    _create_job(
        db,
        job_id=job_id,
        user_id=user_id,
        status=restored_status,
    )
    _create_workspace(tmp_path, job_id=job_id, marker=b"erase")
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    funded_balance = points_store.credit(
        user_id,
        100,
        reason="test_restore_funding",
    )
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, reserved_balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="local",
        model="whisper",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.0,
        units={"audio_seconds": 60},
        idempotency_key=f"restore-{uuid.uuid4().hex}",
    )
    assert reserved_balance == funded_balance - 30
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append_job_terminal(
        user_id=user_id,
        job_ids=[job_id],
        terminal_status=terminal_status,
    )

    first = reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)
    first_balance = points_store.get_balance(user_id)
    second = reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)

    assert first.job_terminal_events == 1
    assert second.job_terminal_events == 1
    assert first_balance == funded_balance
    assert points_store.get_balance(user_id) == funded_balance
    assert not (tmp_path / "uploads" / f"{job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / job_id).exists()
    refund_id = make_idempotency_id("refund", reservation.ledger_id, "failed")
    with db.session() as session:
        restored_job = session.get(DbJob, job_id)
        assert restored_job is not None
        assert restored_job.status == "cancelled"
        assert restored_job.message == "Cancelled by user"
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.status == "cancelled"
        assert ledger.credits_charged == 0
        refund = session.get(DbPointTransaction, refund_id)
        assert refund is not None
        assert refund.delta == 30
        ledger_transactions = [
            transaction
            for transaction in session.scalars(
                select(DbPointTransaction).where(
                    DbPointTransaction.user_id == user_id,
                ),
            ).all()
            if isinstance(transaction.meta, dict) and transaction.meta.get("ledger_id") == reservation.ledger_id
        ]
        assert sorted(transaction.delta for transaction in ledger_transactions) == [
            -30,
            30,
        ]


@pytest.mark.parametrize(
    "terminal_statuses",
    [("failed", "cancelled"), ("cancelled", "failed")],
)
def test_job_terminal_replay_gives_cancellation_precedence_in_any_order(
    tmp_path: Path,
    terminal_statuses: tuple[JobTerminalStatus, JobTerminalStatus],
) -> None:
    db = Database()
    user_id = _create_user(db, label="terminal-precedence")
    job_id = f"terminal-precedence-{uuid.uuid4().hex}"
    _create_job(
        db,
        job_id=job_id,
        user_id=user_id,
        status="processing",
    )
    _create_workspace(tmp_path, job_id=job_id, marker=b"erase")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    for terminal_status in terminal_statuses:
        journal.append_job_terminal(
            user_id=user_id,
            job_ids=[job_id],
            terminal_status=terminal_status,
        )

    report = reconcile_erasure_journal(
        db=db,
        data_dir=tmp_path,
        journal=journal,
    )

    assert report.job_terminal_events == 2
    assert not (tmp_path / "uploads" / f"{job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / job_id).exists()
    with db.session() as session:
        restored_job = session.get(DbJob, job_id)
        assert restored_job is not None
        assert restored_job.status == "cancelled"


def test_replay_fails_closed_on_restored_ownership_conflict(tmp_path: Path) -> None:
    db = Database()
    intended_user_id = _create_user(db, label="intended")
    other_user_id = _create_user(db, label="owner")
    job_id = f"conflict-{uuid.uuid4().hex}"
    _create_job(db, job_id=job_id, user_id=other_user_id)
    _create_workspace(tmp_path, job_id=job_id, marker=b"keep")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append(kind="job", user_id=intended_user_id, job_ids=[job_id])

    with pytest.raises(ErasureReplayConflictError, match="ownership conflicts"):
        reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)

    assert (tmp_path / "uploads" / f"{job_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / job_id / "transcription.json").is_file()
    with db.session() as session:
        assert session.get(DbJob, job_id) is not None


def test_job_replay_preserves_media_when_marker_owner_conflicts_with_database(
    tmp_path: Path,
) -> None:
    db = Database()
    marker_user_id = _create_user(db, label="marker-owner")
    tombstone_user_id = _create_user(db, label="tombstone-owner")
    job_id = f"marker-conflict-{uuid.uuid4().hex}"
    _create_job(db, job_id=job_id, user_id=tombstone_user_id)
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=job_id,
        user_id=marker_user_id,
    )
    _create_workspace(tmp_path, job_id=job_id, marker=b"keep")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append(kind="job", user_id=tombstone_user_id, job_ids=[job_id])

    with pytest.raises(
        WorkspaceOwnershipConflictError,
        match="does not match the expected account",
    ):
        reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)

    assert (tmp_path / "uploads" / f"{job_id}_input.mp4").read_bytes() == b"keep"
    assert (tmp_path / "artifacts" / job_id / "processed.mp4").read_bytes() == b"keep"
    assert get_workspace_owner(data_dir=tmp_path, job_id=job_id) == marker_user_id
    with db.session() as session:
        restored_job = session.get(DbJob, job_id)
        assert restored_job is not None
        assert restored_job.user_id == tombstone_user_id


def test_account_replay_unions_restored_same_user_workspace_markers(
    tmp_path: Path,
) -> None:
    db = Database()
    user_id = _create_user(db, label="restored-marker")
    restored_job_id = f"restored-marker-{uuid.uuid4().hex}"
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=restored_job_id,
        user_id=user_id,
    )
    _create_workspace(tmp_path, job_id=restored_job_id, marker=b"erase")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append(kind="account", user_id=user_id, job_ids=[])

    report = reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)

    assert report.account_events == 1
    assert not (tmp_path / "uploads" / f"{restored_job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / restored_job_id).exists()
    assert get_workspace_owner(data_dir=tmp_path, job_id=restored_job_id) is None
    with db.session() as session:
        assert session.get(DbUser, user_id) is None


def test_ownerless_orphan_replay_preserves_owned_workspace(tmp_path: Path) -> None:
    db = Database()
    user_id = _create_user(db, label="owned-orphan")
    job_id = f"owned-orphan-{uuid.uuid4().hex}"
    record_workspace_ownership(
        data_dir=tmp_path,
        job_id=job_id,
        user_id=user_id,
    )
    _create_workspace(tmp_path, job_id=job_id, marker=b"keep")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append_orphan_workspace(job_ids=[job_id])

    with pytest.raises(
        WorkspaceOwnershipConflictError,
        match="without an expected account",
    ):
        reconcile_erasure_journal(db=db, data_dir=tmp_path, journal=journal)

    assert (tmp_path / "uploads" / f"{job_id}_input.mp4").read_bytes() == b"keep"
    assert (tmp_path / "artifacts" / job_id / "processed.mp4").read_bytes() == b"keep"
    assert get_workspace_owner(data_dir=tmp_path, job_id=job_id) == user_id


def test_provider_transcript_replay_is_idempotent_and_uses_opaque_id(
    tmp_path: Path,
) -> None:
    db = Database()
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append_provider_transcript(
        provider="elevenlabs",
        transcript_id="opaque-transcript-123",
    )
    deleted_ids: list[str] = []

    first = reconcile_erasure_journal(
        db=db,
        data_dir=tmp_path,
        journal=journal,
        provider_transcript_deleter=deleted_ids.append,
    )
    second = reconcile_erasure_journal(
        db=db,
        data_dir=tmp_path,
        journal=journal,
        provider_transcript_deleter=deleted_ids.append,
    )

    assert first.provider_transcript_events == 1
    assert second.provider_transcript_events == 1
    assert deleted_ids == ["opaque-transcript-123", "opaque-transcript-123"]


def test_provider_replay_failure_keeps_even_expired_tombstone(
    tmp_path: Path,
) -> None:
    db = Database()
    retention_days = 30
    now = 1_800_000_000
    journal = ErasureJournal(
        tmp_path / "privacy-journal",
        retention_days=retention_days,
    )
    appended = journal.append_provider_transcript(
        provider="elevenlabs",
        transcript_id="opaque-transcript-failure",
        now=now - (retention_days * 86_400) - 1,
    )

    def fail_delete(_transcript_id: str) -> None:
        raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError, match="provider unavailable"):
        reconcile_erasure_journal(
            db=db,
            data_dir=tmp_path,
            journal=journal,
            now=now,
            provider_transcript_deleter=fail_delete,
        )

    assert journal.read_all() == [appended]


def test_orphan_workspace_replay_removes_only_exact_media_and_keeps_rows(
    tmp_path: Path,
) -> None:
    db = Database()
    restored_user_id = _create_user(db, label="restored-orphan")
    other_user_id = _create_user(db, label="other-orphan")
    restored_job_id = f"restored-orphan-{uuid.uuid4().hex}"
    other_job_id = f"other-orphan-{uuid.uuid4().hex}"
    _create_job(db, job_id=restored_job_id, user_id=restored_user_id)
    _create_job(db, job_id=other_job_id, user_id=other_user_id)
    _create_workspace(tmp_path, job_id=restored_job_id, marker=b"erase")
    _create_workspace(tmp_path, job_id=other_job_id, marker=b"keep")
    journal = ErasureJournal(tmp_path / "privacy-journal", retention_days=30)
    journal.append_orphan_workspace(job_ids=[restored_job_id])

    report = reconcile_erasure_journal(
        db=db,
        data_dir=tmp_path,
        journal=journal,
    )

    assert report.orphan_workspace_events == 1
    assert not (tmp_path / "uploads" / f"{restored_job_id}_input.mp4").exists()
    assert not (tmp_path / "artifacts" / restored_job_id).exists()
    assert (tmp_path / "uploads" / f"{other_job_id}_input.mp4").is_file()
    assert (tmp_path / "artifacts" / other_job_id / "transcription.json").is_file()
    with db.session() as session:
        assert session.get(DbJob, restored_job_id) is not None
        assert session.get(DbJob, other_job_id) is not None
