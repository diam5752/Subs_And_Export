"""Atomic usage reservation operations."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import DbPointTransaction, DbUsageLedger
from backend.app.services.points import make_idempotency_id
from backend.app.services.usage_ledger_base import UsageLedgerMixinBase
from backend.app.services.usage_types import ChargeReservation


@dataclass(frozen=True)
class _ReservationParameters:
    user_id: str
    job_id: str | None
    action: str
    provider: str
    endpoint: str | None
    model: str | None
    tier: str | None
    credits: int
    min_credits: int
    cost_estimate_usd: float
    currency: str
    covered_by_ledger_id: str | None
    require_paid_credits: bool | None
    allow_terminal_retry: bool


@dataclass(frozen=True)
class _ReservationRequest:
    user_id: str
    job_id: str | None
    action: str
    provider: str
    endpoint: str | None
    model: str | None
    tier: str | None
    credits: int
    min_credits: int
    estimate: float
    guarded_estimate: float
    currency: str
    covered_by_ledger_id: str | None
    require_paid_credits: bool | None
    requires_paid: bool
    allow_terminal_retry: bool


@dataclass
class _ReservationState:
    root_idempotency_key: str
    idempotency_key: str
    ledger_id: str
    reserve_tx_id: str
    resolved_units: dict[str, Any]


def _validate_reservation_credits(credits: int, covered_by_ledger_id: str | None) -> None:
    if credits < 0 or (credits == 0 and not covered_by_ledger_id):
        raise ValueError("credits must be positive unless covered by a paid reservation")


def _validate_idempotency_key(idempotency_key: str) -> None:
    if not idempotency_key:
        raise ValueError("idempotency_key is required")


def _validated_provider_estimate(value: float, *, label: str) -> float:
    estimate = float(value)
    if not math.isfinite(estimate) or estimate < 0:
        raise ValueError(f"{label} must be finite and non-negative")
    return estimate


def _reservation_requires_paid(
    *,
    estimate: float,
    provider: str,
    require_paid_credits: bool | None,
) -> bool:
    normalized_provider = provider.strip().lower()
    provider_requires_paid = estimate > 0 and normalized_provider not in {"local", "mock"}
    return provider_requires_paid or require_paid_credits is True


def _recovered_debit_ledger_id(existing_debit: DbPointTransaction) -> str:
    debit_meta = existing_debit.meta if isinstance(existing_debit.meta, dict) else {}
    ledger_id = debit_meta.get("ledger_id")
    if not isinstance(ledger_id, str) or len(ledger_id) != 32:
        raise RuntimeError("Existing usage debit has no recoverable ledger")
    return ledger_id


def _validate_recovered_debit_amounts(
    transactions: list[DbPointTransaction],
    *,
    credits: int,
    requires_paid: bool,
) -> None:
    net_charge = max(0, -sum(int(item.delta) for item in transactions))
    net_paid_charge = max(0, -sum(int(item.paid_delta) for item in transactions))
    invalid_paid_charge = requires_paid and net_paid_charge != credits
    if net_charge != credits or invalid_paid_charge:
        raise RuntimeError("Existing usage debit is not outstanding")


class UsageReservationMixin(UsageLedgerMixinBase):
    def _prepare_reservation_request(
        self,
        parameters: _ReservationParameters,
    ) -> _ReservationRequest:
        _validate_reservation_credits(parameters.credits, parameters.covered_by_ledger_id)
        estimate = _validated_provider_estimate(parameters.cost_estimate_usd, label="Provider cost estimate")
        if parameters.covered_by_ledger_id:
            self._validate_coverage(
                covered_by_ledger_id=parameters.covered_by_ledger_id,
                user_id=parameters.user_id,
                job_id=parameters.job_id,
            )
        requires_paid = _reservation_requires_paid(
            estimate=estimate,
            provider=parameters.provider,
            require_paid_credits=parameters.require_paid_credits,
        )
        guarded_estimate = _validated_provider_estimate(
            estimate * settings.external_provider_price_safety_multiplier,
            label="Guarded provider cost estimate",
        )
        return _ReservationRequest(
            user_id=parameters.user_id,
            job_id=parameters.job_id,
            action=parameters.action,
            provider=parameters.provider,
            endpoint=parameters.endpoint,
            model=parameters.model,
            tier=parameters.tier,
            credits=parameters.credits,
            min_credits=parameters.min_credits,
            estimate=estimate,
            guarded_estimate=guarded_estimate,
            currency=parameters.currency,
            covered_by_ledger_id=parameters.covered_by_ledger_id,
            require_paid_credits=parameters.require_paid_credits,
            requires_paid=requires_paid,
            allow_terminal_retry=parameters.allow_terminal_retry,
        )

    @staticmethod
    def _initial_reservation_state(
        request: _ReservationRequest,
        *,
        units: dict[str, Any] | None,
        idempotency_key: str,
    ) -> _ReservationState:
        resolved_units = dict(units or {})
        resolved_units["cost_estimate_usd"] = request.estimate
        resolved_units["guarded_cost_estimate_usd"] = request.guarded_estimate
        resolved_units["paid_credits_reserved"] = request.credits if request.requires_paid else 0
        resolved_units["require_paid_credits"] = request.requires_paid
        if request.covered_by_ledger_id:
            resolved_units["covered_by_ledger_id"] = request.covered_by_ledger_id
        return _ReservationState(
            root_idempotency_key=idempotency_key,
            idempotency_key=idempotency_key,
            ledger_id=make_idempotency_id("ledger", idempotency_key),
            reserve_tx_id=make_idempotency_id("reserve", idempotency_key),
            resolved_units=resolved_units,
        )

    def _apply_terminal_retry(
        self,
        session: Session,
        request: _ReservationRequest,
        state: _ReservationState,
    ) -> None:
        if not request.allow_terminal_retry:
            return
        idempotency_key, retry_attempt = self._resolve_retry_idempotency_in_session(
            session,
            state.root_idempotency_key,
        )
        state.idempotency_key = idempotency_key
        state.resolved_units["retry_root_idempotency_key"] = state.root_idempotency_key
        state.resolved_units["retry_attempt"] = retry_attempt
        state.ledger_id = make_idempotency_id("ledger", idempotency_key)
        state.reserve_tx_id = make_idempotency_id("reserve", idempotency_key)

    def _validate_existing_ledger(
        self,
        ledger: DbUsageLedger,
        request: _ReservationRequest,
        state: _ReservationState,
    ) -> ChargeReservation:
        self._validate_existing_reservation(
            ledger,
            user_id=request.user_id,
            job_id=request.job_id,
            action=request.action,
            provider=request.provider,
            model=request.model,
            tier=request.tier,
            credits=request.credits,
            min_credits=request.min_credits,
            cost_estimate_usd=request.estimate,
            covered_by_ledger_id=request.covered_by_ledger_id,
            require_paid_credits=request.require_paid_credits,
        )
        return cast(
            ChargeReservation,
            self._reservation_from_ledger(
                ledger,
                idempotency_key=state.idempotency_key,
            ),
        )

    def _recover_existing_debit(
        self,
        session: Session,
        request: _ReservationRequest,
        state: _ReservationState,
    ) -> None:
        if request.credits <= 0:
            return
        existing_debit = session.get(DbPointTransaction, state.reserve_tx_id)
        if existing_debit is None:
            return
        state.ledger_id = _recovered_debit_ledger_id(existing_debit)
        linked_transactions = list(
            session.scalars(
                select(DbPointTransaction)
                .where(
                    DbPointTransaction.user_id == request.user_id,
                    or_(
                        DbPointTransaction.id == state.reserve_tx_id,
                        DbPointTransaction.meta["ledger_id"].as_string() == state.ledger_id,
                    ),
                )
                .with_for_update()
            ).all()
        )
        _validate_recovered_debit_amounts(
            linked_transactions,
            credits=request.credits,
            requires_paid=request.requires_paid,
        )

    def _spend_reserved_credits(
        self,
        session: Session,
        request: _ReservationRequest,
        state: _ReservationState,
    ) -> None:
        if request.credits <= 0:
            return
        self.points_store.spend_once_in_session(
            session,
            request.user_id,
            request.credits,
            reason=request.action,
            transaction_id=state.reserve_tx_id,
            meta={
                "ledger_id": state.ledger_id,
                "action": request.action,
                "provider": request.provider,
                "model": request.model,
                "tier": request.tier,
                "kind": "reserve",
                "funding_source": "paid" if request.requires_paid else "mixed",
            },
            require_paid=request.requires_paid,
        )

    def _reserve_provider_budget(
        self,
        session: Session,
        request: _ReservationRequest,
        state: _ReservationState,
    ) -> None:
        if not request.requires_paid:
            return
        budget = self.provider_budget_store.reserve_in_session(
            session,
            idempotency_key=state.idempotency_key,
            estimated_usd=request.guarded_estimate,
            daily_limit_usd=settings.external_provider_daily_budget_usd,
            monthly_limit_usd=settings.external_provider_monthly_budget_usd,
        )
        if budget.status != "reserved":
            raise RuntimeError("Provider budget idempotency key is settled")

    def _create_reservation_ledger(
        self,
        session: Session,
        request: _ReservationRequest,
        state: _ReservationState,
        *,
        now: int,
    ) -> ChargeReservation:
        record = DbUsageLedger(
            id=state.ledger_id,
            user_id=request.user_id,
            job_id=request.job_id,
            action=request.action,
            provider=request.provider,
            endpoint=request.endpoint,
            model=request.model,
            tier=request.tier,
            units=state.resolved_units,
            cost_usd=request.estimate,
            credits_reserved=request.credits,
            paid_credits_reserved=request.credits if request.requires_paid else 0,
            credits_charged=0,
            min_credits=request.min_credits,
            currency=request.currency,
            status="reserved",
            error=None,
            idempotency_key=state.idempotency_key,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        return cast(
            ChargeReservation,
            self._reservation_from_ledger(
                record,
                idempotency_key=state.idempotency_key,
            ),
        )

    def _reserve_in_session(
        self,
        session: Session,
        request: _ReservationRequest,
        state: _ReservationState,
        *,
        now: int,
    ) -> ChargeReservation:
        self._apply_terminal_retry(session, request, state)
        existing = session.scalar(
            select(DbUsageLedger).where(DbUsageLedger.idempotency_key == state.idempotency_key).limit(1)
        )
        if existing is not None:
            return self._validate_existing_ledger(existing, request, state)
        self._recover_existing_debit(session, request, state)
        self._spend_reserved_credits(session, request, state)
        self._reserve_provider_budget(session, request, state)
        return self._create_reservation_ledger(session, request, state, now=now)

    def _recover_integrity_conflict(
        self,
        request: _ReservationRequest,
        state: _ReservationState,
        error: IntegrityError,
    ) -> ChargeReservation:
        with self.db.session() as session:
            existing = session.scalar(
                select(DbUsageLedger).where(DbUsageLedger.idempotency_key == state.idempotency_key).limit(1)
            )
            if existing is None:
                raise error
            return self._validate_existing_ledger(existing, request, state)

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
        _validate_idempotency_key(idempotency_key)
        request = self._prepare_reservation_request(
            _ReservationParameters(
                user_id=user_id,
                job_id=job_id,
                action=action,
                provider=provider,
                endpoint=endpoint,
                model=model,
                tier=tier,
                credits=credits,
                min_credits=min_credits,
                cost_estimate_usd=cost_estimate_usd,
                currency=currency,
                covered_by_ledger_id=covered_by_ledger_id,
                require_paid_credits=require_paid_credits,
                allow_terminal_retry=allow_terminal_retry,
            )
        )
        state = self._initial_reservation_state(
            request,
            units=units,
            idempotency_key=idempotency_key,
        )
        try:
            with self.db.session() as session:
                reservation = self._reserve_in_session(session, request, state, now=int(time.time()))
        except IntegrityError as error:
            reservation = self._recover_integrity_conflict(request, state, error)
        return reservation, self.points_store.get_balance(user_id)
