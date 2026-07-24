from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select

from backend.app.core.database import Database
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.db.models import (
    DbProviderBudgetReservation,
    DbProviderBudgetWindow,
)
from backend.app.services.provider_budget import ProviderBudgetStore


def _clear_budget_state(db: Database) -> None:
    with db.session() as session:
        session.execute(delete(DbProviderBudgetReservation))
        session.execute(delete(DbProviderBudgetWindow))


def test_provider_budget_reserve_finalize_and_idempotency() -> None:
    db = Database()
    _clear_budget_state(db)
    store = ProviderBudgetStore(db)
    key = uuid.uuid4().hex
    now = datetime(2031, 1, 2, tzinfo=timezone.utc)

    first = store.reserve(
        idempotency_key=key,
        estimated_usd=0.05,
        daily_limit_usd=1.0,
        monthly_limit_usd=2.0,
        now=now,
    )
    second = store.reserve(
        idempotency_key=key,
        estimated_usd=0.05,
        daily_limit_usd=1.0,
        monthly_limit_usd=2.0,
        now=now,
    )
    assert first.status == "reserved"
    assert second.status == "reserved"

    store.finalize(key, actual_usd=0.03)
    store.finalize(key, actual_usd=0.03)

    with db.session() as session:
        reservation = session.get(DbProviderBudgetReservation, key)
        assert reservation is not None
        assert reservation.status == "finalized"
        assert reservation.actual_usd == pytest.approx(0.03)
        windows = list(session.scalars(select(DbProviderBudgetWindow)).all())
        assert len(windows) == 2
        assert all(window.reserved_usd == pytest.approx(0.0) for window in windows)
        assert all(window.spent_usd == pytest.approx(0.03) for window in windows)


def test_provider_budget_release_returns_capacity() -> None:
    db = Database()
    _clear_budget_state(db)
    store = ProviderBudgetStore(db)
    now = datetime(2031, 2, 2, tzinfo=timezone.utc)
    first_key = uuid.uuid4().hex

    store.reserve(
        idempotency_key=first_key,
        estimated_usd=0.08,
        daily_limit_usd=0.1,
        monthly_limit_usd=0.1,
        now=now,
    )
    store.release(first_key)
    store.reserve(
        idempotency_key=uuid.uuid4().hex,
        estimated_usd=0.08,
        daily_limit_usd=0.1,
        monthly_limit_usd=0.1,
        now=now,
    )


def test_provider_budget_rejects_closed_and_over_limit_windows() -> None:
    db = Database()
    _clear_budget_state(db)
    store = ProviderBudgetStore(db)
    now = datetime(2031, 3, 2, tzinfo=timezone.utc)

    with pytest.raises(ProviderBudgetExceededError, match="closed"):
        store.reserve(
            idempotency_key=uuid.uuid4().hex,
            estimated_usd=0.01,
            daily_limit_usd=0,
            monthly_limit_usd=1,
            now=now,
        )

    store.reserve(
        idempotency_key=uuid.uuid4().hex,
        estimated_usd=0.08,
        daily_limit_usd=0.1,
        monthly_limit_usd=1.0,
        now=now,
    )
    with pytest.raises(ProviderBudgetExceededError, match="Daily"):
        store.reserve(
            idempotency_key=uuid.uuid4().hex,
            estimated_usd=0.03,
            daily_limit_usd=0.1,
            monthly_limit_usd=1.0,
            now=now,
        )


def test_provider_budget_concurrent_reservations_cannot_overshoot() -> None:
    # REGRESSION: two workers racing at the budget boundary may authorize only
    # one provider call.
    db = Database()
    _clear_budget_state(db)
    now = datetime(2031, 4, 2, tzinfo=timezone.utc)

    def reserve_once() -> str:
        try:
            ProviderBudgetStore(Database()).reserve(
                idempotency_key=uuid.uuid4().hex,
                estimated_usd=0.08,
                daily_limit_usd=0.1,
                monthly_limit_usd=0.1,
                now=now,
            )
            return "reserved"
        except ProviderBudgetExceededError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = sorted(executor.map(lambda _: reserve_once(), range(2)))

    assert results == ["rejected", "reserved"]
