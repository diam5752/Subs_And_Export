from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.database import Database
from backend.app.db.models import (
    DbJob,
    DbPointTransaction,
    DbProviderBudgetReservation,
    DbUsageLedger,
    DbUser,
)
from backend.app.services.points import PointsStore, make_idempotency_id
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
    points_store.credit(
        user_id,
        200,
        reason="test_paid_funding",
        paid_credit_delta=200,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"reserve-roundtrip-{uuid.uuid4().hex[:8]}"

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
        idempotency_key=idempotency_key,
        endpoint="audio/transcriptions",
    )
    assert reservation.reserved_credits == 30
    assert balance == starting_balance - 30

    final_balance = ledger_store.finalize(
        reservation,
        credits_charged=20,
        cost_usd=0.02,
        units={"audio_seconds": 60},
        result={"text": "replay-safe"},
    )
    assert final_balance == starting_balance - 25
    assert ledger_store.get_finalized_result(reservation) == {
        "text": "replay-safe",
    }

    retry, retry_balance = ledger_store.reserve(
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
        idempotency_key=idempotency_key,
        endpoint="audio/transcriptions",
    )
    assert retry.ledger_id == reservation.ledger_id
    assert retry_balance == starting_balance - 25
    assert ledger_store.mark_dispatched(retry) is False

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
    points_store.credit(
        user_id,
        200,
        reason="test_paid_funding",
        paid_credit_delta=200,
    )
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


def test_terminal_refund_allows_one_serialized_paid_retry() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-retry-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        200,
        reason="test_paid_funding",
        paid_credit_delta=200,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"retry-root-{uuid.uuid4().hex[:8]}"

    def reserve() -> tuple[str, str, int]:
        reservation, balance = ledger_store.reserve(
            user_id=user_id,
            job_id=job_id,
            action="caption_reprocess",
            provider="elevenlabs",
            model="scribe_v2",
            tier="standard",
            credits=30,
            min_credits=10,
            cost_estimate_usd=0.02,
            units={"audio_seconds": 30},
            idempotency_key=idempotency_key,
            allow_terminal_retry=True,
        )
        return (
            reservation.ledger_id,
            reservation.idempotency_key,
            balance,
        )

    def reservation_for(
        ledger_id: str,
        reservation_key: str,
    ):
        with db.session() as session:
            ledger = session.get(DbUsageLedger, ledger_id)
            assert ledger is not None
            return ledger_store._reservation_from_ledger(
                ledger,
                idempotency_key=reservation_key,
            )

    first_id, first_key, first_balance = reserve()
    assert first_key == idempotency_key
    assert first_balance == starting_balance - 30
    assert ledger_store.fail(
        reservation_for(first_id, first_key),
        status="failed",
        error="provider unavailable",
    ) == starting_balance

    retry_id, retry_key, retry_balance = reserve()
    assert retry_id != first_id
    assert retry_key != first_key
    assert retry_balance == starting_balance - 30
    assert ledger_store.fail(
        reservation_for(retry_id, retry_key),
        status="failed",
        error="provider unavailable again",
    ) == starting_balance

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(
            executor.map(lambda _index: reserve(), range(2))
        )

    assert concurrent[0] == concurrent[1]
    final_id, final_key, final_balance = concurrent[0]
    assert final_id not in {first_id, retry_id}
    assert final_key not in {first_key, retry_key}
    assert final_balance == starting_balance - 30
    final = reservation_for(final_id, final_key)
    assert ledger_store.mark_dispatched(final) is True
    assert ledger_store.finalize(
        final,
        credits_charged=20,
        cost_usd=0.01,
        units={"prompt_tokens": 20},
    ) == starting_balance - 20

    replay_id, replay_key, replay_balance = reserve()
    assert (replay_id, replay_key) == (final_id, final_key)
    assert replay_balance == starting_balance - 20

    with db.session() as session:
        ledgers = list(
            session.scalars(
                select(DbUsageLedger).where(
                    DbUsageLedger.user_id == user_id,
                    DbUsageLedger.action == "caption_reprocess",
                )
            ).all()
        )
        assert len(ledgers) == 3
        attempts = sorted(
            int((ledger.units or {}).get("retry_attempt", -1))
            for ledger in ledgers
        )
        assert attempts == [0, 1, 2]


