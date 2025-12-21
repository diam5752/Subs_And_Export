from __future__ import annotations

import time
import uuid

from backend.app.core.database import Database
from backend.app.db.models import DbJob, DbUsageLedger, DbUser
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import UsageLedgerStore


def _seed_user(db: Database) -> str:
    user_id = uuid.uuid4().hex
    with db.session() as session:
        session.add(
            DbUser(
                id=user_id,
                email=f"{user_id}@example.com",
                name="Ledger",
                provider="local",
                password_hash="x",
                google_sub=None,
                created_at="now",
            )
        )
    return user_id


def _seed_job(db: Database, user_id: str, job_id: str) -> str:
    now = int(time.time())
    with db.session() as session:
        session.add(
            DbJob(
                id=job_id,
                user_id=user_id,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
    return job_id


def test_usage_ledger_reserve_finalize_refund_roundtrip() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-roundtrip-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    reservation, balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=30,
        min_credits=25,
        cost_estimate_usd=0.03,
        units={"audio_seconds": 60},
        idempotency_key=f"reserve-roundtrip-{uuid.uuid4().hex[:8]}",
        endpoint="audio/transcriptions",
    )
    assert reservation.reserved_credits == 30
    assert balance == starting_balance - 30

    final_balance = ledger_store.finalize(
        reservation,
        credits_charged=20,
        cost_usd=0.02,
        units={"audio_seconds": 60},
    )
    assert final_balance == starting_balance - 25

    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.credits_reserved == 30
        assert ledger.credits_charged == 25
        assert ledger.status == "finalized"


def test_usage_ledger_reserve_is_idempotent() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-idempotent-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    idempotency_key = f"reserve-idempotent-{uuid.uuid4().hex[:8]}"
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    reservation, balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=25,
        min_credits=25,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 30},
        idempotency_key=idempotency_key,
        endpoint="audio/transcriptions",
    )
    assert balance == starting_balance - 25

    again, balance_again = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=25,
        min_credits=25,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 30},
        idempotency_key=idempotency_key,
        endpoint="audio/transcriptions",
    )
    assert again.ledger_id == reservation.ledger_id
    assert balance_again == starting_balance - 25


def test_usage_ledger_refund_if_reserved() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-refund-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=25,
        min_credits=25,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 30},
        idempotency_key=f"reserve-refund-{uuid.uuid4().hex[:8]}",
        endpoint="audio/transcriptions",
    )
    assert points_store.get_balance(user_id) == starting_balance - 25

    balance = ledger_store.refund_if_reserved(reservation, status="failed", error="boom")
    assert balance == starting_balance

    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.status == "failed"


def test_usage_ledger_summarize_groups(monkeypatch) -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id_one = f"job-day-one-{uuid.uuid4().hex[:8]}"
    job_id_two = f"job-day-two-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id_one)
    _seed_job(db, user_id, job_id_two)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    day_one = 1_700_000_000
    day_two = day_one + 86_400

    monkeypatch.setattr("backend.app.services.usage_ledger.time.time", lambda: day_one)
    reservation_one, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id_one,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=25,
        min_credits=25,
        cost_estimate_usd=0.01,
        units={"audio_seconds": 30},
        idempotency_key=f"summary-1-{uuid.uuid4().hex[:8]}",
        endpoint="audio/transcriptions",
    )
    ledger_store.finalize(reservation_one, credits_charged=25, cost_usd=0.01, units={})

    monkeypatch.setattr("backend.app.services.usage_ledger.time.time", lambda: day_two)
    reservation_two, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id_two,
        action="social_copy",
        provider="openai",
        model="gpt-4o-mini",
        tier="standard",
        credits=10,
        min_credits=10,
        cost_estimate_usd=0.02,
        units={"prompt_tokens": 100, "completion_tokens": 50},
        idempotency_key=f"summary-2-{uuid.uuid4().hex[:8]}",
        endpoint="chat/completions",
    )
    ledger_store.finalize(reservation_two, credits_charged=10, cost_usd=0.02, units={})

    summary_day = ledger_store.summarize(start_ts=day_one - 1, end_ts=day_two + 1, group_by="day")
    assert len(summary_day) >= 2  # May have more from previous test runs

    # Use group_by=user to isolate this test's data
    summary_user = ledger_store.summarize(start_ts=day_one - 1, end_ts=day_two + 1, group_by="user")
    user_map = {row.bucket: row for row in summary_user}
    assert user_id in user_map
    # Our test user should have 25 + 10 = 35 credits charged
    assert user_map[user_id].credits_charged == 35
