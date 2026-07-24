"""Usage ledger store for external API usage and credit reservations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.db.models import DbUsageLedger
from backend.app.services.points import PointsStore, make_idempotency_id
from backend.app.services.provider_budget import ProviderBudgetStore


@dataclass(frozen=True)
class ChargeReservation:
    ledger_id: str
    user_id: str
    job_id: str | None
    action: str
    provider: str
    model: str | None
    tier: str | None
    reserved_credits: int
    min_credits: int
    idempotency_key: str
    paid_credits_reserved: int = 0
    estimated_cost_usd: float = 0.0


@dataclass(frozen=True)
class ChargePlan:
    """Charge reservations tied to a processing job."""

    transcription: ChargeReservation | None = None
    social_copy: ChargeReservation | None = None


@dataclass(frozen=True)
class UsageSummaryRow:
    bucket: str
    credits_reserved: int
    credits_charged: int
    cost_usd: float
    count: int


class UsageLedgerStore:
    def __init__(self, db: Database, points_store: PointsStore) -> None:
        self.db = db
        self.points_store = points_store
        self.provider_budget_store = ProviderBudgetStore(db)

    def reserve(
        self,
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
        units: dict[str, Any] | None,
        idempotency_key: str,
        endpoint: str | None = None,
        currency: str = "USD",
        covered_by_ledger_id: str | None = None,
        require_paid_credits: bool | None = None,
    ) -> tuple[ChargeReservation, int]:
        if credits < 0 or (credits == 0 and not covered_by_ledger_id):
            raise ValueError("credits must be positive unless covered by a paid reservation")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        if covered_by_ledger_id:
            self._validate_coverage(
                covered_by_ledger_id=covered_by_ledger_id,
                user_id=user_id,
                job_id=job_id,
            )

        with self.db.session() as session:
            existing = session.scalar(
                select(DbUsageLedger).where(DbUsageLedger.idempotency_key == idempotency_key).limit(1)
            )
            if existing:
                self._validate_existing_reservation(
                    existing,
                    user_id=user_id,
                    job_id=job_id,
                    action=action,
                    provider=provider,
                    model=model,
                    tier=tier,
                    credits=credits,
                    min_credits=min_credits,
                    cost_estimate_usd=cost_estimate_usd,
                    covered_by_ledger_id=covered_by_ledger_id,
                    require_paid_credits=require_paid_credits,
                )
                reservation = ChargeReservation(
                    ledger_id=existing.id,
                    user_id=existing.user_id,
                    job_id=existing.job_id,
                    action=existing.action,
                    provider=existing.provider,
                    model=existing.model,
                    tier=existing.tier,
                    reserved_credits=existing.credits_reserved,
                    min_credits=existing.min_credits,
                    idempotency_key=idempotency_key,
                    paid_credits_reserved=existing.paid_credits_reserved,
                    estimated_cost_usd=self._estimate_from_ledger(existing),
                )
                balance = self.points_store.get_balance(user_id)
                return reservation, balance

        normalized_provider = provider.strip().lower()
        estimate = max(0.0, float(cost_estimate_usd))
        provider_requires_paid = estimate > 0 and normalized_provider not in {"local", "mock"}
        requires_paid = provider_requires_paid or require_paid_credits is True
        guarded_estimate = estimate * settings.external_provider_price_safety_multiplier
        budget_reserved = False
        if requires_paid:
            self.provider_budget_store.reserve(
                idempotency_key=idempotency_key,
                estimated_usd=guarded_estimate,
                daily_limit_usd=settings.external_provider_daily_budget_usd,
                monthly_limit_usd=settings.external_provider_monthly_budget_usd,
            )
            budget_reserved = True

        ledger_id = uuid.uuid4().hex
        spent = False
        try:
            if credits > 0:
                tx_id = make_idempotency_id("reserve", idempotency_key)
                new_balance, spent = self.points_store.spend_once(
                    user_id,
                    credits,
                    reason=action,
                    transaction_id=tx_id,
                    meta={
                        "ledger_id": ledger_id,
                        "action": action,
                        "provider": provider,
                        "model": model,
                        "tier": tier,
                        "kind": "reserve",
                        "funding_source": "paid" if requires_paid else "mixed",
                    },
                    require_paid=requires_paid,
                )
            else:
                new_balance = self.points_store.get_balance(user_id)
        except Exception:
            if budget_reserved:
                self.provider_budget_store.release(idempotency_key)
            raise

        now = int(time.time())
        resolved_units = dict(units or {})
        resolved_units["cost_estimate_usd"] = estimate
        resolved_units["guarded_cost_estimate_usd"] = guarded_estimate
        resolved_units["paid_credits_reserved"] = credits if requires_paid else 0
        resolved_units["require_paid_credits"] = requires_paid
        if covered_by_ledger_id:
            resolved_units["covered_by_ledger_id"] = covered_by_ledger_id
        record = DbUsageLedger(
            id=ledger_id,
            user_id=user_id,
            job_id=job_id,
            action=action,
            provider=provider,
            endpoint=endpoint,
            model=model,
            tier=tier,
            units=resolved_units,
            cost_usd=estimate,
            credits_reserved=credits,
            paid_credits_reserved=credits if requires_paid else 0,
            credits_charged=0,
            min_credits=min_credits,
            currency=currency,
            status="reserved",
            error=None,
            idempotency_key=idempotency_key,
            created_at=now,
            updated_at=now,
        )

        try:
            with self.db.session() as session:
                session.add(record)
        except IntegrityError:
            with self.db.session() as session:
                existing = session.scalar(
                    select(DbUsageLedger).where(DbUsageLedger.idempotency_key == idempotency_key).limit(1)
                )
            if existing:
                self._validate_existing_reservation(
                    existing,
                    user_id=user_id,
                    job_id=job_id,
                    action=action,
                    provider=provider,
                    model=model,
                    tier=tier,
                    credits=credits,
                    min_credits=min_credits,
                    cost_estimate_usd=cost_estimate_usd,
                    covered_by_ledger_id=covered_by_ledger_id,
                    require_paid_credits=require_paid_credits,
                )
                reservation = ChargeReservation(
                    ledger_id=existing.id,
                    user_id=existing.user_id,
                    job_id=existing.job_id,
                    action=existing.action,
                    provider=existing.provider,
                    model=existing.model,
                    tier=existing.tier,
                    reserved_credits=existing.credits_reserved,
                    min_credits=existing.min_credits,
                    idempotency_key=idempotency_key,
                    paid_credits_reserved=existing.paid_credits_reserved,
                    estimated_cost_usd=self._estimate_from_ledger(existing),
                )
                balance = self.points_store.get_balance(user_id)
                return reservation, balance

            if spent:
                refund_tx = make_idempotency_id("refund", ledger_id, "reserve")
                self.points_store.refund_once(
                    user_id,
                    credits,
                    original_reason=action,
                    transaction_id=refund_tx,
                    meta={"ledger_id": ledger_id, "action": action, "kind": "reserve_refund"},
                    paid_credit_delta=credits if requires_paid else 0,
                )
            if budget_reserved:
                self.provider_budget_store.release(idempotency_key)
            raise
        except Exception:
            if spent:
                refund_tx = make_idempotency_id("refund", ledger_id, "reserve")
                self.points_store.refund_once(
                    user_id,
                    credits,
                    original_reason=action,
                    transaction_id=refund_tx,
                    meta={"ledger_id": ledger_id, "action": action, "kind": "reserve_refund"},
                    paid_credit_delta=credits if requires_paid else 0,
                )
            if budget_reserved:
                self.provider_budget_store.release(idempotency_key)
            raise

        reservation = ChargeReservation(
            ledger_id=ledger_id,
            user_id=user_id,
            job_id=job_id,
            action=action,
            provider=provider,
            model=model,
            tier=tier,
            reserved_credits=credits,
            min_credits=min_credits,
            idempotency_key=idempotency_key,
            paid_credits_reserved=credits if requires_paid else 0,
            estimated_cost_usd=estimate,
        )
        return reservation, new_balance

    def mark_dispatched(self, reservation: ChargeReservation) -> None:
        """Persist the no-refund boundary immediately before provider I/O."""
        now = int(time.time())
        with self.db.session() as session:
            ledger = session.scalar(
                select(DbUsageLedger)
                .where(DbUsageLedger.id == reservation.ledger_id)
                .with_for_update()
                .limit(1)
            )
            if ledger is None:
                raise RuntimeError("Usage reservation is missing")
            if ledger.status == "reserved":
                ledger.status = "dispatched"
                ledger.updated_at = now
            elif ledger.status not in {"dispatched", "finalizing", "finalized"}:
                raise RuntimeError(f"Usage reservation cannot be dispatched from {ledger.status}")

    def finalize(
        self,
        reservation: ChargeReservation,
        *,
        credits_charged: int,
        cost_usd: float,
        units: dict[str, Any] | None,
        status: str = "finalized",
    ) -> int:
        with self.db.session() as session:
            ledger = session.scalar(
                select(DbUsageLedger)
                .where(DbUsageLedger.id == reservation.ledger_id)
                .with_for_update()
                .limit(1)
            )
            if ledger is None:
                return self.points_store.get_balance(reservation.user_id)
            if ledger.status in {"finalized", "failed_charged"}:
                return self.points_store.get_balance(reservation.user_id)
            if ledger.status not in {"reserved", "dispatched", "finalizing"}:
                return self.points_store.get_balance(reservation.user_id)
            ledger.status = "finalizing"
            ledger.updated_at = int(time.time())

        final_credits = (
            0
            if reservation.reserved_credits == 0 and reservation.min_credits == 0
            else max(int(credits_charged), int(reservation.min_credits))
        )
        refund_amount = max(0, reservation.reserved_credits - final_credits)
        extra_charge = max(0, final_credits - reservation.reserved_credits)
        paid_operation = reservation.paid_credits_reserved > 0

        if extra_charge:
            tx_id = make_idempotency_id("overage", reservation.ledger_id, str(extra_charge))
            self.points_store.spend_once(
                reservation.user_id,
                extra_charge,
                reason=reservation.action,
                transaction_id=tx_id,
                meta={"ledger_id": reservation.ledger_id, "action": reservation.action, "kind": "overage"},
                require_paid=paid_operation,
            )

        if refund_amount:
            refund_tx = make_idempotency_id("refund", reservation.ledger_id, str(refund_amount))
            self.points_store.refund_once(
                reservation.user_id,
                refund_amount,
                original_reason=reservation.action,
                transaction_id=refund_tx,
                meta={"ledger_id": reservation.ledger_id, "action": reservation.action, "kind": "adjustment"},
                paid_credit_delta=refund_amount if paid_operation else 0,
            )

        now = int(time.time())
        with self.db.session() as session:
            ledger = session.get(DbUsageLedger, reservation.ledger_id)
            if not ledger:
                return self.points_store.get_balance(reservation.user_id)
            ledger.credits_charged = final_credits
            ledger.cost_usd = float(cost_usd)
            ledger.units = units
            ledger.status = status
            ledger.updated_at = now

        if reservation.estimated_cost_usd > 0:
            self.provider_budget_store.finalize(
                reservation.idempotency_key,
                actual_usd=max(0.0, float(cost_usd)),
            )

        return self.points_store.get_balance(reservation.user_id)

    def fail(
        self,
        reservation: ChargeReservation,
        *,
        status: str,
        error: str | None = None,
    ) -> int:
        now = int(time.time())
        with self.db.session() as session:
            ledger = session.scalar(
                select(DbUsageLedger)
                .where(DbUsageLedger.id == reservation.ledger_id)
                .with_for_update()
                .limit(1)
            )
            if ledger is None:
                return self.points_store.get_balance(reservation.user_id)
            current_status = ledger.status
            if current_status == "reserved":
                ledger.status = "failing_refund"
            elif current_status in {"dispatched", "finalizing"}:
                ledger.status = "failing_charged"
            elif current_status not in {"failing_refund", "failing_charged"}:
                return self.points_store.get_balance(reservation.user_id)
            ledger.updated_at = now

        if current_status in {"reserved", "failing_refund"}:
            if reservation.reserved_credits > 0:
                refund_tx = make_idempotency_id("refund", reservation.ledger_id, "failed")
                self.points_store.refund_once(
                    reservation.user_id,
                    reservation.reserved_credits,
                    original_reason=reservation.action,
                    transaction_id=refund_tx,
                    meta={
                        "ledger_id": reservation.ledger_id,
                        "action": reservation.action,
                        "kind": "failed",
                    },
                    paid_credit_delta=reservation.paid_credits_reserved,
                )
            if reservation.estimated_cost_usd > 0:
                self.provider_budget_store.release(reservation.idempotency_key)
            settled_status = status
            charged = 0
        elif current_status in {"dispatched", "finalizing", "failing_charged"}:
            if reservation.estimated_cost_usd > 0:
                self.provider_budget_store.finalize(
                    reservation.idempotency_key,
                    actual_usd=reservation.estimated_cost_usd,
                )
            settled_status = "failed_charged"
            charged = reservation.reserved_credits
        with self.db.session() as session:
            ledger = session.get(DbUsageLedger, reservation.ledger_id)
            if ledger:
                ledger.status = settled_status
                ledger.credits_charged = charged
                ledger.error = error[:500] if error else None
                ledger.updated_at = now
        return self.points_store.get_balance(reservation.user_id)

    def refund_if_reserved(
        self,
        reservation: ChargeReservation,
        *,
        status: str,
        error: str | None = None,
    ) -> int:
        return self.fail(reservation, status=status, error=error)

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
    def _estimate_from_ledger(ledger: DbUsageLedger) -> float:
        units = ledger.units if isinstance(ledger.units, dict) else {}
        stored = units.get("cost_estimate_usd")
        return float(stored if stored is not None else ledger.cost_usd or 0.0)

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
            max(0.0, float(cost_estimate_usd)) > 0
            and normalized_provider not in {"local", "mock"}
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
            or abs(
                UsageLedgerStore._estimate_from_ledger(ledger)
                - max(0.0, float(cost_estimate_usd))
            )
            > 1e-9
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
                or parent.status
                not in {"reserved", "dispatched", "finalizing", "finalized", "failed_charged"}
            ):
                raise ValueError("Included provider call requires a matching paid reservation")