def test_usage_reservation_rolls_back_every_surface_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash before ledger persistence must not orphan a paid debit."""
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-atomic-reserve-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"atomic-reserve-{uuid.uuid4().hex[:8]}"
    debit_id = make_idempotency_id("reserve", idempotency_key)
    ledger_id = make_idempotency_id("ledger", idempotency_key)
    original_reserve = (
        ledger_store.provider_budget_store.reserve_in_session
    )

    def interrupt_after_budget_reservation(
        session: Session,
        **kwargs: Any,
    ) -> object:
        original_reserve(session, **kwargs)
        raise RuntimeError("simulated crash before ledger persistence")

    monkeypatch.setattr(
        ledger_store.provider_budget_store,
        "reserve_in_session",
        interrupt_after_budget_reservation,
    )
    with pytest.raises(RuntimeError, match="before ledger persistence"):
        ledger_store.reserve(
            user_id=user_id,
            job_id=job_id,
            action="transcription",
            provider="elevenlabs",
            model="scribe_v2",
            tier="standard",
            credits=30,
            min_credits=30,
            cost_estimate_usd=0.02,
            units={"audio_seconds": 120},
            idempotency_key=idempotency_key,
        )

    assert points_store.get_balance(user_id) == starting_balance
    with db.session() as session:
        assert session.get(DbPointTransaction, debit_id) is None
        assert session.get(DbUsageLedger, ledger_id) is None
        assert (
            session.get(
                DbProviderBudgetReservation,
                idempotency_key,
            )
            is None
        )

    monkeypatch.setattr(
        ledger_store.provider_budget_store,
        "reserve_in_session",
        original_reserve,
    )
    reservation, balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 120},
        idempotency_key=idempotency_key,
    )

    assert reservation.ledger_id == ledger_id
    assert balance == starting_balance - 30
    with db.session() as session:
        assert session.get(DbPointTransaction, debit_id) is not None
        assert session.get(DbUsageLedger, ledger_id) is not None
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "reserved"


def test_usage_reservation_rejects_terminal_orphan_budget() -> None:
    """A legacy settled budget key cannot authorize another provider call."""
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-terminal-budget-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"terminal-budget-{uuid.uuid4().hex[:8]}"
    guarded_estimate = 0.02 * 1.25
    ledger_store.provider_budget_store.reserve(
        idempotency_key=idempotency_key,
        estimated_usd=guarded_estimate,
        daily_limit_usd=1.0,
        monthly_limit_usd=2.0,
    )
    ledger_store.provider_budget_store.release(idempotency_key)

    with pytest.raises(
        RuntimeError,
        match="Provider budget idempotency key is settled",
    ):
        ledger_store.reserve(
            user_id=user_id,
            job_id=job_id,
            action="transcription",
            provider="elevenlabs",
            model="scribe_v2",
            tier="standard",
            credits=30,
            min_credits=30,
            cost_estimate_usd=0.02,
            units={"audio_seconds": 120},
            idempotency_key=idempotency_key,
        )

    assert points_store.get_balance(user_id) == starting_balance
    with db.session() as session:
        assert (
            session.get(
                DbPointTransaction,
                make_idempotency_id("reserve", idempotency_key),
            )
            is None
        )
        assert session.scalar(
            select(DbUsageLedger).where(
                DbUsageLedger.idempotency_key == idempotency_key,
            )
        ) is None
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "released"


def test_stale_orphan_budget_refunds_exact_outstanding_debit_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Debit compensation and budget release must commit as one operation."""
    db = Database()
    user_id = _seed_user(db)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balances = points_store.get_balances(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"stale-orphan-{uuid.uuid4().hex[:8]}"
    ledger_id = make_idempotency_id("ledger", idempotency_key)
    reserve_tx_id = make_idempotency_id(
        "reserve",
        idempotency_key,
    )
    points_store.spend_once(
        user_id,
        30,
        reason="transcription",
        transaction_id=reserve_tx_id,
        meta={
            "ledger_id": ledger_id,
            "action": "transcription",
            "kind": "reserve",
        },
        require_paid=True,
    )
    points_store.refund_once(
        user_id,
        7,
        original_reason="transcription",
        transaction_id=make_idempotency_id(
            "refund",
            ledger_id,
            "partial",
        ),
        meta={
            "ledger_id": ledger_id,
            "action": "transcription",
            "kind": "partial",
        },
        paid_credit_delta=7,
    )
    ledger_store.provider_budget_store.reserve(
        idempotency_key=idempotency_key,
        estimated_usd=0.02 * 1.25,
        daily_limit_usd=1.0,
        monthly_limit_usd=2.0,
    )
    with db.session() as session:
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        budget.updated_at = 100

    orphan_refund_id = make_idempotency_id(
        "refund",
        ledger_id,
        "stale_orphan",
    )
    original_release = (
        ledger_store.provider_budget_store.release_in_session
    )

    def interrupt_after_release(
        session: Session,
        budget_key: str,
    ) -> None:
        original_release(session, budget_key)
        raise RuntimeError("simulated orphan settlement crash")

    monkeypatch.setattr(
        ledger_store.provider_budget_store,
        "release_in_session",
        interrupt_after_release,
    )
    with pytest.raises(
        RuntimeError,
        match="simulated orphan settlement crash",
    ):
        ledger_store.reconcile_stale_reservations(
            stale_before=101,
        )

    interrupted_balances = points_store.get_balances(user_id)
    assert interrupted_balances.balance == starting_balances.balance - 23
    assert (
        interrupted_balances.paid_balance
        == starting_balances.paid_balance - 23
    )
    with db.session() as session:
        assert session.get(
            DbPointTransaction,
            orphan_refund_id,
        ) is None
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "reserved"

    monkeypatch.setattr(
        ledger_store.provider_budget_store,
        "release_in_session",
        original_release,
    )
    assert ledger_store.reconcile_stale_reservations(
        stale_before=101,
    ) == 1
    assert points_store.get_balances(user_id) == starting_balances
    assert ledger_store.reconcile_stale_reservations(
        stale_before=101,
    ) == 0
    with db.session() as session:
        refund = session.get(
            DbPointTransaction,
            orphan_refund_id,
        )
        assert refund is not None
        assert refund.delta == 23
        assert refund.paid_delta == 23
        assert refund.reason == "refund_transcription"
        assert refund.meta == {
            "ledger_id": ledger_id,
            "action": "transcription",
            "kind": "stale_orphan",
        }
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "released"


def test_stale_orphan_rechecks_ledger_after_budget_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent atomic reserve must keep its newly claimed budget."""
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-orphan-race-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"orphan-race-{uuid.uuid4().hex[:8]}"
    ledger_id = make_idempotency_id("ledger", idempotency_key)
    reserve_tx_id = make_idempotency_id("reserve", idempotency_key)
    ledger_store.provider_budget_store.reserve(
        idempotency_key=idempotency_key,
        estimated_usd=0.02 * 1.25,
        daily_limit_usd=1.0,
        monthly_limit_usd=2.0,
    )
    with db.session() as session:
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        budget.updated_at = 100

    original_scalar = Session.scalar
    injected = False

    def inject_concurrent_reserve(session, statement, *args, **kwargs):
        nonlocal injected
        statement_text = str(statement)
        if (
            not injected
            and getattr(statement, "_for_update_arg", None) is not None
            and "provider_budget_reservations" in statement_text
        ):
            injected = True
            with db.session() as concurrent:
                points_store.spend_once_in_session(
                    concurrent,
                    user_id,
                    30,
                    reason="transcription",
                    transaction_id=reserve_tx_id,
                    meta={
                        "ledger_id": ledger_id,
                        "action": "transcription",
                        "kind": "reserve",
                    },
                    require_paid=True,
                )
                concurrent.add(
                    DbUsageLedger(
                        id=ledger_id,
                        user_id=user_id,
                        job_id=job_id,
                        action="transcription",
                        provider="elevenlabs",
                        endpoint=None,
                        model="scribe_v2",
                        tier="standard",
                        units={},
                        cost_usd=0.02,
                        credits_reserved=30,
                        paid_credits_reserved=30,
                        credits_charged=0,
                        min_credits=30,
                        currency="USD",
                        status="reserved",
                        error=None,
                        idempotency_key=idempotency_key,
                        created_at=101,
                        updated_at=101,
                    )
                )
        return original_scalar(session, statement, *args, **kwargs)

    monkeypatch.setattr(Session, "scalar", inject_concurrent_reserve)

    assert ledger_store.reconcile_stale_reservations(
        stale_before=101,
    ) == 0
    assert injected is True
    with db.session() as session:
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "reserved"
        assert session.get(DbUsageLedger, ledger_id) is not None
        assert session.get(DbPointTransaction, reserve_tx_id) is not None


def test_legacy_compensated_debit_cannot_authorize_free_dispatch() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-compensated-debit-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"compensated-debit-{uuid.uuid4().hex[:8]}"
    debit_id = make_idempotency_id("reserve", idempotency_key)
    legacy_ledger_id = uuid.uuid4().hex
    points_store.spend_once(
        user_id,
        30,
        reason="transcription",
        transaction_id=debit_id,
        meta={
            "ledger_id": legacy_ledger_id,
            "action": "transcription",
            "kind": "reserve",
        },
        require_paid=True,
    )
    points_store.refund_once(
        user_id,
        30,
        original_reason="transcription",
        transaction_id=make_idempotency_id(
            "refund",
            legacy_ledger_id,
            "reserve",
        ),
        meta={
            "ledger_id": legacy_ledger_id,
            "action": "transcription",
            "kind": "reserve_refund",
        },
        paid_credit_delta=30,
    )
    ledger_store.provider_budget_store.reserve(
        idempotency_key=idempotency_key,
        estimated_usd=0.02 * 1.25,
        daily_limit_usd=1.0,
        monthly_limit_usd=2.0,
    )

    with pytest.raises(
        RuntimeError,
        match="Existing usage debit is not outstanding",
    ):
        ledger_store.reserve(
            user_id=user_id,
            job_id=job_id,
            action="transcription",
            provider="elevenlabs",
            model="scribe_v2",
            tier="standard",
            credits=30,
            min_credits=30,
            cost_estimate_usd=0.02,
            units={"audio_seconds": 120},
            idempotency_key=idempotency_key,
        )

    assert points_store.get_balance(user_id) == starting_balance
    with db.session() as session:
        assert session.scalar(
            select(DbUsageLedger).where(
                DbUsageLedger.idempotency_key == idempotency_key,
            )
        ) is None
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "reserved"
        budget.updated_at = 100

    assert ledger_store.reconcile_stale_reservations(
        stale_before=101,
    ) == 1
    assert points_store.get_balance(user_id) == starting_balance
    assert ledger_store.reconcile_stale_reservations(
        stale_before=101,
    ) == 0
    with db.session() as session:
        assert session.get(
            DbPointTransaction,
            make_idempotency_id(
                "refund",
                legacy_ledger_id,
                "stale_orphan",
            ),
        ) is None
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "released"


def test_provider_dispatch_is_claimed_by_exactly_one_worker() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-dispatch-claim-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 120},
        idempotency_key=f"dispatch-claim-{uuid.uuid4().hex[:8]}",
    )
    barrier = Barrier(2)

    def claim() -> bool:
        barrier.wait()
        return ledger_store.mark_dispatched(reservation)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _: claim(), range(2)))

    assert results == [False, True]
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.status == "dispatched"


@pytest.mark.parametrize(
    "cost_estimate_usd",
    [float("nan"), float("inf"), float("-inf"), -0.01],
)
def test_usage_ledger_rejects_invalid_provider_estimate_before_mutation(
    cost_estimate_usd: float,
) -> None:
    # REGRESSION: max(0, NaN/negative) could turn an external paid operation
    # into a zero-cost reservation that bypassed paid credits and hard budgets.
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-invalid-estimate-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    idempotency_key = f"invalid-estimate-{uuid.uuid4().hex[:8]}"

    with pytest.raises(ValueError, match="finite and non-negative"):
        ledger_store.reserve(
            user_id=user_id,
            job_id=job_id,
            action="transcription",
            provider="elevenlabs",
            model="scribe_v2",
            tier="standard",
            credits=30,
            min_credits=30,
            cost_estimate_usd=cost_estimate_usd,
            units={"audio_seconds": 120},
            idempotency_key=idempotency_key,
        )

    assert points_store.get_balance(user_id) == starting_balance
    with db.session() as session:
        assert session.scalar(
            select(DbUsageLedger).where(
                DbUsageLedger.idempotency_key == idempotency_key,
            )
        ) is None
        assert session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        ) is None


def test_usage_ledger_refund_if_reserved() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-refund-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        200,
        reason="test_paid_funding",
        paid_credit_delta=200,
    )
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


def test_usage_ledger_refunds_after_provider_dispatch_and_keeps_provider_cost() -> None:
    # REGRESSION: a failed external service must not charge the customer even
    # when the provider request may already have consumed operator budget.
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-dispatched-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 120},
        idempotency_key=f"dispatch-{uuid.uuid4().hex[:8]}",
    )

    ledger_store.mark_dispatched(reservation)
    balance = ledger_store.fail(reservation, status="failed", error="timeout")
    assert balance == starting_balance
    assert ledger_store.fail(reservation, status="failed") == starting_balance
    assert ledger_store.finalize(
        reservation,
        credits_charged=30,
        cost_usd=0.02,
        units={},
    ) == starting_balance
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.status == "failed"
        assert ledger.credits_charged == 0
        budget = session.get(
            DbProviderBudgetReservation,
            reservation.idempotency_key,
        )
        assert budget is not None
        assert budget.status == "finalized"
        assert budget.actual_usd == pytest.approx(
            reservation.estimated_cost_usd * 1.25,
        )


def test_dispatched_failure_recovers_after_refund_before_final_settlement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash after refund must resume without a second wallet credit."""
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-failure-recovery-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 120},
        idempotency_key=f"failure-recovery-{uuid.uuid4().hex[:8]}",
    )
    ledger_store.mark_dispatched(reservation)

    original_finalize = (
        ledger_store.provider_budget_store.finalize_in_session
    )
    finalize_attempts = 0

    def interrupt_first_finalize(
        session: Session,
        idempotency_key: str,
        *,
        actual_usd: float,
    ) -> None:
        nonlocal finalize_attempts
        finalize_attempts += 1
        if finalize_attempts == 1:
            raise RuntimeError("simulated crash after wallet refund")
        original_finalize(
            session,
            idempotency_key,
            actual_usd=actual_usd,
        )

    monkeypatch.setattr(
        ledger_store.provider_budget_store,
        "finalize_in_session",
        interrupt_first_finalize,
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        ledger_store.fail(reservation, status="failed", error="timeout")

    assert points_store.get_balance(user_id) == starting_balance - 30
    with db.session() as session:
        interrupted = session.get(DbUsageLedger, reservation.ledger_id)
        assert interrupted is not None
        assert interrupted.status == "dispatched"
        budget = session.get(
            DbProviderBudgetReservation,
            reservation.idempotency_key,
        )
        assert budget is not None
        assert budget.status == "reserved"

    assert ledger_store.fail(
        reservation,
        status="failed",
        error="timeout",
    ) == starting_balance
    with db.session() as session:
        settled = session.get(DbUsageLedger, reservation.ledger_id)
        assert settled is not None
        assert settled.status == "failed"
        assert settled.credits_charged == 0
        budget = session.get(
            DbProviderBudgetReservation,
            reservation.idempotency_key,
        )
        assert budget is not None
        assert budget.status == "finalized"
        assert budget.actual_usd == pytest.approx(
            reservation.estimated_cost_usd * 1.25,
        )


def test_failed_job_compensates_already_finalized_transcription() -> None:
    """A later job failure refunds the exact settled customer charge."""
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-post-stt-failure-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        200,
        reason="test_paid_funding",
        paid_credit_delta=200,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=100,
        min_credits=30,
        cost_estimate_usd=0.04,
        units={"audio_seconds": 600},
        idempotency_key=f"post-stt-failure-{uuid.uuid4().hex[:8]}",
    )
    ledger_store.mark_dispatched(reservation)
    assert ledger_store.finalize(
        reservation,
        credits_charged=30,
        cost_usd=0.01,
        units={"audio_seconds": 120},
    ) == starting_balance - 30

    assert ledger_store.fail_job_reservations(
        job_id,
        error="renderer failed",
    ) == 1
    assert points_store.get_balance(user_id) == starting_balance
    assert ledger_store.fail_job_reservations(
        job_id,
        error="renderer failed",
    ) == 1
    assert points_store.get_balance(user_id) == starting_balance
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.status == "failed"
        assert ledger.credits_charged == 0
        assert ledger.cost_usd == pytest.approx(0.01)
        assert ledger.units is not None
        assert ledger.units["failure_refunded_credits"] == 30
        budget = session.get(
            DbProviderBudgetReservation,
            reservation.idempotency_key,
        )
        assert budget is not None
        assert budget.status == "finalized"
        assert budget.actual_usd == pytest.approx(0.01)


