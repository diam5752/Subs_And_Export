"""Dispatch and final settlement operations."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import (
    DbJob,
    DbPointTransaction,
    DbUsageLedger,
    DbUsageResult,
)
from backend.app.services.points import make_idempotency_id
from backend.app.services.usage_ledger_base import UsageLedgerMixinBase
from backend.app.services.usage_types import ChargeReservation

_ACTIVE_FINALIZATION_STATUSES = {"reserved", "dispatched", "finalizing"}
_STALE_FAILURE_STATUSES = {
    "reserved",
    "dispatched",
    "finalizing",
    "failing_refund",
    "failing_refund_dispatched",
    "failing_charged",
}
_RECOVERABLE_FAILURE_STATUSES = _STALE_FAILURE_STATUSES | {"finalized"}
_DISPATCHED_FAILURE_STATUSES = {
    "dispatched",
    "finalizing",
    "failing_refund_dispatched",
    "failing_charged",
    "finalized",
}


@dataclass(frozen=True)
class _FinalizePlan:
    actual_cost: float
    final_credits: int
    refund_amount: int
    extra_charge: int
    paid_operation: bool


def _outstanding_reservation_charges(transactions: Sequence[DbPointTransaction]) -> tuple[int, int]:
    outstanding_charge = max(0, -sum(int(item.delta) for item in transactions))
    outstanding_paid_charge = max(0, -sum(int(item.paid_delta) for item in transactions))
    return outstanding_charge, outstanding_paid_charge


class UsageSettlementMixin(UsageLedgerMixinBase):
    def mark_dispatched(self, reservation: ChargeReservation) -> bool:
        """Claim provider dispatch exactly once across workers."""
        now = int(time.time())
        with self.db.session() as session:
            ledger = session.scalar(
                select(DbUsageLedger).where(DbUsageLedger.id == reservation.ledger_id).with_for_update().limit(1)
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
                    DbUsageLedger.idempotency_key == reservation.idempotency_key,
                    DbUsageLedger.status == "finalized",
                )
                .limit(1)
            )
            if ledger is None or not ledger.job_id:
                return None
            result_record = session.get(DbUsageResult, ledger.id)
            if result_record is None or result_record.job_id != ledger.job_id:
                return None
            return dict(result_record.payload) if isinstance(result_record.payload, dict) else None

    @staticmethod
    def _prepare_finalize_plan(
        reservation: ChargeReservation,
        *,
        credits_charged: int,
        cost_usd: float,
        status: str,
    ) -> _FinalizePlan:
        if status != "finalized":
            raise ValueError("Failed provider output must use the refund path")
        actual_cost = float(cost_usd)
        if not math.isfinite(actual_cost) or actual_cost < 0:
            raise ValueError("Provider cost must be finite and non-negative")
        requested_credits = int(credits_charged)
        if requested_credits < 0:
            raise ValueError("credits_charged must be non-negative")
        no_charge_allowed = reservation.reserved_credits == 0 and reservation.min_credits == 0
        final_credits = 0 if no_charge_allowed else max(requested_credits, int(reservation.min_credits))
        return _FinalizePlan(
            actual_cost=actual_cost,
            final_credits=final_credits,
            refund_amount=max(0, reservation.reserved_credits - final_credits),
            extra_charge=max(0, final_credits - reservation.reserved_credits),
            paid_operation=reservation.paid_credits_reserved > 0,
        )

    @staticmethod
    def _lock_result_job(
        session: Session,
        reservation: ChargeReservation,
        result: dict[str, Any] | None,
    ) -> DbJob | None:
        if result is None:
            return None
        if not reservation.job_id:
            raise RuntimeError("Replay-safe provider result requires a job")
        # Lock the job before its ledger to match workspace-cleanup lock order.
        result_job = session.scalar(select(DbJob).where(DbJob.id == reservation.job_id).with_for_update().limit(1))
        if result_job is None:
            raise RuntimeError("Replay-safe provider result job is missing")
        return result_job

    def _apply_finalize_adjustments(
        self,
        session: Session,
        reservation: ChargeReservation,
        plan: _FinalizePlan,
    ) -> int | None:
        settled_balance: int | None = None
        if plan.extra_charge:
            tx_id = make_idempotency_id(
                "overage",
                reservation.ledger_id,
                str(plan.extra_charge),
            )
            settled_balance, _ = self.points_store.spend_once_in_session(
                session,
                reservation.user_id,
                plan.extra_charge,
                reason=reservation.action,
                transaction_id=tx_id,
                meta={
                    "ledger_id": reservation.ledger_id,
                    "action": reservation.action,
                    "kind": "overage",
                },
                require_paid=plan.paid_operation,
            )
        if plan.refund_amount:
            refund_tx = make_idempotency_id(
                "refund",
                reservation.ledger_id,
                str(plan.refund_amount),
            )
            settled_balance = self.points_store.refund_once_in_session(
                session,
                reservation.user_id,
                plan.refund_amount,
                original_reason=reservation.action,
                transaction_id=refund_tx,
                meta={
                    "ledger_id": reservation.ledger_id,
                    "action": reservation.action,
                    "kind": "adjustment",
                },
                paid_credit_delta=(plan.refund_amount if plan.paid_operation else 0),
            )
        return settled_balance

    @staticmethod
    def _persist_replay_result(
        session: Session,
        *,
        ledger: DbUsageLedger,
        result_job: DbJob | None,
        result: dict[str, Any] | None,
        now: int,
    ) -> None:
        if result is None:
            return
        if result_job is None or ledger.job_id != result_job.id:
            raise RuntimeError("Replay-safe provider result job changed")
        existing_result = session.get(DbUsageResult, ledger.id)
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
            return
        if existing_result.job_id != result_job.id or existing_result.payload != result:
            raise RuntimeError("Replay-safe provider result conflict")

    def _finalize_active_ledger(
        self,
        session: Session,
        *,
        ledger: DbUsageLedger,
        reservation: ChargeReservation,
        plan: _FinalizePlan,
        units: dict[str, Any] | None,
        result_job: DbJob | None,
        result: dict[str, Any] | None,
        now: int,
    ) -> int | None:
        settled_balance = self._apply_finalize_adjustments(session, reservation, plan)
        ledger.credits_charged = plan.final_credits
        ledger.cost_usd = plan.actual_cost
        resolved_units = dict(ledger.units) if isinstance(ledger.units, dict) else {}
        if units:
            resolved_units.update(units)
        ledger.units = resolved_units
        self._persist_replay_result(
            session,
            ledger=ledger,
            result_job=result_job,
            result=result,
            now=now,
        )
        ledger.status = "finalized"
        ledger.updated_at = now
        if reservation.estimated_cost_usd > 0:
            self.provider_budget_store.finalize_in_session(
                session,
                reservation.idempotency_key,
                actual_usd=plan.actual_cost,
            )
        return settled_balance

    def _repair_finalized_budget(
        self,
        session: Session,
        *,
        ledger: DbUsageLedger | None,
        reservation: ChargeReservation,
    ) -> None:
        if ledger is None or ledger.status != "finalized":
            return
        if reservation.estimated_cost_usd <= 0:
            return
        self.provider_budget_store.finalize_in_session(
            session,
            reservation.idempotency_key,
            actual_usd=max(0.0, float(ledger.cost_usd)),
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
        plan = self._prepare_finalize_plan(
            reservation,
            credits_charged=credits_charged,
            cost_usd=cost_usd,
            status=status,
        )
        settled_balance: int | None = None
        now = int(time.time())
        with self.db.session() as session:
            result_job = self._lock_result_job(session, reservation, result)
            ledger = session.scalar(
                select(DbUsageLedger).where(DbUsageLedger.id == reservation.ledger_id).with_for_update().limit(1)
            )
            if ledger is not None and ledger.status in _ACTIVE_FINALIZATION_STATUSES:
                settled_balance = self._finalize_active_ledger(
                    session,
                    ledger=ledger,
                    reservation=reservation,
                    plan=plan,
                    units=units,
                    result_job=result_job,
                    result=result,
                    now=now,
                )
            else:
                self._repair_finalized_budget(
                    session,
                    ledger=ledger,
                    reservation=reservation,
                )
        if settled_balance is not None:
            return settled_balance
        return self.points_store.get_balance(reservation.user_id)

    @staticmethod
    def _validated_actual_cost(actual_cost_usd: float | None) -> float | None:
        if actual_cost_usd is None:
            return None
        resolved_actual_cost = float(actual_cost_usd)
        if not math.isfinite(resolved_actual_cost) or resolved_actual_cost < 0:
            raise ValueError("Provider cost must be finite and non-negative")
        return resolved_actual_cost

    @staticmethod
    def _recoverable_failure_status(
        ledger: DbUsageLedger | None,
        *,
        stale_before: int | None,
    ) -> str | None:
        if ledger is None:
            return None
        current_status = str(ledger.status)
        if stale_before is None:
            return current_status
        if int(ledger.updated_at) >= stale_before:
            return None
        if current_status not in _STALE_FAILURE_STATUSES:
            return None
        return current_status

    @staticmethod
    def _locked_reservation_transactions(
        session: Session,
        reservation: ChargeReservation,
    ) -> tuple[str, list[DbPointTransaction]]:
        reserve_tx_id = make_idempotency_id(
            "reserve",
            reservation.idempotency_key,
        )
        transactions = list(
            session.scalars(
                select(DbPointTransaction)
                .where(
                    DbPointTransaction.user_id == reservation.user_id,
                    or_(
                        DbPointTransaction.id == reserve_tx_id,
                        DbPointTransaction.meta["ledger_id"].as_string() == reservation.ledger_id,
                    ),
                )
                .with_for_update()
            ).all()
        )
        return reserve_tx_id, transactions

    @staticmethod
    def _validate_reservation_debit(
        ledger: DbUsageLedger,
        reserve_tx_id: str,
        transactions: Sequence[DbPointTransaction],
    ) -> None:
        if int(ledger.credits_reserved) <= 0:
            return
        has_debit = any(item.id == reserve_tx_id and int(item.delta) < 0 for item in transactions)
        if not has_debit:
            raise RuntimeError("Usage reservation debit is missing")

    def _refund_failed_charge(
        self,
        session: Session,
        reservation: ChargeReservation,
        *,
        outstanding_charge: int,
        outstanding_paid_charge: int,
    ) -> int | None:
        if outstanding_charge <= 0:
            return None
        refund_tx = make_idempotency_id(
            "refund",
            reservation.ledger_id,
            "failed",
        )
        return self.points_store.refund_once_in_session(
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
            paid_credit_delta=min(outstanding_charge, outstanding_paid_charge),
        )

    @staticmethod
    def _failure_provider_cost(
        ledger: DbUsageLedger,
        reservation: ChargeReservation,
        *,
        current_status: str,
        resolved_actual_cost: float | None,
    ) -> float | None:
        if resolved_actual_cost is not None:
            return resolved_actual_cost
        if current_status == "finalized":
            return max(0.0, float(ledger.cost_usd))
        if current_status not in _DISPATCHED_FAILURE_STATUSES:
            return None
        ledger_units = ledger.units if isinstance(ledger.units, dict) else {}
        guarded_estimate = ledger_units.get(
            "guarded_cost_estimate_usd",
            reservation.estimated_cost_usd * settings.external_provider_price_safety_multiplier,
        )
        return max(0.0, float(guarded_estimate))

    def _settle_failure_provider_budget(
        self,
        session: Session,
        reservation: ChargeReservation,
        *,
        current_status: str,
        provider_cost: float | None,
    ) -> None:
        if reservation.estimated_cost_usd <= 0:
            return
        if current_status in _DISPATCHED_FAILURE_STATUSES:
            self.provider_budget_store.finalize_in_session(
                session,
                reservation.idempotency_key,
                actual_usd=max(0.0, float(provider_cost or 0.0)),
            )
            return
        self.provider_budget_store.release_in_session(
            session,
            reservation.idempotency_key,
        )

    @staticmethod
    def _update_failed_ledger(
        ledger: DbUsageLedger,
        *,
        status: str,
        error: str | None,
        units: dict[str, Any] | None,
        outstanding_charge: int,
        provider_dispatched: bool,
        provider_cost: float | None,
        now: int,
    ) -> None:
        resolved_units = dict(ledger.units) if isinstance(ledger.units, dict) else {}
        if units:
            resolved_units.update(units)
        resolved_units["failure_refunded_credits"] = outstanding_charge
        resolved_units["failure_provider_dispatched"] = provider_dispatched
        ledger.units = resolved_units
        ledger.status = status
        ledger.credits_charged = 0
        if provider_cost is not None:
            ledger.cost_usd = provider_cost
        ledger.error = error[:500] if error else None
        ledger.updated_at = now

    def _fail_recoverable_ledger(
        self,
        session: Session,
        *,
        ledger: DbUsageLedger,
        reservation: ChargeReservation,
        current_status: str,
        status: str,
        error: str | None,
        units: dict[str, Any] | None,
        resolved_actual_cost: float | None,
        now: int,
    ) -> int | None:
        reserve_tx_id, transactions = self._locked_reservation_transactions(
            session,
            reservation,
        )
        self._validate_reservation_debit(ledger, reserve_tx_id, transactions)
        outstanding_charge, outstanding_paid_charge = _outstanding_reservation_charges(transactions)
        settled_balance = self._refund_failed_charge(
            session,
            reservation,
            outstanding_charge=outstanding_charge,
            outstanding_paid_charge=outstanding_paid_charge,
        )
        provider_cost = self._failure_provider_cost(
            ledger,
            reservation,
            current_status=current_status,
            resolved_actual_cost=resolved_actual_cost,
        )
        self._settle_failure_provider_budget(
            session,
            reservation,
            current_status=current_status,
            provider_cost=provider_cost,
        )
        self._update_failed_ledger(
            ledger,
            status=status,
            error=error,
            units=units,
            outstanding_charge=outstanding_charge,
            provider_dispatched=current_status in _DISPATCHED_FAILURE_STATUSES,
            provider_cost=provider_cost,
            now=now,
        )
        return settled_balance

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
        resolved_actual_cost = self._validated_actual_cost(actual_cost_usd)
        settled_balance: int | None = None
        now = int(time.time())
        with self.db.session() as session:
            ledger = session.scalar(
                select(DbUsageLedger).where(DbUsageLedger.id == reservation.ledger_id).with_for_update().limit(1)
            )
            current_status = self._recoverable_failure_status(
                ledger,
                stale_before=stale_before,
            )
            if ledger is not None and current_status is not None and current_status in _RECOVERABLE_FAILURE_STATUSES:
                settled_balance = self._fail_recoverable_ledger(
                    session,
                    ledger=ledger,
                    reservation=reservation,
                    current_status=current_status,
                    status=status,
                    error=error,
                    units=units,
                    resolved_actual_cost=resolved_actual_cost,
                    now=now,
                )
        if settled_balance is not None:
            return settled_balance
        return self.points_store.get_balance(reservation.user_id)
