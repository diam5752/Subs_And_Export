"""Concurrency-safe provider-money reservations.

Every external call reserves guarded USD cost in both a daily and monthly
window before dispatch. PostgreSQL row locks make the cap effective across
workers, not just inside one process.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from backend.app.core.database import Database
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.db.models import (
    DbProviderBudgetReservation,
    DbProviderBudgetWindow,
)


@dataclass(frozen=True, slots=True)
class ProviderBudgetReservation:
    idempotency_key: str
    estimated_usd: float
    status: str


class ProviderBudgetStore:
    def __init__(self, db: Database) -> None:
        self.db = db

    def reserve(
        self,
        *,
        idempotency_key: str,
        estimated_usd: float,
        daily_limit_usd: float,
        monthly_limit_usd: float,
        now: datetime | None = None,
    ) -> ProviderBudgetReservation:
        estimate = float(estimated_usd)
        if not idempotency_key or len(idempotency_key) > 64:
            raise ValueError("Invalid provider budget idempotency key")
        if estimate <= 0:
            raise ValueError("Provider budget estimate must be positive")
        if daily_limit_usd <= 0 or monthly_limit_usd <= 0:
            raise ProviderBudgetExceededError("External provider budgets are closed")

        current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        daily_key, monthly_key = self._window_keys(current)
        now_ts = int(current.timestamp())

        with self.db.session() as session:
            existing = session.get(DbProviderBudgetReservation, idempotency_key)
            if existing is not None:
                if abs(float(existing.estimated_usd) - estimate) > 1e-9:
                    raise ValueError("Provider budget idempotency key conflict")
                return ProviderBudgetReservation(
                    idempotency_key=existing.idempotency_key,
                    estimated_usd=float(existing.estimated_usd),
                    status=existing.status,
                )

            for key, scope, period_start in (
                (daily_key, "day", self._day_start(current)),
                (monthly_key, "month", self._month_start(current)),
            ):
                session.execute(
                    pg_insert(DbProviderBudgetWindow)
                    .values(
                        key=key,
                        scope=scope,
                        period_start=period_start,
                        reserved_usd=0.0,
                        spent_usd=0.0,
                        updated_at=now_ts,
                    )
                    .on_conflict_do_nothing(index_elements=[DbProviderBudgetWindow.key])
                )

            windows = list(
                session.scalars(
                    select(DbProviderBudgetWindow)
                    .where(DbProviderBudgetWindow.key.in_([daily_key, monthly_key]))
                    .order_by(DbProviderBudgetWindow.key.asc())
                    .with_for_update()
                ).all()
            )
            by_key = {window.key: window for window in windows}
            daily = by_key.get(daily_key)
            monthly = by_key.get(monthly_key)
            if daily is None or monthly is None:
                raise RuntimeError("Provider budget windows could not be locked")

            if float(daily.reserved_usd) + float(daily.spent_usd) + estimate > daily_limit_usd:
                raise ProviderBudgetExceededError("Daily external provider budget exceeded")
            if float(monthly.reserved_usd) + float(monthly.spent_usd) + estimate > monthly_limit_usd:
                raise ProviderBudgetExceededError("Monthly external provider budget exceeded")

            daily.reserved_usd += estimate
            monthly.reserved_usd += estimate
            daily.updated_at = now_ts
            monthly.updated_at = now_ts
            session.add(
                DbProviderBudgetReservation(
                    idempotency_key=idempotency_key,
                    daily_window_key=daily_key,
                    monthly_window_key=monthly_key,
                    estimated_usd=estimate,
                    actual_usd=0.0,
                    status="reserved",
                    created_at=now_ts,
                    updated_at=now_ts,
                )
            )

        return ProviderBudgetReservation(
            idempotency_key=idempotency_key,
            estimated_usd=estimate,
            status="reserved",
        )

    def release(self, idempotency_key: str) -> None:
        self._settle(idempotency_key=idempotency_key, actual_usd=None)

    def finalize(self, idempotency_key: str, *, actual_usd: float) -> None:
        actual = float(actual_usd)
        if actual < 0:
            raise ValueError("Provider actual cost cannot be negative")
        self._settle(idempotency_key=idempotency_key, actual_usd=actual)

    def _settle(self, *, idempotency_key: str, actual_usd: float | None) -> None:
        now_ts = int(time.time())
        with self.db.session() as session:
            reservation = session.scalar(
                select(DbProviderBudgetReservation)
                .where(DbProviderBudgetReservation.idempotency_key == idempotency_key)
                .with_for_update()
                .limit(1)
            )
            if reservation is None:
                return
            if reservation.status != "reserved":
                return

            window_keys = [reservation.daily_window_key, reservation.monthly_window_key]
            windows = list(
                session.scalars(
                    select(DbProviderBudgetWindow)
                    .where(DbProviderBudgetWindow.key.in_(window_keys))
                    .order_by(DbProviderBudgetWindow.key.asc())
                    .with_for_update()
                ).all()
            )
            if len(windows) != 2:
                raise RuntimeError("Provider budget reservation windows are missing")

            estimate = float(reservation.estimated_usd)
            for window in windows:
                window.reserved_usd = max(0.0, float(window.reserved_usd) - estimate)
                if actual_usd is not None:
                    window.spent_usd += actual_usd
                window.updated_at = now_ts

            reservation.actual_usd = float(actual_usd or 0.0)
            reservation.status = "finalized" if actual_usd is not None else "released"
            reservation.updated_at = now_ts

    @staticmethod
    def _window_keys(now: datetime) -> tuple[str, str]:
        return (
            f"day:{now:%Y-%m-%d}",
            f"month:{now:%Y-%m}",
        )

    @staticmethod
    def _day_start(now: datetime) -> int:
        return int(datetime(now.year, now.month, now.day, tzinfo=timezone.utc).timestamp())

    @staticmethod
    def _month_start(now: datetime) -> int:
        return int(datetime(now.year, now.month, 1, tzinfo=timezone.utc).timestamp())
