"""Authoritative refund projection and event-state helpers."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import (
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_service_base import BillingServiceMixinBase
from backend.app.services.billing_types import (
    _ACTIVE_REFUND_STATUSES,
    _CHARGE_REFUND_SUMMARY_STATUS,
    _INACTIVE_DISPUTE_STATUSES,
    _INACTIVE_REFUND_STATUSES,
    _RECOGNIZED_EVENT_TYPES,
    _REFUND_STATUS_RANK,
    BillingProviderError,
    BillingValidationError,
    StripeRefundState,
)


class BillingRefundMixin(BillingServiceMixinBase):
    def _upsert_authoritative_refunds_in_session(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        payment_intent_id: str,
        refunds: tuple[StripeRefundState, ...],
        charge_refunded_amount_cents: int,
        reconciliation_event_id: str,
        reconciliation_event_created: int,
        now: int,
    ) -> None:
        self._validate_authoritative_refund_collection(refunds)
        existing_individuals = self._existing_individual_refunds(
            session,
            purchase=purchase,
            refund_ids={refund.id for refund in refunds},
        )
        active_refund_cents = self._validated_active_refund_total(
            refunds,
            purchase=purchase,
            payment_intent_id=payment_intent_id,
        )
        if active_refund_cents < charge_refunded_amount_cents:
            raise BillingProviderError(
                "Stripe refund reconciliation returned an incomplete active cumulative refund total",
            )
        if active_refund_cents > purchase.amount_eur_cents:
            raise BillingProviderError(
                "Stripe refund reconciliation exceeds the purchase amount",
            )
        for refund in refunds:
            self._upsert_authoritative_refund(
                session,
                purchase=purchase,
                refund=refund,
                existing=existing_individuals.get(refund.id),
                reconciliation_event_id=reconciliation_event_id,
                reconciliation_event_created=reconciliation_event_created,
                now=now,
            )

    @staticmethod
    def _validate_authoritative_refund_collection(
        refunds: tuple[StripeRefundState, ...],
    ) -> None:
        if not refunds:
            raise BillingProviderError(
                "Stripe refund reconciliation returned no refund objects",
            )

        refund_ids = [refund.id for refund in refunds]
        if len(refund_ids) != len(set(refund_ids)):
            raise BillingProviderError(
                "Stripe refund reconciliation returned duplicate objects",
            )

    def _existing_individual_refunds(
        self,
        session: Session,
        *,
        purchase: DbCreditPurchase,
        refund_ids: set[str],
    ) -> dict[str, DbCreditPurchaseReversal]:
        existing_refunds = list(
            session.scalars(
                select(DbCreditPurchaseReversal)
                .where(
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                    DbCreditPurchaseReversal.provider == "stripe",
                    DbCreditPurchaseReversal.kind == "refund",
                )
                .with_for_update()
            )
        )
        existing_individuals = {
            item.provider_reversal_id: item for item in existing_refunds if self._is_individual_refund(item)
        }
        missing_refund_ids = set(existing_individuals) - refund_ids
        if missing_refund_ids:
            raise BillingProviderError(
                "Stripe refund reconciliation returned an incomplete refund set",
            )
        return existing_individuals

    @staticmethod
    def _validated_active_refund_total(
        refunds: tuple[StripeRefundState, ...],
        *,
        purchase: DbCreditPurchase,
        payment_intent_id: str,
    ) -> int:
        active_refund_cents = 0
        for refund in refunds:
            BillingRefundMixin._validate_authoritative_refund(
                refund,
                purchase=purchase,
                payment_intent_id=payment_intent_id,
            )
            if refund.status in _ACTIVE_REFUND_STATUSES:
                active_refund_cents += refund.amount_cents
        return active_refund_cents

    @staticmethod
    def _validate_authoritative_refund(
        refund: StripeRefundState,
        *,
        purchase: DbCreditPurchase,
        payment_intent_id: str,
    ) -> None:
        if (
            refund.payment_intent_id != payment_intent_id
            or refund.currency != purchase.currency.lower()
            or refund.amount_cents <= 0
            or refund.amount_cents > purchase.amount_eur_cents
            or refund.status not in (_ACTIVE_REFUND_STATUSES | _INACTIVE_REFUND_STATUSES)
            or refund.created <= 0
        ):
            raise BillingProviderError(
                "Stripe refund reconciliation returned invalid data",
            )

    @staticmethod
    def _upsert_authoritative_refund(
        session: Session,
        *,
        purchase: DbCreditPurchase,
        refund: StripeRefundState,
        existing: DbCreditPurchaseReversal | None,
        reconciliation_event_id: str,
        reconciliation_event_created: int,
        now: int,
    ) -> None:
        reversal = existing or BillingRefundMixin._authoritative_refund_by_id(session, refund.id)
        if reversal is None:
            reversal = BillingRefundMixin._new_authoritative_refund(
                session,
                purchase=purchase,
                refund=refund,
                reconciliation_event_created=reconciliation_event_created,
                now=now,
            )
        elif not BillingRefundMixin._authoritative_refund_matches(
            reversal,
            purchase=purchase,
            refund=refund,
        ):
            raise BillingValidationError("Refund object conflicts with its purchase")
        reconciliation_id = hashlib.sha256(
            (f"stripe-refund-reconciliation:{reconciliation_event_id}:{refund.id}").encode()
        ).hexdigest()
        reversal.provider_event_id = f"reconcile_{reconciliation_id}"
        reversal.provider_event_created = max(
            int(reversal.provider_event_created),
            reconciliation_event_created,
        )
        reversal.status = refund.status
        reversal.active = refund.status in _ACTIVE_REFUND_STATUSES
        reversal.updated_at = now

    @staticmethod
    def _authoritative_refund_by_id(
        session: Session,
        refund_id: str,
    ) -> DbCreditPurchaseReversal | None:
        return session.scalar(
            select(DbCreditPurchaseReversal)
            .where(
                DbCreditPurchaseReversal.provider == "stripe",
                DbCreditPurchaseReversal.provider_reversal_id == refund_id,
            )
            .with_for_update()
            .limit(1)
        )

    @staticmethod
    def _new_authoritative_refund(
        session: Session,
        *,
        purchase: DbCreditPurchase,
        refund: StripeRefundState,
        reconciliation_event_created: int,
        now: int,
    ) -> DbCreditPurchaseReversal:
        reversal = DbCreditPurchaseReversal(
            id=uuid.uuid4().hex,
            purchase_id=purchase.id,
            provider="stripe",
            provider_reversal_id=refund.id,
            provider_event_id=None,
            provider_event_created=reconciliation_event_created,
            kind="refund",
            amount_cents=refund.amount_cents,
            currency=refund.currency,
            status=refund.status,
            active=refund.status in _ACTIVE_REFUND_STATUSES,
            created_at=now,
            updated_at=now,
        )
        session.add(reversal)
        return reversal

    @staticmethod
    def _authoritative_refund_matches(
        reversal: DbCreditPurchaseReversal,
        *,
        purchase: DbCreditPurchase,
        refund: StripeRefundState,
    ) -> bool:
        return (
            reversal.purchase_id == purchase.id
            and reversal.kind == "refund"
            and reversal.currency.lower() == refund.currency
            and reversal.amount_cents == refund.amount_cents
        )

    @staticmethod
    def _provider_event_created(value: Any) -> int:
        if isinstance(value, bool):
            raise BillingValidationError("Stripe event timestamp is invalid")
        try:
            created = int(value)
        except (TypeError, ValueError) as exc:
            raise BillingValidationError(
                "Stripe event timestamp is invalid",
            ) from exc
        if created <= 0:
            raise BillingValidationError("Stripe event timestamp is invalid")
        return created

    @staticmethod
    def _event_livemode(value: Any) -> bool:
        if not isinstance(value, bool):
            raise BillingValidationError("Stripe event mode is invalid")
        return value

    @staticmethod
    def _validated_event_livemode(
        event_type: str,
        value: Any,
    ) -> bool | None:
        if event_type not in _RECOGNIZED_EVENT_TYPES:
            return value if isinstance(value, bool) else None
        livemode = BillingRefundMixin._event_livemode(value)
        if livemode != (not settings.is_dev):
            raise BillingValidationError(
                "Stripe event mode does not match the runtime environment",
            )
        return livemode

    @staticmethod
    def _validate_checkout_session_id_mode(session_id: str) -> None:
        if not session_id.startswith(("cs_test_", "cs_live_")):
            raise BillingValidationError("Invalid Checkout Session id")
        expected_prefix = "cs_test_" if settings.is_dev else "cs_live_"
        if not session_id.startswith(expected_prefix):
            raise BillingValidationError(
                "Checkout Session mode does not match the runtime environment",
            )

    @staticmethod
    def _dispute_active(*, event_type: str, status: str) -> bool:
        if event_type == "charge.dispute.funds_withdrawn":
            return True
        if event_type == "charge.dispute.funds_reinstated":
            return False
        return status not in _INACTIVE_DISPUTE_STATUSES

    @staticmethod
    def _newer_cumulative_refund_state(
        reversal: DbCreditPurchaseReversal,
        *,
        event_id: str,
        provider_event_created: int,
        amount_cents: int,
    ) -> bool:
        if amount_cents != reversal.amount_cents:
            return amount_cents > reversal.amount_cents
        if provider_event_created != reversal.provider_event_created:
            return provider_event_created > reversal.provider_event_created
        return event_id > str(reversal.provider_event_id or "")

    @staticmethod
    def _stale_refund_state(
        reversal: DbCreditPurchaseReversal,
        *,
        event_id: str,
        provider_event_created: int,
        status: str,
    ) -> bool:
        if provider_event_created != reversal.provider_event_created:
            return provider_event_created < reversal.provider_event_created
        incoming_rank = _REFUND_STATUS_RANK[status]
        current_rank = _REFUND_STATUS_RANK.get(reversal.status, -1)
        if incoming_rank != current_rank:
            return incoming_rank < current_rank
        return event_id <= str(reversal.provider_event_id or "")

    @staticmethod
    def _is_charge_refund_summary(
        reversal: DbCreditPurchaseReversal,
    ) -> bool:
        return reversal.status == _CHARGE_REFUND_SUMMARY_STATUS or reversal.provider_reversal_id.startswith("ch_")

    @staticmethod
    def _is_individual_refund(
        reversal: DbCreditPurchaseReversal,
    ) -> bool:
        return (
            reversal.provider == "stripe"
            and reversal.provider_reversal_id.startswith("re_")
            and not BillingRefundMixin._is_charge_refund_summary(reversal)
        )

    @staticmethod
    def _is_legacy_refund_baseline(
        reversal: DbCreditPurchaseReversal,
    ) -> bool:
        return reversal.kind == "refund" and reversal.provider == "legacy_migration"

    @staticmethod
    def _stale_dispute_state(
        reversal: DbCreditPurchaseReversal,
        *,
        event_id: str,
        provider_event_created: int,
        active: bool,
    ) -> bool:
        return provider_event_created < reversal.provider_event_created or (
            provider_event_created == reversal.provider_event_created
            and bool(reversal.active)
            and not active
            and reversal.provider_event_id != event_id
        )