def test_stale_dispatched_reservation_is_reconciled_once() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-stale-dispatch-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 120},
        idempotency_key=f"stale-dispatch-{uuid.uuid4().hex[:8]}",
    )
    assert ledger_store.mark_dispatched(reservation)
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        ledger.updated_at = 100

    assert ledger_store.reconcile_stale_reservations(
        stale_before=101,
    ) == 1
    assert points_store.get_balance(user_id) == starting_balance
    assert ledger_store.reconcile_stale_reservations(
        stale_before=101,
    ) == 0
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.status == "failed"
        assert ledger.credits_charged == 0
        budget = session.get(
            DbProviderBudgetReservation,
            reservation.idempotency_key,
        )
        assert budget is not None
        assert budget.status == "finalized"
        assert budget.actual_usd == pytest.approx(0.02 * 1.25)


def test_legacy_partial_finalization_refunds_only_outstanding_charge() -> None:
    """Recover an old split transaction without refunding more than was spent."""
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-legacy-finalizing-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        200,
        reason="test_paid_funding",
        paid_credit_delta=200,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=100,
        min_credits=30,
        cost_estimate_usd=0.04,
        units={"audio_seconds": 600},
        idempotency_key=f"legacy-finalizing-{uuid.uuid4().hex[:8]}",
    )
    ledger_store.mark_dispatched(reservation)
    adjustment_id = make_idempotency_id(
        "refund",
        reservation.ledger_id,
        "70",
    )
    points_store.refund_once(
        user_id,
        70,
        original_reason=reservation.action,
        transaction_id=adjustment_id,
        meta={
            "ledger_id": reservation.ledger_id,
            "action": reservation.action,
            "kind": "adjustment",
        },
        paid_credit_delta=70,
    )
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        ledger.status = "finalizing"

    assert points_store.get_balance(user_id) == starting_balance - 30
    assert ledger_store.fail(
        reservation,
        status="failed",
        error="legacy crash",
    ) == starting_balance


