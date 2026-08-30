from __future__ import annotations

from backend.tests.services.usage_ledger_test_support import (
    Barrier,
    Database,
    DbPointTransaction,
    DbProviderBudgetReservation,
    DbUsageLedger,
    PointsStore,
    Session,
    ThreadPoolExecutor,
    UsageLedgerStore,
    _seed_job,
    _seed_user,
    make_idempotency_id,
    pytest,
    select,
    uuid,
)


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

    assert (
        ledger_store.reconcile_stale_reservations(
            stale_before=101,
        )
        == 0
    )
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
        assert (
            session.scalar(
                select(DbUsageLedger).where(
                    DbUsageLedger.idempotency_key == idempotency_key,
                )
            )
            is None
        )
        budget = session.get(
            DbProviderBudgetReservation,
            idempotency_key,
        )
        assert budget is not None
        assert budget.status == "reserved"
        budget.updated_at = 100

    assert (
        ledger_store.reconcile_stale_reservations(
            stale_before=101,
        )
        == 1
    )
    assert points_store.get_balance(user_id) == starting_balance
    assert (
        ledger_store.reconcile_stale_reservations(
            stale_before=101,
        )
        == 0
    )
    with db.session() as session:
        assert (
            session.get(
                DbPointTransaction,
                make_idempotency_id(
                    "refund",
                    legacy_ledger_id,
                    "stale_orphan",
                ),
            )
            is None
        )
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
        assert (
            session.scalar(
                select(DbUsageLedger).where(
                    DbUsageLedger.idempotency_key == idempotency_key,
                )
            )
            is None
        )
        assert (
            session.get(
                DbProviderBudgetReservation,
                idempotency_key,
            )
            is None
        )


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
    assert (
        ledger_store.finalize(
            reservation,
            credits_charged=30,
            cost_usd=0.02,
            units={},
        )
        == starting_balance
    )
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

    original_finalize = ledger_store.provider_budget_store.finalize_in_session
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

    assert (
        ledger_store.fail(
            reservation,
            status="failed",
            error="timeout",
        )
        == starting_balance
    )
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
