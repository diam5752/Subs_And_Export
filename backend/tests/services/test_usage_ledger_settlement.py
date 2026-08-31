from __future__ import annotations

from backend.tests.services.usage_ledger_test_support import (
    Barrier,
    Database,
    DbProviderBudgetReservation,
    DbUsageLedger,
    PointsStore,
    ThreadPoolExecutor,
    UsageLedgerStore,
    _seed_job,
    _seed_user,
    make_idempotency_id,
    pytest,
    uuid,
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
    assert (
        ledger_store.finalize(
            reservation,
            credits_charged=30,
            cost_usd=0.01,
            units={"audio_seconds": 120},
        )
        == starting_balance - 30
    )

    assert (
        ledger_store.fail_job_reservations(
            job_id,
            error="renderer failed",
        )
        == 1
    )
    assert points_store.get_balance(user_id) == starting_balance
    assert (
        ledger_store.fail_job_reservations(
            job_id,
            error="renderer failed",
        )
        == 1
    )
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
    assert (
        ledger_store.fail(
            reservation,
            status="failed",
            error="legacy crash",
        )
        == starting_balance
    )


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
