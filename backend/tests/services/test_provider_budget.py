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


def test_provider_budget_preflight_reads_current_windows_without_writing() -> None:
    db = Database()
    _clear_budget_state(db)
    store = ProviderBudgetStore(db)
    now = datetime(2031, 3, 3, tzinfo=timezone.utc)
    key = uuid.uuid4().hex
    store.reserve(
        idempotency_key=key,
        estimated_usd=0.08,
        daily_limit_usd=0.1,
        monthly_limit_usd=1.0,
        now=now,
    )

    with pytest.raises(ProviderBudgetExceededError, match="Daily"):
        store.assert_can_reserve(
            estimated_usd=0.03,
            daily_limit_usd=0.1,
            monthly_limit_usd=1.0,
            now=now,
        )

    with db.session() as session:
        reservations = list(
            session.scalars(select(DbProviderBudgetReservation)).all(),
        )
        windows = list(session.scalars(select(DbProviderBudgetWindow)).all())
        assert [item.idempotency_key for item in reservations] == [key]
        assert len(windows) == 2
        assert all(window.reserved_usd == pytest.approx(0.08) for window in windows)


def test_provider_budget_preflight_treats_missing_windows_as_zero_without_creating() -> None:
    db = Database()
    _clear_budget_state(db)

    ProviderBudgetStore(db).assert_can_reserve(
        estimated_usd=0.03,
        daily_limit_usd=0.1,
        monthly_limit_usd=1.0,
        now=datetime(2031, 3, 4, tzinfo=timezone.utc),
    )

    with db.session() as session:
        assert list(session.scalars(select(DbProviderBudgetReservation)).all()) == []
        assert list(session.scalars(select(DbProviderBudgetWindow)).all()) == []


@pytest.mark.parametrize(
    "estimated_usd",
    [float("nan"), float("inf"), float("-inf"), 0.0, -0.01],
)
def test_provider_budget_rejects_non_finite_or_non_positive_estimates(
    estimated_usd: float,
) -> None:
    # REGRESSION: NaN compares false to both zero and hard limits, which could
    # otherwise create a reservation without consuming guarded capacity.
    store = ProviderBudgetStore(Database())

    with pytest.raises(ValueError, match="finite and positive"):
        store.reserve(
            idempotency_key=uuid.uuid4().hex,
            estimated_usd=estimated_usd,
            daily_limit_usd=1.0,
            monthly_limit_usd=2.0,
        )


@pytest.mark.parametrize(
    ("daily_limit_usd", "monthly_limit_usd"),
    [
        (float("nan"), 1.0),
        (1.0, float("nan")),
        (float("inf"), 1.0),
        (1.0, float("inf")),
    ],
)
def test_provider_budget_rejects_non_finite_hard_limits(
    daily_limit_usd: float,
    monthly_limit_usd: float,
) -> None:
    # REGRESSION: a non-finite cap must close dispatch rather than behave like
    # an unlimited operator-money budget.
    store = ProviderBudgetStore(Database())

    with pytest.raises(ProviderBudgetExceededError, match="closed"):
        store.reserve(
            idempotency_key=uuid.uuid4().hex,
            estimated_usd=0.01,
            daily_limit_usd=daily_limit_usd,
            monthly_limit_usd=monthly_limit_usd,
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
