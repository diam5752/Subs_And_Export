"""Usage ledger store for external API usage and credit reservations."""

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.db.models import (
    DbJob,
    DbPointTransaction,
    DbProviderBudgetReservation,
    DbUsageLedger,
    DbUsageResult,
)
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
        allow_terminal_retry: bool = False,
    ) -> tuple[ChargeReservation, int]:
        if credits < 0 or (credits == 0 and not covered_by_ledger_id):
            raise ValueError("credits must be positive unless covered by a paid reservation")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        estimate = float(cost_estimate_usd)
        if not math.isfinite(estimate) or estimate < 0:
            raise ValueError(
                "Provider cost estimate must be finite and non-negative",
            )
        if covered_by_ledger_id:
            self._validate_coverage(
                covered_by_ledger_id=covered_by_ledger_id,
                user_id=user_id,
                job_id=job_id,
            )

        normalized_provider = provider.strip().lower()
        provider_requires_paid = estimate > 0 and normalized_provider not in {"local", "mock"}
        requires_paid = provider_requires_paid or require_paid_credits is True
        guarded_estimate = estimate * settings.external_provider_price_safety_multiplier
        if not math.isfinite(guarded_estimate) or guarded_estimate < 0:
            raise ValueError(
                "Guarded provider cost estimate must be finite and non-negative",
            )

        now = int(time.time())
        resolved_units = dict(units or {})
        resolved_units["cost_estimate_usd"] = estimate
        resolved_units["guarded_cost_estimate_usd"] = guarded_estimate
        resolved_units["paid_credits_reserved"] = credits if requires_paid else 0
        resolved_units["require_paid_credits"] = requires_paid
        if covered_by_ledger_id:
            resolved_units["covered_by_ledger_id"] = covered_by_ledger_id

        root_idempotency_key = idempotency_key
        ledger_id = make_idempotency_id("ledger", idempotency_key)
        reserve_tx_id = make_idempotency_id("reserve", idempotency_key)
        reservation: ChargeReservation | None = None
        try:
            with self.db.session() as session:
                if allow_terminal_retry:
                    idempotency_key, retry_attempt = (
                        self._resolve_retry_idempotency_in_session(
                            session,
                            root_idempotency_key,
                        )
                    )
                    resolved_units["retry_root_idempotency_key"] = (
                        root_idempotency_key
                    )
                    resolved_units["retry_attempt"] = retry_attempt
                    ledger_id = make_idempotency_id(
                        "ledger",
                        idempotency_key,
                    )
                    reserve_tx_id = make_idempotency_id(
                        "reserve",
                        idempotency_key,
                    )
                existing = session.scalar(
                    select(DbUsageLedger)
                    .where(
                        DbUsageLedger.idempotency_key == idempotency_key,
                    )
                    .limit(1)
                )
                if existing is not None:
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
                        cost_estimate_usd=estimate,
                        covered_by_ledger_id=covered_by_ledger_id,
                        require_paid_credits=require_paid_credits,
                    )
                    reservation = self._reservation_from_ledger(
                        existing,
                        idempotency_key=idempotency_key,
                    )
                else:
                    existing_debit = (
                        session.get(DbPointTransaction, reserve_tx_id)
                        if credits > 0
                        else None
                    )
                    if existing_debit is not None:
                        debit_meta = (
                            existing_debit.meta
                            if isinstance(existing_debit.meta, dict)
                            else {}
                        )
                        recovered_ledger_id = debit_meta.get("ledger_id")
                        if (
                            not isinstance(recovered_ledger_id, str)
                            or len(recovered_ledger_id) != 32
                        ):
                            raise RuntimeError(
                                "Existing usage debit has no recoverable ledger",
                            )
                        ledger_id = recovered_ledger_id
                        linked_transactions = list(
                            session.scalars(
                                select(DbPointTransaction)
                                .where(
                                    DbPointTransaction.user_id == user_id,
                                    or_(
                                        DbPointTransaction.id
                                        == reserve_tx_id,
                                        (
                                            DbPointTransaction.meta[
                                                "ledger_id"
                                            ].as_string()
                                            == ledger_id
                                        ),
                                    ),
                                )
                                .with_for_update()
                            ).all()
                        )
                        net_charge = max(
                            0,
                            -sum(
                                int(item.delta)
                                for item in linked_transactions
                            ),
                        )
                        net_paid_charge = max(
                            0,
                            -sum(
                                int(item.paid_delta)
                                for item in linked_transactions
                            ),
                        )
                        if (
                            net_charge != credits
                            or (
                                requires_paid
                                and net_paid_charge != credits
                            )
                        ):
                            raise RuntimeError(
                                "Existing usage debit is not outstanding",
                            )

                    if credits > 0:
                        self.points_store.spend_once_in_session(
                            session,
                            user_id,
                            credits,
                            reason=action,
                            transaction_id=reserve_tx_id,
                            meta={
                                "ledger_id": ledger_id,
                                "action": action,
                                "provider": provider,
                                "model": model,
                                "tier": tier,
                                "kind": "reserve",
                                "funding_source": (
                                    "paid" if requires_paid else "mixed"
                                ),
                            },
                            require_paid=requires_paid,
                        )

                    if requires_paid:
                        budget = (
                            self.provider_budget_store.reserve_in_session(
                                session,
                                idempotency_key=idempotency_key,
                                estimated_usd=guarded_estimate,
                                daily_limit_usd=(
                                    settings.external_provider_daily_budget_usd
                                ),
                                monthly_limit_usd=(
                                    settings.external_provider_monthly_budget_usd
                                ),
                            )
                        )
                        if budget.status != "reserved":
                            raise RuntimeError(
                                "Provider budget idempotency key is settled",
                            )

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
                        paid_credits_reserved=(
                            credits if requires_paid else 0
                        ),
                        credits_charged=0,
                        min_credits=min_credits,
                        currency=currency,
                        status="reserved",
                        error=None,
                        idempotency_key=idempotency_key,
                        created_at=now,
                        updated_at=now,
                    )
                    session.add(record)
                    reservation = self._reservation_from_ledger(
                        record,
                        idempotency_key=idempotency_key,
                    )
        except IntegrityError:
            with self.db.session() as session:
                existing = session.scalar(
                    select(DbUsageLedger)
                    .where(
                        DbUsageLedger.idempotency_key == idempotency_key,
                    )
                    .limit(1)
                )
                if existing is None:
                    raise
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
                    cost_estimate_usd=estimate,
                    covered_by_ledger_id=covered_by_ledger_id,
                    require_paid_credits=require_paid_credits,
                )
                reservation = self._reservation_from_ledger(
                    existing,
                    idempotency_key=idempotency_key,
                )

        if reservation is None:
            raise RuntimeError("Usage reservation could not be created")
        return reservation, self.points_store.get_balance(user_id)

    def mark_dispatched(self, reservation: ChargeReservation) -> bool:
        """Claim provider dispatch exactly once across workers."""
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
                return True
            if ledger.status in {
                "dispatched",
                "finalizing",
                "finalized",
                "failed",
                "cancelled",
            }:
                return False
            else:
                raise RuntimeError(f"Usage reservation cannot be dispatched from {ledger.status}")

    def get_finalized_result(
        self,
        reservation: ChargeReservation,
    ) -> dict[str, Any] | None:
        """Return a replay-safe result persisted with a finalized charge."""
        with self.db.session() as session:
            ledger = session.scalar(
                select(DbUsageLedger)
                .where(
                    DbUsageLedger.id == reservation.ledger_id,
                    DbUsageLedger.user_id == reservation.user_id,
                    DbUsageLedger.idempotency_key
                    == reservation.idempotency_key,
                    DbUsageLedger.status == "finalized",
                )
                .limit(1)
            )
            if ledger is None or not ledger.job_id:
                return None
            result_record = session.get(
                DbUsageResult,
                ledger.id,
            )
            if (
                result_record is None
                or result_record.job_id != ledger.job_id
            ):
                return None
            return (
                dict(result_record.payload)
                if isinstance(result_record.payload, dict)
                else None
            )

    def finalize(
        self,
        reservation: ChargeReservation,
        *,
        credits_charged: int,
        cost_usd: float,
        units: dict[str, Any] | None,
        result: dict[str, Any] | None = None,
        status: str = "finalized",
    ) -> int:
        if status != "finalized":
            raise ValueError("Failed provider output must use the refund path")
        actual_cost = float(cost_usd)
        if not math.isfinite(actual_cost) or actual_cost < 0:
            raise ValueError("Provider cost must be finite and non-negative")
        requested_credits = int(credits_charged)
        if requested_credits < 0:
            raise ValueError("credits_charged must be non-negative")

        final_credits = (
            0
            if reservation.reserved_credits == 0
            and reservation.min_credits == 0
            else max(requested_credits, int(reservation.min_credits))
        )
        refund_amount = max(
            0,
            reservation.reserved_credits - final_credits,
        )
        extra_charge = max(
            0,
            final_credits - reservation.reserved_credits,
        )
        paid_operation = reservation.paid_credits_reserved > 0
        settled_balance: int | None = None
        now = int(time.time())

        with self.db.session() as session:
            result_job: DbJob | None = None
            if result is not None:
                if not reservation.job_id:
                    raise RuntimeError(
                        "Replay-safe provider result requires a job",
                    )
                # Lock the job before its usage ledger. Workspace cleanup
                # deletes the job first and then updates its FK-linked
                # ledgers, so this order avoids a job/ledger deadlock.
                result_job = session.scalar(
                    select(DbJob)
                    .where(DbJob.id == reservation.job_id)
                    .with_for_update()
                    .limit(1)
                )
                if result_job is None:
                    raise RuntimeError(
                        "Replay-safe provider result job is missing",
                    )
            ledger = session.scalar(
                select(DbUsageLedger)
                .where(DbUsageLedger.id == reservation.ledger_id)
                .with_for_update()
                .limit(1)
            )
            if ledger is not None and ledger.status in {
                "reserved",
                "dispatched",
                # Recover a transaction interrupted by an older release.
                "finalizing",
            }:
                if extra_charge:
                    tx_id = make_idempotency_id(
                        "overage",
                        reservation.ledger_id,
                        str(extra_charge),
                    )
                    settled_balance, _ = (
                        self.points_store.spend_once_in_session(
                            session,
                            reservation.user_id,
                            extra_charge,
                            reason=reservation.action,
                            transaction_id=tx_id,
                            meta={
                                "ledger_id": reservation.ledger_id,
                                "action": reservation.action,
                                "kind": "overage",
                            },
                            require_paid=paid_operation,
                        )
                    )

                if refund_amount:
                    refund_tx = make_idempotency_id(
                        "refund",
                        reservation.ledger_id,
                        str(refund_amount),
                    )
                    settled_balance = (
                        self.points_store.refund_once_in_session(
                            session,
                            reservation.user_id,
                            refund_amount,
                            original_reason=reservation.action,
                            transaction_id=refund_tx,
                            meta={
                                "ledger_id": reservation.ledger_id,
                                "action": reservation.action,
                                "kind": "adjustment",
                            },
                            paid_credit_delta=(
                                refund_amount if paid_operation else 0
                            ),
                        )
                    )

                ledger.credits_charged = final_credits
                ledger.cost_usd = actual_cost
                resolved_units = (
                    dict(ledger.units)
                    if isinstance(ledger.units, dict)
                    else {}
                )
                if units:
                    resolved_units.update(units)
                ledger.units = resolved_units
                if result is not None:
                    if (
                        result_job is None
                        or ledger.job_id != result_job.id
                    ):
                        raise RuntimeError(
                            "Replay-safe provider result job changed",
                        )
                    existing_result = session.get(
                        DbUsageResult,
                        ledger.id,
                    )
                    if existing_result is None:
                        session.add(
                            DbUsageResult(
                                ledger_id=ledger.id,
                                job_id=result_job.id,
                                payload=dict(result),
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    elif (
                        existing_result.job_id != result_job.id
                        or existing_result.payload != result
                    ):
                        raise RuntimeError(
                            "Replay-safe provider result conflict",
                        )
                ledger.status = "finalized"
                ledger.updated_at = now
                if reservation.estimated_cost_usd > 0:
                    self.provider_budget_store.finalize_in_session(
                        session,
                        reservation.idempotency_key,
                        actual_usd=actual_cost,
                    )
            elif (
                ledger is not None
                and ledger.status == "finalized"
                and reservation.estimated_cost_usd > 0
            ):
                # Repair a terminal ledger whose provider budget settlement
                # was interrupted by an older split-transaction release.
                self.provider_budget_store.finalize_in_session(
                    session,
                    reservation.idempotency_key,
                    actual_usd=max(0.0, float(ledger.cost_usd)),
                )

        if settled_balance is not None:
            return settled_balance
        return self.points_store.get_balance(reservation.user_id)

    def fail(
        self,
        reservation: ChargeReservation,
        *,
        status: str,
        error: str | None = None,
        actual_cost_usd: float | None = None,
        units: dict[str, Any] | None = None,
        stale_before: int | None = None,
    ) -> int:
        if status not in {"failed", "cancelled"}:
            raise ValueError("Failure status must be failed or cancelled")
        if actual_cost_usd is not None:
            resolved_actual_cost = float(actual_cost_usd)
            if (
                not math.isfinite(resolved_actual_cost)
                or resolved_actual_cost < 0
            ):
                raise ValueError(
                    "Provider cost must be finite and non-negative",
                )
        else:
            resolved_actual_cost = None

        now = int(time.time())
        settled_balance: int | None = None
        with self.db.session() as session:
            ledger = session.scalar(
                select(DbUsageLedger)
                .where(DbUsageLedger.id == reservation.ledger_id)
                .with_for_update()
                .limit(1)
            )
            if ledger is None:
                current_status = None
            else:
                current_status = ledger.status
                if (
                    stale_before is not None
                    and (
                        int(ledger.updated_at) >= stale_before
                        or current_status
                        not in {
                            "reserved",
                            "dispatched",
                            "finalizing",
                            "failing_refund",
                            "failing_refund_dispatched",
                            "failing_charged",
                        }
                    )
                ):
                    current_status = None
            recoverable_statuses = {
                "reserved",
                "dispatched",
                "finalizing",
                "failing_refund",
                "failing_refund_dispatched",
                "failing_charged",
                # Compensate a completed provider step when the overall paid
                # job subsequently fails.
                "finalized",
            }
            if ledger is not None and current_status in recoverable_statuses:
                reserve_tx_id = make_idempotency_id(
                    "reserve",
                    reservation.idempotency_key,
                )
                transactions = list(
                    session.scalars(
                        select(DbPointTransaction)
                        .where(
                            DbPointTransaction.user_id
                            == reservation.user_id,
                            or_(
                                DbPointTransaction.id == reserve_tx_id,
                                (
                                    DbPointTransaction.meta[
                                        "ledger_id"
                                    ].as_string()
                                    == reservation.ledger_id
                                ),
                            ),
                        )
                        .with_for_update()
                    ).all()
                )
                if (
                    int(ledger.credits_reserved) > 0
                    and not any(
                        item.id == reserve_tx_id and int(item.delta) < 0
                        for item in transactions
                    )
                ):
                    raise RuntimeError(
                        "Usage reservation debit is missing",
                    )
                outstanding_charge = max(
                    0,
                    -sum(int(item.delta) for item in transactions),
                )
                outstanding_paid_charge = max(
                    0,
                    -sum(int(item.paid_delta) for item in transactions),
                )
                if outstanding_charge > 0:
                    refund_tx = make_idempotency_id(
                        "refund",
                        reservation.ledger_id,
                        "failed",
                    )
                    settled_balance = (
                        self.points_store.refund_once_in_session(
                            session,
                            reservation.user_id,
                            outstanding_charge,
                            original_reason=reservation.action,
                            transaction_id=refund_tx,
                            meta={
                                "ledger_id": reservation.ledger_id,
                                "action": reservation.action,
                                "kind": "failed",
                            },
                            paid_credit_delta=min(
                                outstanding_charge,
                                outstanding_paid_charge,
                            ),
                        )
                    )

                dispatched_statuses = {
                    "dispatched",
                    "finalizing",
                    "failing_refund_dispatched",
                    "failing_charged",
                    "finalized",
                }
                provider_cost = resolved_actual_cost
                if (
                    provider_cost is None
                    and current_status == "finalized"
                ):
                    provider_cost = max(0.0, float(ledger.cost_usd))
                if (
                    provider_cost is None
                    and current_status in dispatched_statuses
                ):
                    ledger_units = (
                        ledger.units
                        if isinstance(ledger.units, dict)
                        else {}
                    )
                    provider_cost = max(
                        0.0,
                        float(
                            ledger_units.get(
                                "guarded_cost_estimate_usd",
                                reservation.estimated_cost_usd
                                * settings.external_provider_price_safety_multiplier,
                            )
                        ),
                    )

                if reservation.estimated_cost_usd > 0:
                    if current_status in dispatched_statuses:
                        self.provider_budget_store.finalize_in_session(
                            session,
                            reservation.idempotency_key,
                            actual_usd=max(0.0, float(provider_cost or 0.0)),
                        )
                    else:
                        self.provider_budget_store.release_in_session(
                            session,
                            reservation.idempotency_key,
                        )

                resolved_units = (
                    dict(ledger.units)
                    if isinstance(ledger.units, dict)
                    else {}
                )
                if units:
                    resolved_units.update(units)
                resolved_units["failure_refunded_credits"] = (
                    outstanding_charge
                )
                resolved_units["failure_provider_dispatched"] = (
                    current_status in dispatched_statuses
                )
                ledger.units = resolved_units
                ledger.status = status
                ledger.credits_charged = 0
                if provider_cost is not None:
                    ledger.cost_usd = provider_cost
                ledger.error = error[:500] if error else None
                ledger.updated_at = now

        if settled_balance is not None:
            return settled_balance
        return self.points_store.get_balance(reservation.user_id)

    def refund_if_reserved(
        self,
        reservation: ChargeReservation,
        *,
        status: str,
        error: str | None = None,
    ) -> int:
        return self.fail(reservation, status=status, error=error)

    def fail_job_reservations(
        self,
        job_id: str,
        *,
        error: str,
    ) -> int:
        """Compensate every paid step before a stale active job is deleted."""
        with self.db.session() as session:
            ledgers = list(
                session.scalars(
                    select(DbUsageLedger)
                    .where(DbUsageLedger.job_id == job_id)
                    .order_by(
                        DbUsageLedger.created_at.asc(),
                        DbUsageLedger.id.asc(),
                    )
                ).all()
            )
            reservations = [
                self._reservation_from_ledger(
                    ledger,
                    idempotency_key=str(ledger.idempotency_key or ""),
                )
                for ledger in ledgers
                if ledger.idempotency_key
            ]

        settled = 0
        for reservation in reservations:
            self.fail(
                reservation,
                status="failed",
                error=error,
            )
            settled += 1
        return settled

    def reconcile_stale_reservations(
        self,
        *,
        stale_before: int,
        limit: int = 100,
    ) -> int:
        """Refund stale provider claims left behind by a crashed worker."""
        if stale_before <= 0:
            raise ValueError("stale_before must be positive")
        if limit <= 0 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.db.session() as session:
            ledgers = list(
                session.scalars(
                    select(DbUsageLedger)
                    .where(
                        DbUsageLedger.status.in_(
                            {
                                "reserved",
                                "dispatched",
                                "finalizing",
                                "failing_refund",
                                "failing_refund_dispatched",
                                "failing_charged",
                            }
                        ),
                        DbUsageLedger.updated_at < stale_before,
                    )
                    .order_by(
                        DbUsageLedger.updated_at.asc(),
                        DbUsageLedger.id.asc(),
                    )
                    .limit(limit)
                ).all()
            )
            reservations = [
                self._reservation_from_ledger(
                    ledger,
                    idempotency_key=str(ledger.idempotency_key or ""),
                )
                for ledger in ledgers
                if ledger.idempotency_key
            ]
            orphan_budget_keys = list(
                session.scalars(
                    select(
                        DbProviderBudgetReservation.idempotency_key,
                    )
                    .outerjoin(
                        DbUsageLedger,
                        DbUsageLedger.idempotency_key
                        == (
                            DbProviderBudgetReservation.idempotency_key
                        ),
                    )
                    .where(
                        DbProviderBudgetReservation.status == "reserved",
                        DbProviderBudgetReservation.updated_at
                        < stale_before,
                        DbUsageLedger.id.is_(None),
                    )
                    .order_by(
                        DbProviderBudgetReservation.updated_at.asc(),
                        DbProviderBudgetReservation.idempotency_key.asc(),
                    )
                    .limit(limit)
                ).all()
            )
            reconciled_orphan_budgets = 0
            for idempotency_key in orphan_budget_keys:
                reserve_tx_id = make_idempotency_id(
                    "reserve",
                    idempotency_key,
                )
                reserve_debit = session.scalar(
                    select(DbPointTransaction)
                    .where(DbPointTransaction.id == reserve_tx_id)
                    .with_for_update()
                    .limit(1)
                )
                if reserve_debit is not None:
                    if int(reserve_debit.delta) >= 0:
                        raise RuntimeError(
                            "Orphan usage reserve transaction is not a debit",
                        )
                    debit_meta = (
                        reserve_debit.meta
                        if isinstance(reserve_debit.meta, dict)
                        else {}
                    )
                    recovered_ledger_id = debit_meta.get("ledger_id")
                    if (
                        not isinstance(recovered_ledger_id, str)
                        or len(recovered_ledger_id) != 32
                    ):
                        raise RuntimeError(
                            "Orphan usage debit has no recoverable ledger",
                        )
                    linked_transactions = list(
                        session.scalars(
                            select(DbPointTransaction)
                            .where(
                                DbPointTransaction.user_id
                                == reserve_debit.user_id,
                                or_(
                                    DbPointTransaction.id
                                    == reserve_tx_id,
                                    (
                                        DbPointTransaction.meta[
                                            "ledger_id"
                                        ].as_string()
                                        == recovered_ledger_id
                                    ),
                                ),
                            )
                            .order_by(DbPointTransaction.id.asc())
                            .with_for_update()
                        ).all()
                    )
                else:
                    recovered_ledger_id = None
                    linked_transactions = []

                # A concurrent reserve recovery may have recreated the ledger
                # while this stale candidate was waiting on its debit lock.
                if session.scalar(
                    select(DbUsageLedger.id)
                    .where(
                        DbUsageLedger.idempotency_key
                        == idempotency_key,
                    )
                    .limit(1)
                ) is not None:
                    continue

                if reserve_debit is not None:
                    if recovered_ledger_id is None:
                        raise RuntimeError(
                            "Orphan usage debit has no recoverable ledger",
                        )
                    outstanding_charge = max(
                        0,
                        -sum(
                            int(item.delta)
                            for item in linked_transactions
                        ),
                    )
                    outstanding_paid_charge = max(
                        0,
                        -sum(
                            int(item.paid_delta)
                            for item in linked_transactions
                        ),
                    )
                    if outstanding_paid_charge > outstanding_charge:
                        raise RuntimeError(
                            "Orphan usage debit has invalid paid allocation",
                        )
                    if outstanding_charge > 0:
                        refund_tx = make_idempotency_id(
                            "refund",
                            recovered_ledger_id,
                            "stale_orphan",
                        )
                        self.points_store.refund_once_in_session(
                            session,
                            reserve_debit.user_id,
                            outstanding_charge,
                            original_reason=reserve_debit.reason,
                            transaction_id=refund_tx,
                            meta={
                                "ledger_id": recovered_ledger_id,
                                "action": reserve_debit.reason,
                                "kind": "stale_orphan",
                            },
                            paid_credit_delta=(
                                outstanding_paid_charge
                            ),
                        )

                orphan = session.scalar(
                    select(DbProviderBudgetReservation)
                    .where(
                        DbProviderBudgetReservation.idempotency_key
                        == idempotency_key,
                    )
                    .with_for_update()
                    .limit(1)
                )
                if (
                    orphan is None
                    or orphan.status != "reserved"
                    or int(orphan.updated_at) >= stale_before
                ):
                    continue
                # The budget lock may have waited for a concurrent reserve
                # transaction that also inserted its ledger. Re-check after
                # the lock so a newly valid reservation is never released.
                if session.scalar(
                    select(DbUsageLedger.id)
                    .where(
                        DbUsageLedger.idempotency_key
                        == idempotency_key,
                    )
                    .limit(1)
                ) is not None:
                    continue
                self.provider_budget_store.release_in_session(
                    session,
                    idempotency_key,
                )
                reconciled_orphan_budgets += 1

        for reservation in reservations:
            self.fail(
                reservation,
                status="failed",
                error="Stale paid provider dispatch reconciled",
                stale_before=stale_before,
            )
        return len(reservations) + reconciled_orphan_budgets

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
                        DbUsageLedger.idempotency_key
                        == root_idempotency_key,
                        (
                            DbUsageLedger.units[
                                "retry_root_idempotency_key"
                            ].as_string()
                            == root_idempotency_key
                        ),
                    )
                )
            ).all()
        )
        if not candidates:
            return root_idempotency_key, 0

        def retry_attempt(ledger: DbUsageLedger) -> int:
            units = (
                ledger.units
                if isinstance(ledger.units, dict)
                else {}
            )
            raw_attempt = units.get("retry_attempt", 0)
            if (
                not isinstance(raw_attempt, int)
                or isinstance(raw_attempt, bool)
                or raw_attempt < 0
            ):
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
