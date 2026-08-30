"""Usage ledger store for external API usage and credit reservations."""

from __future__ import annotations

import hashlib
import time as time
from datetime import datetime, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from backend.app.core.database import Database
from backend.app.db.models import (
    DbUsageLedger,
)
from backend.app.services.points import PointsStore, make_idempotency_id
from backend.app.services.provider_budget import ProviderBudgetStore
from backend.app.services.usage_recovery import UsageRecoveryMixin
from backend.app.services.usage_reservations import UsageReservationMixin
from backend.app.services.usage_settlement import UsageSettlementMixin
from backend.app.services.usage_types import ChargePlan as ChargePlan
from backend.app.services.usage_types import ChargeReservation as ChargeReservation
from backend.app.services.usage_types import UsageSummaryRow as UsageSummaryRow

__all__ = [
    "ChargePlan",
    "ChargeReservation",
    "UsageLedgerStore",
    "UsageSummaryRow",
]


class UsageLedgerStore(
    UsageReservationMixin,
    UsageSettlementMixin,
    UsageRecoveryMixin,
):
    def __init__(self, db: Database, points_store: PointsStore) -> None:
        self.db = db
        self.points_store = points_store
        self.provider_budget_store = ProviderBudgetStore(db)

    def summarize(
        self,
        *,
        start_ts: int,
        end_ts: int,
        group_by: str,
    ) -> list[UsageSummaryRow]:
        if start_ts > end_ts:
            raise ValueError("start_ts must be <= end_ts")
        if group_by not in {"day", "month", "user", "action"}:
            raise ValueError("Invalid group_by")

        with self.db.session() as session:
            rows = list(
                session.scalars(
                    select(DbUsageLedger).where(
                        DbUsageLedger.created_at >= start_ts,
                        DbUsageLedger.created_at <= end_ts,
                    )
                ).all()
            )

        summary: dict[str, UsageSummaryRow] = {}
        for row in rows:
            if group_by == "day":
                bucket = datetime.fromtimestamp(row.created_at, tz=timezone.utc).strftime("%Y-%m-%d")
            elif group_by == "month":
                bucket = datetime.fromtimestamp(row.created_at, tz=timezone.utc).strftime("%Y-%m")
            elif group_by == "user":
                bucket = row.user_id
            else:
                bucket = row.action

            existing = summary.get(bucket)
            if existing:
                summary[bucket] = UsageSummaryRow(
                    bucket=bucket,
                    credits_reserved=existing.credits_reserved + int(row.credits_reserved or 0),
                    credits_charged=existing.credits_charged + int(row.credits_charged or 0),
                    cost_usd=existing.cost_usd + float(row.cost_usd or 0.0),
                    count=existing.count + 1,
                )
            else:
                summary[bucket] = UsageSummaryRow(
                    bucket=bucket,
                    credits_reserved=int(row.credits_reserved or 0),
                    credits_charged=int(row.credits_charged or 0),
                    cost_usd=float(row.cost_usd or 0.0),
                    count=1,
                )

        return sorted(summary.values(), key=lambda item: item.bucket)

    def total_cost_usd(self, *, start_ts: int, end_ts: int) -> float:
        """Return reserved/finalized provider cost for a closed time range."""
        if start_ts > end_ts:
            raise ValueError("start_ts must be <= end_ts")
        with self.db.session() as session:
            value = session.scalar(
                select(func.coalesce(func.sum(DbUsageLedger.cost_usd), 0.0)).where(
                    DbUsageLedger.created_at >= start_ts,
                    DbUsageLedger.created_at <= end_ts,
                )
            )
        return float(value or 0.0)

    @staticmethod
    def _advisory_lock_key(value: str) -> int:
        return int.from_bytes(
            hashlib.sha256(value.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )

    def _resolve_retry_idempotency_in_session(
        self,
        session: Session,
        root_idempotency_key: str,
    ) -> tuple[str, int]:
        """Serialize retries and derive a new key only after a refund."""
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {
                "lock_key": self._advisory_lock_key(
                    f"usage-retry:{root_idempotency_key}",
                )
            },
        )
        candidates = list(
            session.scalars(
                select(DbUsageLedger).where(
                    or_(
                        DbUsageLedger.idempotency_key == root_idempotency_key,
                        (DbUsageLedger.units["retry_root_idempotency_key"].as_string() == root_idempotency_key),
                    )
                )
            ).all()
        )
        if not candidates:
            return root_idempotency_key, 0

        def retry_attempt(ledger: DbUsageLedger) -> int:
            units = ledger.units if isinstance(ledger.units, dict) else {}
            raw_attempt = units.get("retry_attempt", 0)
            if not isinstance(raw_attempt, int) or isinstance(raw_attempt, bool) or raw_attempt < 0:
                raise RuntimeError(
                    "Usage retry metadata is invalid",
                )
            return raw_attempt

        latest = max(
            candidates,
            key=lambda ledger: (
                retry_attempt(ledger),
                int(ledger.created_at),
                ledger.id,
            ),
        )
        latest_attempt = retry_attempt(latest)
        if latest.status not in {"failed", "cancelled"}:
            if not latest.idempotency_key:
                raise RuntimeError(
                    "Usage retry ledger has no idempotency key",
                )
            return latest.idempotency_key, latest_attempt

        next_attempt = latest_attempt + 1
        return (
            make_idempotency_id(
                "usage-retry",
                root_idempotency_key,
                str(next_attempt),
            ),
            next_attempt,
        )

    @staticmethod
    def _estimate_from_ledger(ledger: DbUsageLedger) -> float:
        units = ledger.units if isinstance(ledger.units, dict) else {}
        stored = units.get("cost_estimate_usd")
        return float(stored if stored is not None else ledger.cost_usd or 0.0)

    @staticmethod
    def _reservation_from_ledger(
        ledger: DbUsageLedger,
        *,
        idempotency_key: str,
    ) -> ChargeReservation:
        return ChargeReservation(
            ledger_id=ledger.id,
            user_id=ledger.user_id,
            job_id=ledger.job_id,
            action=ledger.action,
            provider=ledger.provider,
            model=ledger.model,
            tier=ledger.tier,
            reserved_credits=int(ledger.credits_reserved),
            min_credits=int(ledger.min_credits),
            idempotency_key=idempotency_key,
            paid_credits_reserved=int(ledger.paid_credits_reserved),
            estimated_cost_usd=UsageLedgerStore._estimate_from_ledger(
                ledger,
            ),
        )

    @staticmethod
    def _validate_existing_reservation(
        ledger: DbUsageLedger,
        *,
        user_id: str,
        job_id: str | None,
        action: str,
        provider: str,
        model: str | None,
        tier: str | None,
        credits: int,
        min_credits: int,
        cost_estimate_usd: float,
        covered_by_ledger_id: str | None,
        require_paid_credits: bool | None,
    ) -> None:
        units = ledger.units if isinstance(ledger.units, dict) else {}
        normalized_provider = provider.strip().lower()
        expected_requires_paid = (
            max(0.0, float(cost_estimate_usd)) > 0 and normalized_provider not in {"local", "mock"}
        ) or require_paid_credits is True
        if (
            ledger.user_id != user_id
            or ledger.job_id != job_id
            or ledger.action != action
            or ledger.provider != provider
            or ledger.model != model
            or ledger.tier != tier
            or int(ledger.credits_reserved) != int(credits)
            or int(ledger.min_credits) != int(min_credits)
            or abs(UsageLedgerStore._estimate_from_ledger(ledger) - max(0.0, float(cost_estimate_usd))) > 1e-9
            or units.get("covered_by_ledger_id") != covered_by_ledger_id
            or bool(units.get("require_paid_credits")) != expected_requires_paid
        ):
            raise ValueError("Usage idempotency key conflict")

    def _validate_coverage(
        self,
        *,
        covered_by_ledger_id: str,
        user_id: str,
        job_id: str | None,
    ) -> None:
        with self.db.session() as session:
            parent = session.get(DbUsageLedger, covered_by_ledger_id)
            if (
                parent is None
                or parent.user_id != user_id
                or parent.job_id != job_id
                or int(parent.paid_credits_reserved or 0) <= 0
                or parent.status not in {"reserved", "dispatched", "finalizing", "finalized", "failed_charged"}
            ):
                raise ValueError("Included provider call requires a matching paid reservation")
