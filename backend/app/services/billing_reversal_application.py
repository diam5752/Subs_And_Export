"""Transactional Stripe reversal parsing and aggregate application helpers."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_service_base import BillingServiceMixinBase
from backend.app.services.billing_types import (
    _ACTIVE_REFUND_STATUSES,
    _CHARGE_REFUND_SUMMARY_STATUS,
    _INACTIVE_REFUND_STATUSES,
    _REFUND_OBJECT_EVENT_TYPES,
    BillingProviderError,
    BillingValidationError,
    StripeRefundState,
)
from backend.app.services.financial_records import financial_retention_deadline
from backend.app.services.points import make_idempotency_id


@dataclass(frozen=True, slots=True)
class ParsedReversalEvent:
    payment_intent_id: str
    purchase_id: str
    provider_reversal_id: str
    currency: str
    amount_cents: int
    kind: str
    status: str
    active: bool
    is_charge_refund_summary: bool
    is_refund_object: bool


@dataclass(frozen=True, slots=True)
class ReversalAggregate:
    refunded_cents: int
    active_reversal_cents: int
    dispute_active: bool
    desired_reversal: int


class BillingReversalApplicationMixin(BillingServiceMixinBase):
    def _validated_reversal_event(
        self,
        obj: dict[str, Any],
        *,
        event_type: str,
        purchase_id: str | None,
        resolved_payment_intent_id: str | None,
        authoritative_refunds: tuple[StripeRefundState, ...] | None,
    ) -> ParsedReversalEvent:
        payment_intent_id, validated_purchase_id, provider_reversal_id, currency = self._validated_reversal_identity(
            obj,
            purchase_id=purchase_id,
            resolved_payment_intent_id=resolved_payment_intent_id,
        )
        is_charge_summary, is_refund_object, kind = self._reversal_classification(event_type)
        self._validate_refund_reconciliation_presence(
            is_charge_summary=is_charge_summary,
            authoritative_refunds=authoritative_refunds,
        )
        amount_cents = self._reversal_amount(
            obj,
            is_charge_summary=is_charge_summary,
        )
        status, active = self._reversal_object_state(
            obj,
            event_type=event_type,
            provider_reversal_id=provider_reversal_id,
            is_charge_summary=is_charge_summary,
            is_refund_object=is_refund_object,
        )
        return ParsedReversalEvent(
            payment_intent_id=payment_intent_id,
            purchase_id=validated_purchase_id,
            provider_reversal_id=provider_reversal_id,
            currency=currency,
            amount_cents=amount_cents,
            kind=kind,
            status=status,
            active=active,
            is_charge_refund_summary=is_charge_summary,
            is_refund_object=is_refund_object,
        )

    def _validated_reversal_identity(
        self,
        obj: dict[str, Any],
        *,
        purchase_id: str | None,
        resolved_payment_intent_id: str | None,
    ) -> tuple[str, str, str, str]:
        payment_intent_id = self._stripe_id(obj.get("payment_intent")) or resolved_payment_intent_id or ""
        if not payment_intent_id:
            raise BillingProviderError("Local reversal PaymentIntent is not available yet")
        if not purchase_id:
            raise BillingProviderError("Local reversal purchase is not available yet")
        provider_reversal_id = self._stripe_id(obj.get("id"))
        if not provider_reversal_id or len(provider_reversal_id) > 255:
            raise BillingValidationError("Reversal object id is invalid")
        currency = str(obj.get("currency") or "").lower().strip()
        if not currency or len(currency) > 8:
            raise BillingValidationError("Reversal currency is invalid")
        return payment_intent_id, purchase_id, provider_reversal_id, currency

    @staticmethod
    def _reversal_classification(event_type: str) -> tuple[bool, bool, str]:
        is_charge_summary = event_type == "charge.refunded"
        is_refund_object = event_type in _REFUND_OBJECT_EVENT_TYPES
        kind = "refund" if is_charge_summary or is_refund_object else "dispute"
        return is_charge_summary, is_refund_object, kind

    @staticmethod
    def _validate_refund_reconciliation_presence(
        *,
        is_charge_summary: bool,
        authoritative_refunds: tuple[StripeRefundState, ...] | None,
    ) -> None:
        if is_charge_summary and authoritative_refunds is None:
            raise BillingProviderError(
                "Stripe refund reconciliation is unavailable",
            )
        if not is_charge_summary and authoritative_refunds is not None:
            raise BillingValidationError(
                "Unexpected authoritative refund reconciliation",
            )

    @staticmethod
    def _reversal_amount(
        obj: dict[str, Any],
        *,
        is_charge_summary: bool,
    ) -> int:
        raw_amount = obj.get("amount_refunded") if is_charge_summary else obj.get("amount")
        if raw_amount is None or isinstance(raw_amount, bool):
            raise BillingValidationError("Reversal amount is invalid")
        try:
            return int(raw_amount)
        except (TypeError, ValueError) as exc:
            raise BillingValidationError("Reversal amount is invalid") from exc

    def _reversal_object_state(
        self,
        obj: dict[str, Any],
        *,
        event_type: str,
        provider_reversal_id: str,
        is_charge_summary: bool,
        is_refund_object: bool,
    ) -> tuple[str, bool]:
        if is_charge_summary:
            return self._charge_refund_summary_state(provider_reversal_id)
        status = str(obj.get("status") or "").lower().strip()
        if is_refund_object:
            return self._refund_object_state(
                event_type=event_type,
                provider_reversal_id=provider_reversal_id,
                status=status,
            )
        if not status or len(status) > 64:
            raise BillingValidationError("Dispute status is invalid")
        return status, self._dispute_active(event_type=event_type, status=status)

    @staticmethod
    def _charge_refund_summary_state(provider_reversal_id: str) -> tuple[str, bool]:
        if not provider_reversal_id.startswith("ch_"):
            raise BillingValidationError("Refund summary object id is invalid")
        return _CHARGE_REFUND_SUMMARY_STATUS, True

    @staticmethod
    def _refund_object_state(
        *,
        event_type: str,
        provider_reversal_id: str,
        status: str,
    ) -> tuple[str, bool]:
        if not provider_reversal_id.startswith("re_"):
            raise BillingValidationError("Refund object id is invalid")
        if status not in _ACTIVE_REFUND_STATUSES | _INACTIVE_REFUND_STATUSES:
            raise BillingValidationError("Refund status is invalid")
        if event_type == "refund.failed" and status not in _INACTIVE_REFUND_STATUSES:
            raise BillingValidationError("Failed refund status is invalid")
        return status, status in _ACTIVE_REFUND_STATUSES

    def _apply_reversal_in_session(
        self,
        session: Session,
        *,
        event: ParsedReversalEvent,
        event_id: str,
        integration_identifier: str | None,
        authoritative_refunds: tuple[StripeRefundState, ...] | None,
        provider_event_created: int,
    ) -> None:
        purchase = self._locked_reversal_purchase(
            session,
            event=event,
            integration_identifier=integration_identifier,
        )
        now = int(time.time())
        if not self._persist_reversal_event(
            session,
            purchase=purchase,
            event=event,
            event_id=event_id,
            authoritative_refunds=authoritative_refunds,
            provider_event_created=provider_event_created,
            now=now,
        ):
            return
        session.flush()
        reversals = self._purchase_reversals(session, purchase.id)
        aggregate = self._reversal_aggregate(purchase, reversals)
        debt_credits = self._reconcile_reversal_wallet(
            session,
            purchase=purchase,
            aggregate=aggregate,
            event_id=event_id,
        )
        self._apply_reversal_aggregate(
            session,
            purchase=purchase,
            aggregate=aggregate,
            debt_credits=debt_credits,
            provider_event_created=provider_event_created,
            now=now,
        )

    def _persist_reversal_event(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        event: ParsedReversalEvent,
        event_id: str,
        authoritative_refunds: tuple[StripeRefundState, ...] | None,
        provider_event_created: int,
        now: int,
    ) -> bool:
        if not self._upsert_provider_reversal(
            session,
            purchase=purchase,
            event=event,
            event_id=event_id,
            provider_event_created=provider_event_created,
            now=now,
        ):
            return False
        if authoritative_refunds is not None:
            self._upsert_authoritative_refunds_in_session(
                session,
                purchase=purchase,
                payment_intent_id=event.payment_intent_id,
                refunds=authoritative_refunds,
                charge_refunded_amount_cents=event.amount_cents,
                reconciliation_event_id=event_id,
                reconciliation_event_created=provider_event_created,
                now=now,
            )
        return True

    @staticmethod
    def _purchase_reversals(
        session: Session,
        purchase_id: str,
    ) -> list[DbCreditPurchaseReversal]:
        return list(
            session.scalars(select(DbCreditPurchaseReversal).where(DbCreditPurchaseReversal.purchase_id == purchase_id))
        )

    @staticmethod
    def _locked_reversal_purchase(
        session: Session,
        *,
        event: ParsedReversalEvent,
        integration_identifier: str | None,
    ) -> DbCreditPurchase:
        purchase = session.scalar(
            select(DbCreditPurchase).where(DbCreditPurchase.id == event.purchase_id).with_for_update().limit(1)
        )
        if purchase is None:
            raise BillingProviderError(
                "Local reversal purchase is not available yet",
            )
        if integration_identifier is not None and purchase.integration_identifier != integration_identifier:
            raise BillingValidationError(
                "PaymentIntent namespace conflicts with its purchase",
            )
        if purchase.payment_intent_id not in {None, event.payment_intent_id}:
            raise BillingValidationError(
                "Reversal PaymentIntent conflicts with its purchase",
            )
        if event.currency != purchase.currency.lower():
            raise BillingValidationError("Reversal currency mismatch")
        if event.amount_cents <= 0 or event.amount_cents > purchase.amount_eur_cents:
            raise BillingValidationError("Reversal amount is invalid")
        purchase.payment_intent_id = event.payment_intent_id
        return purchase

    def _upsert_provider_reversal(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        event: ParsedReversalEvent,
        event_id: str,
        provider_event_created: int,
        now: int,
    ) -> bool:
        reversal = self._provider_reversal(session, event.provider_reversal_id)
        if reversal is None:
            self._add_provider_reversal(
                session,
                purchase=purchase,
                event=event,
                event_id=event_id,
                provider_event_created=provider_event_created,
                now=now,
            )
            return True
        self._validate_existing_reversal_identity(reversal, purchase=purchase, event=event)
        if event.is_charge_refund_summary:
            self._update_charge_summary_reversal(
                reversal,
                event=event,
                event_id=event_id,
                provider_event_created=provider_event_created,
                now=now,
            )
            return True
        if not self._incoming_reversal_state_is_current(
            reversal,
            event=event,
            event_id=event_id,
            provider_event_created=provider_event_created,
        ):
            return False
        self._write_reversal_state(
            reversal,
            event=event,
            event_id=event_id,
            provider_event_created=provider_event_created,
            now=now,
        )
        return True

    def _update_charge_summary_reversal(
        self,
        reversal: DbCreditPurchaseReversal,
        *,
        event: ParsedReversalEvent,
        event_id: str,
        provider_event_created: int,
        now: int,
    ) -> None:
        if self._newer_cumulative_refund_state(
            reversal,
            event_id=event_id,
            provider_event_created=provider_event_created,
            amount_cents=event.amount_cents,
        ):
            self._write_reversal_state(
                reversal,
                event=event,
                event_id=event_id,
                provider_event_created=provider_event_created,
                now=now,
            )

    @staticmethod
    def _provider_reversal(
        session: Session,
        provider_reversal_id: str,
    ) -> DbCreditPurchaseReversal | None:
        return session.scalar(
            select(DbCreditPurchaseReversal)
            .where(
                DbCreditPurchaseReversal.provider == "stripe",
                DbCreditPurchaseReversal.provider_reversal_id == provider_reversal_id,
            )
            .with_for_update()
            .limit(1)
        )

    @staticmethod
    def _add_provider_reversal(
        session: Session,
        *,
        purchase: DbCreditPurchase,
        event: ParsedReversalEvent,
        event_id: str,
        provider_event_created: int,
        now: int,
    ) -> None:
        session.add(
            DbCreditPurchaseReversal(
                id=uuid.uuid4().hex,
                purchase_id=purchase.id,
                provider="stripe",
                provider_reversal_id=event.provider_reversal_id,
                provider_event_id=event_id,
                provider_event_created=provider_event_created,
                kind=event.kind,
                amount_cents=event.amount_cents,
                currency=event.currency,
                status=event.status,
                active=event.active,
                created_at=now,
                updated_at=now,
            )
        )

    @staticmethod
    def _validate_existing_reversal_identity(
        reversal: DbCreditPurchaseReversal,
        *,
        purchase: DbCreditPurchase,
        event: ParsedReversalEvent,
    ) -> None:
        if (
            reversal.purchase_id != purchase.id
            or reversal.kind != event.kind
            or reversal.currency.lower() != event.currency
        ):
            raise BillingValidationError(
                "Reversal object conflicts with its purchase",
            )

    def _incoming_reversal_state_is_current(
        self,
        reversal: DbCreditPurchaseReversal,
        *,
        event: ParsedReversalEvent,
        event_id: str,
        provider_event_created: int,
    ) -> bool:
        if reversal.amount_cents != event.amount_cents:
            label = "Refund" if event.is_refund_object else "Dispute"
            raise BillingValidationError(
                f"{label} amount conflicts with its prior state",
            )
        if event.is_refund_object:
            return not self._stale_refund_state(
                reversal,
                event_id=event_id,
                provider_event_created=provider_event_created,
                status=event.status,
            )
        return not self._stale_dispute_state(
            reversal,
            event_id=event_id,
            provider_event_created=provider_event_created,
            active=event.active,
        )

    @staticmethod
    def _write_reversal_state(
        reversal: DbCreditPurchaseReversal,
        *,
        event: ParsedReversalEvent,
        event_id: str,
        provider_event_created: int,
        now: int,
    ) -> None:
        reversal.provider_event_id = event_id
        reversal.provider_event_created = provider_event_created
        reversal.amount_cents = event.amount_cents
        reversal.status = event.status
        reversal.active = event.active
        reversal.updated_at = now

    def _reversal_aggregate(
        self,
        purchase: DbCreditPurchase,
        reversals: list[DbCreditPurchaseReversal],
    ) -> ReversalAggregate:
        active_refunded_cents = self._active_refunded_cents(reversals)
        refunded_cents = min(purchase.amount_eur_cents, active_refunded_cents)
        active_dispute_cents = sum(item.amount_cents for item in reversals if item.kind == "dispute" and item.active)
        active_reversal_cents = min(
            purchase.amount_eur_cents,
            refunded_cents + active_dispute_cents,
        )
        return ReversalAggregate(
            refunded_cents=refunded_cents,
            active_reversal_cents=active_reversal_cents,
            dispute_active=any(item.kind == "dispute" and item.active for item in reversals),
            desired_reversal=math.ceil(
                purchase.credits * active_reversal_cents / purchase.amount_eur_cents,
            ),
        )

    def _active_refunded_cents(
        self,
        reversals: list[DbCreditPurchaseReversal],
    ) -> int:
        individual_refunds = self._individual_refunds(reversals)
        legacy_refund_cents = self._legacy_refund_cents(reversals)
        if individual_refunds:
            individual_refund_cents = sum(item.amount_cents for item in individual_refunds if item.active)
            active_refunded_cents = max(individual_refund_cents, legacy_refund_cents)
        else:
            active_refunded_cents = max(self._charge_summary_cents(reversals), legacy_refund_cents)
        return active_refunded_cents

    def _individual_refunds(
        self,
        reversals: list[DbCreditPurchaseReversal],
    ) -> list[DbCreditPurchaseReversal]:
        return [item for item in reversals if item.kind == "refund" and self._is_individual_refund(item)]

    def _legacy_refund_cents(self, reversals: list[DbCreditPurchaseReversal]) -> int:
        return max(
            (item.amount_cents for item in reversals if self._is_legacy_refund_baseline(item) and item.active),
            default=0,
        )

    def _charge_summary_cents(self, reversals: list[DbCreditPurchaseReversal]) -> int:
        return max(
            (item.amount_cents for item in reversals if self._is_charge_refund_summary(item) and item.active),
            default=0,
        )

    def _reconcile_reversal_wallet(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        aggregate: ReversalAggregate,
        event_id: str,
    ) -> int:
        desired = aggregate.desired_reversal
        current = int(purchase.reversed_credits or 0)
        debt = min(desired, int(purchase.reversal_debt_credits or 0))
        if purchase.fulfilled_at is not None and purchase.user_id is not None and desired > current:
            return self._reverse_reversal_wallet(
                session,
                purchase=purchase,
                desired=desired,
                current=current,
                event_id=event_id,
            )
        if purchase.fulfilled_at is not None and purchase.user_id is not None and desired < current:
            return self._restore_reversal_wallet(
                session,
                purchase=purchase,
                desired=desired,
                current=current,
                event_id=event_id,
            )
        return 0 if purchase.user_id is None else debt

    def _reverse_reversal_wallet(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        desired: int,
        current: int,
        event_id: str,
    ) -> int:
        mutation = self.points_store.reverse_paid_purchase_once_in_session(
            session,
            cast(str, purchase.user_id),
            desired - current,
            purchase_id=purchase.id,
            transaction_id=make_idempotency_id("stripe", "reverse", purchase.id, event_id),
        )
        return min(desired, int(purchase.reversal_debt_credits or 0) + max(0, mutation.debt_delta))

    def _restore_reversal_wallet(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        desired: int,
        current: int,
        event_id: str,
    ) -> int:
        mutation = self.points_store.restore_paid_reversal_once_in_session(
            session,
            cast(str, purchase.user_id),
            current - desired,
            purchase_id=purchase.id,
            transaction_id=make_idempotency_id("stripe", "restore", purchase.id, event_id),
        )
        return min(
            desired,
            max(0, int(purchase.reversal_debt_credits or 0) + min(0, mutation.debt_delta)),
        )

    def _apply_reversal_aggregate(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        aggregate: ReversalAggregate,
        debt_credits: int,
        provider_event_created: int,
        now: int,
    ) -> None:
        purchase.refunded_amount_cents = aggregate.refunded_cents
        purchase.dispute_active = aggregate.dispute_active
        purchase.reversed_amount_cents = aggregate.active_reversal_cents
        purchase.reversed_credits = aggregate.desired_reversal
        purchase.reversal_debt_credits = debt_credits
        purchase.status = self._reversal_status(purchase)
        # A query may autoflush after attaching the PaymentIntent and let a DB
        # trigger extend retention from local observation time. Never overwrite
        # that with an older provider-derived deadline.
        reversal_retention = financial_retention_deadline(
            max(provider_event_created, now),
        )
        purchase.financial_retention_until = max(
            int(purchase.financial_retention_until),
            reversal_retention,
        )
        invoice = session.scalar(
            select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).with_for_update().limit(1)
        )
        if invoice is not None:
            invoice.financial_retention_until = max(
                int(invoice.financial_retention_until),
                reversal_retention,
            )
            invoice.updated_at = max(int(invoice.updated_at), now)
        purchase.updated_at = now
