"""Stripe event scoping and reversal application operations."""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_reversal_application import BillingReversalApplicationMixin
from backend.app.services.billing_types import (
    _LOCAL_INTEGRATION_RE,
    _PURCHASE_ID_RE,
    _REVERSAL_EVENT_TYPES,
    BillingProviderError,
    BillingValidationError,
    StripeRefundState,
    _StripeEventScope,
)


class BillingReversalMixin(BillingReversalApplicationMixin):
    def _resolve_event_scope(
        self,
        session: Session,
        *,
        event_type: str,
        obj: dict[str, Any],
    ) -> _StripeEventScope:
        """Resolve ownership before mutating a shared Stripe account event."""
        if event_type in {
            "checkout.session.completed",
            "checkout.session.async_payment_succeeded",
        }:
            return self._resolve_checkout_completion_scope(session, obj)
        if event_type in {
            "checkout.session.expired",
            "checkout.session.async_payment_failed",
        }:
            return self._resolve_checkout_terminal_scope(session, obj)
        if event_type in _REVERSAL_EVENT_TYPES:
            return self._resolve_reversal_scope(session, obj)
        return _StripeEventScope(is_local=False)

    def _resolve_checkout_completion_scope(
        self,
        session: Session,
        obj: dict[str, Any],
    ) -> _StripeEventScope:
        metadata = obj.get("metadata")
        purchase_id = str(metadata.get("purchase_id") or "") if isinstance(metadata, dict) else ""
        integration_identifier = str(metadata.get("integration_identifier") or "") if isinstance(metadata, dict) else ""
        session_id = self._stripe_id(obj.get("id"))
        known_purchase_id = session.scalar(
            select(DbCreditPurchase.id)
            .where((DbCreditPurchase.id == purchase_id) | (DbCreditPurchase.checkout_session_id == session_id))
            .limit(1)
        )
        payment_intent_id = self._stripe_id(obj.get("payment_intent")) or None
        if known_purchase_id:
            return _StripeEventScope(
                is_local=True,
                purchase_id=known_purchase_id,
                payment_intent_id=payment_intent_id,
            )
        if not self._is_local_integration_identifier(integration_identifier):
            return _StripeEventScope(is_local=False)
        if not _PURCHASE_ID_RE.fullmatch(purchase_id):
            raise BillingValidationError(
                "Local Checkout metadata has an invalid purchase id",
            )
        return _StripeEventScope(
            is_local=True,
            purchase_id=purchase_id,
            integration_identifier=integration_identifier,
            payment_intent_id=payment_intent_id,
        )

    @staticmethod
    def _resolve_checkout_terminal_scope(
        session: Session,
        obj: dict[str, Any],
    ) -> _StripeEventScope:
        session_id = str(obj.get("id") or "")
        if not session_id:
            raise BillingValidationError("Checkout Session id is missing")
        known_purchase_id = session.scalar(
            select(DbCreditPurchase.id).where(DbCreditPurchase.checkout_session_id == session_id).limit(1)
        )
        return _StripeEventScope(
            is_local=known_purchase_id is not None,
            purchase_id=known_purchase_id,
        )

    def _resolve_reversal_scope(
        self,
        session: Session,
        obj: dict[str, Any],
    ) -> _StripeEventScope:
        payment_intent_id = self._stripe_id(obj.get("payment_intent"))
        if not payment_intent_id:
            return self._resolve_reversal_without_payment_intent(session, obj)
        known_purchase_id = session.scalar(
            select(DbCreditPurchase.id).where(DbCreditPurchase.payment_intent_id == payment_intent_id).limit(1)
        )
        if known_purchase_id:
            return _StripeEventScope(
                is_local=True,
                purchase_id=known_purchase_id,
                payment_intent_id=payment_intent_id,
            )
        return self._resolve_payment_intent_metadata_scope(
            obj,
            payment_intent_id=payment_intent_id,
        )

    def _resolve_reversal_without_payment_intent(
        self,
        session: Session,
        obj: dict[str, Any],
    ) -> _StripeEventScope:
        provider_reversal_id = self._stripe_id(obj.get("id"))
        if not provider_reversal_id or len(provider_reversal_id) > 255:
            return _StripeEventScope(is_local=False)
        known_reversal = session.execute(
            select(
                DbCreditPurchaseReversal.purchase_id,
                DbCreditPurchase.payment_intent_id,
            )
            .join(
                DbCreditPurchase,
                DbCreditPurchase.id == DbCreditPurchaseReversal.purchase_id,
            )
            .where(
                DbCreditPurchaseReversal.provider == "stripe",
                DbCreditPurchaseReversal.provider_reversal_id == provider_reversal_id,
            )
            .limit(1)
        ).one_or_none()
        if known_reversal is None:
            return _StripeEventScope(is_local=False)
        known_purchase_id, known_payment_intent_id = known_reversal
        if not known_payment_intent_id:
            raise BillingProviderError(
                "Local reversal PaymentIntent is not available yet",
            )
        return _StripeEventScope(
            is_local=True,
            purchase_id=known_purchase_id,
            payment_intent_id=known_payment_intent_id,
        )

    def _resolve_payment_intent_metadata_scope(
        self,
        obj: dict[str, Any],
        *,
        payment_intent_id: str,
    ) -> _StripeEventScope:
        metadata = self._payment_intent_metadata(obj)
        integration_identifier = str(metadata.get("integration_identifier") or "")
        if not self._is_local_integration_identifier(integration_identifier):
            return _StripeEventScope(is_local=False)
        purchase_id = str(metadata.get("purchase_id") or "")
        if not _PURCHASE_ID_RE.fullmatch(purchase_id):
            raise BillingValidationError(
                "Local PaymentIntent metadata has an invalid purchase id",
            )
        return _StripeEventScope(
            is_local=True,
            purchase_id=purchase_id,
            integration_identifier=integration_identifier,
            payment_intent_id=payment_intent_id,
        )

    def _payment_intent_metadata(
        self,
        obj: dict[str, Any],
    ) -> dict[str, str]:
        raw_payment_intent = obj.get("payment_intent")
        if isinstance(raw_payment_intent, dict):
            raw_metadata = raw_payment_intent.get("metadata")
            if isinstance(raw_metadata, dict):
                return {
                    str(key): str(value)
                    for key, value in raw_metadata.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
        payment_intent_id = self._stripe_id(raw_payment_intent)
        try:
            metadata = self._webhook_gateway().retrieve_payment_intent_metadata(
                payment_intent_id,
            )
        except BillingProviderError:
            raise
        except Exception as exc:
            raise BillingProviderError(
                "Stripe PaymentIntent lookup is temporarily unavailable",
            ) from exc
        if not isinstance(metadata, dict):
            raise BillingProviderError(
                "Stripe PaymentIntent metadata is unavailable",
            )
        return metadata

    @staticmethod
    def _is_local_integration_identifier(value: str) -> bool:
        return _LOCAL_INTEGRATION_RE.fullmatch(value) is not None

    @staticmethod
    def _advisory_lock_key(value: str) -> int:
        return int.from_bytes(
            hashlib.sha256(value.encode()).digest()[:8],
            byteorder="big",
            signed=True,
        )

    def _apply_reversal_event(
        self,
        obj: dict[str, Any],
        *,
        event_id: str,
        event_type: str,
        purchase_id: str | None,
        integration_identifier: str | None,
        resolved_payment_intent_id: str | None,
        authoritative_refunds: tuple[StripeRefundState, ...] | None,
        provider_event_created: int,
    ) -> None:
        event = self._validated_reversal_event(
            obj,
            event_type=event_type,
            purchase_id=purchase_id,
            resolved_payment_intent_id=resolved_payment_intent_id,
            authoritative_refunds=authoritative_refunds,
        )
        with self.db.session() as session:
            self._apply_reversal_in_session(
                session,
                event=event,
                event_id=event_id,
                integration_identifier=integration_identifier,
                authoritative_refunds=authoritative_refunds,
                provider_event_created=provider_event_created,
            )
