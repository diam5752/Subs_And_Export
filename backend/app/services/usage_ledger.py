"""Usage ledger store for external API usage and credit reservations."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.core.database import Database
from backend.app.db.models import DbUsageLedger
from backend.app.services.points import PointsStore, make_idempotency_id


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
    ) -> tuple[ChargeReservation, int]:
        if credits <= 0:
            raise ValueError("credits must be positive")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")

        with self.db.session() as session:
            existing = session.scalar(
                select(DbUsageLedger).where(DbUsageLedger.idempotency_key == idempotency_key).limit(1)
            )
            if existing:
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
                )
                balance = self.points_store.get_balance(user_id)
                return reservation, balance

        ledger_id = uuid.uuid4().hex
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
            },
        )

        now = int(time.time())
        record = DbUsageLedger(
            id=ledger_id,
            user_id=user_id,
            job_id=job_id,
            action=action,
            provider=provider,
            endpoint=endpoint,
            model=model,
            tier=tier,
            units=units,
            cost_usd=cost_estimate_usd,
            credits_reserved=credits,
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
                )
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
                )
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
        )
        return reservation, new_balance

    def finalize(
        self,
        reservation: ChargeReservation,
        *,
        credits_charged: int,
        cost_usd: float,
        units: dict[str, Any] | None,
        status: str = "finalized",
    ) -> int:
        final_credits = max(int(credits_charged), int(reservation.min_credits))
        refund_amount = max(0, reservation.reserved_credits - final_credits)
        extra_charge = max(0, final_credits - reservation.reserved_credits)

        if extra_charge:
            tx_id = make_idempotency_id("overage", reservation.ledger_id, str(extra_charge))
            self.points_store.spend_once(
                reservation.user_id,
                extra_charge,
                reason=reservation.action,
                transaction_id=tx_id,
                meta={"ledger_id": reservation.ledger_id, "action": reservation.action, "kind": "overage"},
            )

        if refund_amount:
            refund_tx = make_idempotency_id("refund", reservation.ledger_id, str(refund_amount))
            self.points_store.refund_once(
                reservation.user_id,
                refund_amount,
                original_reason=reservation.action,
                transaction_id=refund_tx,
                meta={"ledger_id": reservation.ledger_id, "action": reservation.action, "kind": "adjustment"},
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

        return self.points_store.get_balance(reservation.user_id)

    def fail(
        self,
        reservation: ChargeReservation,
        *,
        status: str,
        error: str | None = None,
    ) -> int:
        refund_tx = make_idempotency_id("refund", reservation.ledger_id, "failed")
        self.points_store.refund_once(
            reservation.user_id,
            reservation.reserved_credits,
            original_reason=reservation.action,
            transaction_id=refund_tx,
            meta={"ledger_id": reservation.ledger_id, "action": reservation.action, "kind": "failed"},
        )

        now = int(time.time())
        with self.db.session() as session:
            ledger = session.get(DbUsageLedger, reservation.ledger_id)
            if ledger:
                ledger.status = status
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
        with self.db.session() as session:
            ledger = session.get(DbUsageLedger, reservation.ledger_id)
            if not ledger or ledger.status != "reserved":
                return self.points_store.get_balance(reservation.user_id)

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
