from __future__ import annotations

from backend.tests.services.usage_ledger_test_support import (
    Any,
    Database,
    DbJob,
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


def test_usage_result_and_mobile_job_complete_in_one_transaction() -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"mobile-atomic-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(user_id, 30, reason="mobile_test")
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, _balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="mock",
        model="mock-caption-v1",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.0,
        units={"audio_seconds": 10.0},
        idempotency_key=f"mobile-atomic-{uuid.uuid4().hex}",
    )
    result = {"request_id": job_id, "cues": [{"text": "ΓΕΙΑ"}]}

    ledger_store.finalize(
        reservation,
        credits_charged=30,
        cost_usd=0.0,
        units={"client": "ios"},
        result=result,
        job_status="completed",
        job_result_data={"kind": "mobile_transcription"},
    )

    with db.session() as session:
        job = session.get(DbJob, job_id)
        ledger = session.get(DbUsageLedger, reservation.ledger_id)
        assert job is not None and job.status == "completed"
        assert job.progress == 100
        assert job.result_data == {"kind": "mobile_transcription"}
        assert ledger is not None and ledger.status == "finalized"
    assert ledger_store.get_finalized_result(reservation) == result


@pytest.mark.parametrize(
    ("job_status", "result", "message"),
    [
        (
            "failed",
            {"request_id": "invalid-status"},
            "supports only completed jobs",
        ),
        (
            "completed",
            None,
            "requires a replay-safe result",
        ),
    ],
)
def test_atomic_job_finalize_rejects_inconsistent_replay_evidence(
    job_status: str,
    result: dict[str, Any] | None,
    message: str,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    job_id = f"mobile-invalid-finalize-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    points_store.ensure_account(user_id)
    points_store.credit(user_id, 30, reason="mobile_validation_test")
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)
    reservation, reserved_balance = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="mock",
        model="mock-caption-v1",
        tier="standard",
        credits=30,
        min_credits=30,
        cost_estimate_usd=0.0,
        units={"audio_seconds": 10.0},
        idempotency_key=f"mobile-invalid-finalize-{uuid.uuid4().hex}",
    )

    with pytest.raises(ValueError, match=message):
        ledger_store.finalize(
            reservation,
            credits_charged=30,
            cost_usd=0.0,
            units={"client": "ios"},
            result=result,
            job_status=job_status,
        )

    assert points_store.get_balance(user_id) == reserved_balance


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
    assert (
        ledger_store.fail(
            reservation_for(first_id, first_key),
            status="failed",
            error="provider unavailable",
        )
        == starting_balance
    )

    retry_id, retry_key, retry_balance = reserve()
    assert retry_id != first_id
    assert retry_key != first_key
    assert retry_balance == starting_balance - 30
    assert (
        ledger_store.fail(
            reservation_for(retry_id, retry_key),
            status="failed",
            error="provider unavailable again",
        )
        == starting_balance
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent = list(executor.map(lambda _index: reserve(), range(2)))

    assert concurrent[0] == concurrent[1]
    final_id, final_key, final_balance = concurrent[0]
    assert final_id not in {first_id, retry_id}
    assert final_key not in {first_key, retry_key}
    assert final_balance == starting_balance - 30
    final = reservation_for(final_id, final_key)
    assert ledger_store.mark_dispatched(final) is True
    assert (
        ledger_store.finalize(
            final,
            credits_charged=20,
            cost_usd=0.01,
            units={"prompt_tokens": 20},
        )
        == starting_balance - 20
    )

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
        attempts = sorted(int((ledger.units or {}).get("retry_attempt", -1)) for ledger in ledgers)
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
    original_reserve = ledger_store.provider_budget_store.reserve_in_session

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
    original_release = ledger_store.provider_budget_store.release_in_session

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
    assert interrupted_balances.paid_balance == starting_balances.paid_balance - 23
    with db.session() as session:
        assert (
            session.get(
                DbPointTransaction,
                orphan_refund_id,
            )
            is None
        )
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
    assert (
        ledger_store.reconcile_stale_reservations(
            stale_before=101,
        )
        == 1
    )
    assert points_store.get_balances(user_id) == starting_balances
    assert (
        ledger_store.reconcile_stale_reservations(
            stale_before=101,
        )
        == 0
    )
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