def test_terminal_finalize_retry_repairs_stranded_provider_budget() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-budget-repair-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 120},
        idempotency_key=f"budget-repair-{uuid.uuid4().hex[:8]}",
    )
    ledger_store.mark_dispatched(reservation)
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        ledger.status = "finalized"
        ledger.credits_charged = 30
        ledger.cost_usd = 0.01

    ledger_store.finalize(
        reservation,
        credits_charged=30,
        cost_usd=0.01,
        units={"audio_seconds": 120},
    )
    with db.session() as session:
        budget = session.get(
            DbProviderBudgetReservation,
            reservation.idempotency_key,
        )
        assert budget is not None
        assert budget.status == "finalized"
        assert budget.actual_usd == pytest.approx(0.01)


def test_concurrent_finalize_and_failure_settle_to_one_refund() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-settlement-race-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="elevenlabs",
        model="scribe_v2",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={"audio_seconds": 120},
        idempotency_key=f"settlement-race-{uuid.uuid4().hex[:8]}",
    )
    ledger_store.mark_dispatched(reservation)
    barrier = Barrier(2)

    def finalize() -> int:
        barrier.wait()
        return ledger_store.finalize(
            reservation,
            credits_charged=30,
            cost_usd=0.02,
            units={"audio_seconds": 120},
        )

    def fail() -> int:
        barrier.wait()
        return ledger_store.fail(
            reservation,
            status="failed",
            error="job failed",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            executor.submit(finalize),
            executor.submit(fail),
        ]
        for result in results:
            result.result(timeout=10)

    assert points_store.get_balance(user_id) == starting_balance
    with db.session() as session:
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert ledger is not None
        assert ledger.status == "failed"
        assert ledger.credits_charged == 0


def test_included_provider_reservation_tracks_cost_without_hidden_credit_charge() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"job-included-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        100,
        reason="test_paid_funding",
        paid_credit_delta=100,
    )
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    parent, balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.02,
        units={},
        idempotency_key=f"parent-{uuid.uuid4().hex[:8]}",
    )
    included, included_balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="social_copy",
        provider="openai",
        model="legacy-text-model",
        tier="standard",
        credits=0,
        min_credits=0,
        cost_estimate_usd=0.01,
        units={},
        idempotency_key=f"included-{uuid.uuid4().hex[:8]}",
        covered_by_ledger_id=parent.ledger_id,
    )
    assert included_balance == balance
    ledger_store.mark_dispatched(included)
    final_balance = ledger_store.finalize(
        included,
        credits_charged=999,
        cost_usd=0.008,
        units={"tokens": 100},
    )
    assert final_balance == balance
    with db.session() as session:
        ledger = session.get(DbUsageLedger, included.ledger_id)
        assert ledger is not None
        assert ledger.credits_charged == 0
        assert ledger.cost_usd == pytest.approx(0.008)


def test_usage_ledger_summarize_groups(monkeypatch) -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id_one = f"job-day-one-{uuid.uuid4().hex[:8]}"
    job_id_two = f"job-day-two-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id_one)
    _seed_job(db, user_id, job_id_two)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(
        user_id,
        200,
        reason="test_paid_funding",
        paid_credit_delta=200,
    )
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

    total_cost = ledger_store.total_cost_usd(start_ts=day_one - 1, end_ts=day_two + 1)
    assert total_cost >= 0.03


def test_usage_ledger_total_cost_rejects_inverted_range() -> None:
    db = Database()
    ledger_store = UsageLedgerStore(db=db, points_store=PointsStore(db=db))

    with pytest.raises(ValueError, match="start_ts must be <= end_ts"):
        ledger_store.total_cost_usd(start_ts=2, end_ts=1)
