"""Fail-closed billing-admin authorization and record projection helpers."""

from __future__ import annotations

import os
import re
from typing import Any, Literal, cast

from fastapi import HTTPException, Response
from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement

from backend.app.api.endpoints.billing_admin_models import (
    PendingBillingCustomer,
    PendingBillingInvoice,
    PendingBillingPackage,
    PendingBillingPayment,
    PendingBillingService,
    PendingBillingTax,
    RecordedAadeDocumentResponse,
    RecordedManualRefundAccountingResponse,
    RecordIssuedAadeDocumentRequest,
    WithdrawalResolutionResponse,
)
from backend.app.core.auth import SessionStore, User
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingInvoice,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_records import (
    AADE_GREEK_B2C_DOCUMENT_TYPE,
    AADE_GREEK_B2C_SERIES,
)
from backend.app.services.financial_records import financial_retention_deadline

_PENDING_DOCUMENT_STATUSES = (
    "pending_manual_issue",
    "manual_review_required",
)
_ADMIN_USER_ID = re.compile(r"^[0-9a-f]{16,64}$")
_ADMIN_WRITE_SESSION_MAX_AGE_SECONDS = 15 * 60


def _is_exact_issued_document_replay(
    *,
    invoice: DbBillingInvoice,
    payload: RecordIssuedAadeDocumentRequest,
) -> bool:
    return (
        invoice.document_status == "issued"
        and invoice.aade_document_type == payload.document_type
        and invoice.aade_series == payload.series
        and invoice.aade_aa == payload.aa
        and invoice.aade_mark == payload.mark
        and invoice.issued_at == payload.issued_at
    )


def _ensure_greek_b2c_aade_baseline(
    *,
    invoice: DbBillingInvoice,
    payload: RecordIssuedAadeDocumentRequest,
) -> None:
    if invoice.provider != "aade_etimologio" or invoice.document_kind != "retail_service_receipt":
        raise HTTPException(
            status_code=409,
            detail="Billing invoice is not an AADE retail service receipt",
        )
    if payload.document_type != AADE_GREEK_B2C_DOCUMENT_TYPE or payload.series != AADE_GREEK_B2C_SERIES:
        raise HTTPException(
            status_code=400,
            detail=("AADE document type and series must match the approved Greek B2C baseline"),
        )


def _recorded_document_response(
    *,
    invoice: DbBillingInvoice,
    purchase: DbCreditPurchase,
) -> RecordedAadeDocumentResponse:
    if (
        invoice.aade_document_type is None
        or invoice.aade_series is None
        or invoice.aade_aa is None
        or invoice.aade_mark is None
        or invoice.issued_at is None
        or invoice.recorded_by_user_id is None
        or invoice.recorded_at is None
    ):
        raise HTTPException(
            status_code=409,
            detail="AADE document audit is incomplete",
        )
    return RecordedAadeDocumentResponse(
        invoice_id=invoice.id,
        purchase_id=purchase.id,
        document_status=invoice.document_status,
        aade_document_type=invoice.aade_document_type,
        aade_series=invoice.aade_series,
        aade_aa=invoice.aade_aa,
        aade_mark=invoice.aade_mark,
        issued_at=invoice.issued_at,
        recorded_at=invoice.recorded_at,
        financial_retention_until=invoice.financial_retention_until,
    )


def _recorded_manual_refund_response(
    *,
    adjustment: DbBillingAdjustmentRecord,
    reversal: DbCreditPurchaseReversal,
    invoice: DbBillingInvoice,
) -> RecordedManualRefundAccountingResponse:
    if invoice.document_status != "issued" or invoice.aade_mark is None:
        raise HTTPException(
            status_code=409,
            detail="Original AADE document audit is incomplete",
        )
    return RecordedManualRefundAccountingResponse(
        adjustment_id=adjustment.id,
        purchase_id=adjustment.purchase_id,
        reversal_id=adjustment.reversal_id,
        stripe_refund_id=reversal.provider_reversal_id,
        amount_cents=adjustment.amount_cents,
        currency=adjustment.currency,
        aade_document_type=adjustment.aade_document_type,
        aade_series=adjustment.aade_series,
        aade_aa=adjustment.aade_aa,
        aade_mark=adjustment.aade_mark,
        issued_at=adjustment.issued_at,
        recorded_at=adjustment.recorded_at,
        financial_retention_until=(adjustment.financial_retention_until),
        original_invoice_status=invoice.document_status,
        original_invoice_mark=invoice.aade_mark,
    )


def _is_exact_adjustment_replay(
    *,
    adjustment: DbBillingAdjustmentRecord,
    payload: RecordIssuedAadeDocumentRequest,
) -> bool:
    return (
        adjustment.aade_document_type == payload.document_type
        and adjustment.aade_series == payload.series
        and adjustment.aade_aa == payload.aa
        and adjustment.aade_mark == payload.mark
        and adjustment.issued_at == payload.issued_at
    )


def _record_original_document_for_refund(
    *,
    invoice: DbBillingInvoice,
    purchase: DbCreditPurchase,
    payload: RecordIssuedAadeDocumentRequest | None,
    current_user: User,
    now: int,
) -> None:
    has_recorded_identity = (
        invoice.document_status not in _PENDING_DOCUMENT_STATUSES
        or invoice.aade_document_type is not None
        or invoice.aade_series is not None
        or invoice.aade_aa is not None
        or invoice.aade_mark is not None
        or invoice.issued_at is not None
        or invoice.recorded_by_user_id is not None
        or invoice.recorded_at is not None
    )
    if has_recorded_identity:
        if (
            invoice.document_status != "issued"
            or invoice.aade_mark is None
            or (
                payload is not None
                and not _is_exact_issued_document_replay(
                    invoice=invoice,
                    payload=payload,
                )
            )
        ):
            raise HTTPException(
                status_code=409,
                detail="Original AADE document conflicts with refund review",
            )
        return
    if payload is None:
        raise HTTPException(
            status_code=409,
            detail=("Original AADE document must be supplied together with the refund adjustment"),
        )
    if payload.issued_at > now:
        raise HTTPException(
            status_code=400,
            detail="Original AADE issued_at cannot be in the future",
        )
    _ensure_greek_b2c_aade_baseline(
        invoice=invoice,
        payload=payload,
    )
    payment_confirmation_at = _payment_confirmation_at(
        invoice=invoice,
        purchase=purchase,
    )
    if payload.issued_at < payment_confirmation_at:
        raise HTTPException(
            status_code=400,
            detail=("Original AADE issued_at cannot predate the confirmed payment"),
        )
    invoice.aade_document_type = payload.document_type
    invoice.aade_series = payload.series
    invoice.aade_aa = payload.aa
    invoice.aade_mark = payload.mark
    invoice.issued_at = payload.issued_at
    invoice.recorded_by_user_id = current_user.id
    invoice.recorded_at = now
    invoice.document_status = "issued"
    invoice.financial_retention_until = max(
        int(invoice.financial_retention_until),
        financial_retention_deadline(payload.issued_at),
        financial_retention_deadline(now),
    )
    invoice.updated_at = now
    purchase.financial_retention_until = max(
        int(purchase.financial_retention_until),
        int(invoice.financial_retention_until),
    )
    purchase.updated_at = max(int(purchase.updated_at), now)


def _withdrawal_resolution_response(
    resolution: DbBillingWithdrawalResolution,
) -> WithdrawalResolutionResponse:
    return WithdrawalResolutionResponse(
        resolution_id=resolution.id,
        withdrawal_id=resolution.withdrawal_id,
        purchase_id=resolution.purchase_id,
        decision=cast(
            Literal["accepted_refunded", "rejected"],
            resolution.decision,
        ),
        reason_code=resolution.reason_code,
        adjustment_id=resolution.adjustment_id,
        resolved_at=resolution.resolved_at,
        resolution_sha256=resolution.resolution_sha256,
        resolution_url=(f"/billing/purchases/{resolution.purchase_id}/withdrawal-resolution"),
    )


def _configured_admin_user_ids() -> frozenset[str]:
    configured = os.getenv("GSP_BILLING_ADMIN_USER_IDS", "")
    if not configured.strip():
        raise HTTPException(status_code=403, detail="Admin access not configured")

    user_ids = [raw_user_id.strip() for raw_user_id in configured.split(",")]
    if any(not user_id or _ADMIN_USER_ID.fullmatch(user_id) is None for user_id in user_ids) or len(user_ids) != len(
        set(user_ids)
    ):
        raise HTTPException(
            status_code=403,
            detail="Admin access configuration is invalid",
        )
    return frozenset(user_ids)


def _ensure_admin(current_user: User) -> None:
    if current_user.id not in _configured_admin_user_ids():
        raise HTTPException(status_code=403, detail="Not authorized")
    if not current_user.email_verified:
        raise HTTPException(
            status_code=403,
            detail="Verified admin account required",
        )


def _ensure_recent_admin_session(
    *,
    token: str,
    session_store: SessionStore,
    now: int,
) -> None:
    """Require a freshly issued bearer session for irreversible tax writes."""
    created_at = session_store.get_valid_session_created_at(token)
    age = None if created_at is None else now - created_at
    if age is None or age < 0 or age > _ADMIN_WRITE_SESSION_MAX_AGE_SECONDS:
        raise HTTPException(status_code=403, detail="Recent sign-in required")


def _disable_sensitive_response_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _snapshot_mapping(snapshot: Any) -> dict[str, Any]:
    return snapshot if isinstance(snapshot, dict) else {}


def _snapshot_string(
    snapshot: dict[str, Any],
    key: str,
) -> str | None:
    value = snapshot.get(key)
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _snapshot_integer(
    snapshot: dict[str, Any],
    key: str,
) -> int | None:
    value = snapshot.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _snapshot_boolean(
    snapshot: dict[str, Any],
    key: str,
) -> bool | None:
    value = snapshot.get(key)
    return value if isinstance(value, bool) else None


def _snapshot_string_list(
    snapshot: dict[str, Any],
    key: str,
) -> list[str]:
    value = snapshot.get(key)
    if not isinstance(value, list):
        return []
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return normalized


def _snapshot_integer_with_fallback(
    primary: dict[str, Any],
    fallback: dict[str, Any],
    key: str,
) -> int | None:
    value = _snapshot_integer(primary, key)
    return value if value is not None else _snapshot_integer(fallback, key)


def _pending_invoice(
    *,
    invoice: DbBillingInvoice,
    purchase: DbCreditPurchase,
) -> PendingBillingInvoice:
    package_snapshot = _snapshot_mapping(purchase.snapshot)
    raw_payment_snapshot = purchase.payment_snapshot
    payment_snapshot = _snapshot_mapping(raw_payment_snapshot)
    raw_customer_snapshot = purchase.customer_snapshot
    customer_snapshot = _snapshot_mapping(raw_customer_snapshot)
    tax_snapshot = _snapshot_mapping(purchase.tax_snapshot)
    document_snapshot = _snapshot_mapping(invoice.document_snapshot)
    payment = (
        PendingBillingPayment(
            checkout_session_id=_snapshot_string(
                payment_snapshot,
                "checkout_session_id",
            ),
            payment_intent_id=_snapshot_string(
                payment_snapshot,
                "payment_intent_id",
            ),
            confirmed_at=_snapshot_integer(
                payment_snapshot,
                "stripe_event_created",
            ),
            livemode=_snapshot_boolean(payment_snapshot, "livemode"),
            amount_paid_cents=_snapshot_integer(
                payment_snapshot,
                "amount_paid_cents",
            ),
            currency=(
                _snapshot_string(payment_snapshot, "currency") or _snapshot_string(document_snapshot, "currency")
            ),
            payment_status=_snapshot_string(
                payment_snapshot,
                "payment_status",
            ),
        )
        if isinstance(raw_payment_snapshot, dict)
        else None
    )
    customer = (
        PendingBillingCustomer(
            name=_snapshot_string(customer_snapshot, "name"),
            email=_snapshot_string(customer_snapshot, "email"),
            country=_snapshot_string(customer_snapshot, "country"),
            city=_snapshot_string(customer_snapshot, "city"),
            postal_code=_snapshot_string(customer_snapshot, "postal_code"),
            line1=_snapshot_string(customer_snapshot, "line1"),
            line2=_snapshot_string(customer_snapshot, "line2"),
            state=_snapshot_string(customer_snapshot, "state"),
            status=_snapshot_string(customer_snapshot, "status"),
            missing_required_fields=_snapshot_string_list(
                customer_snapshot,
                "missing_required_fields",
            ),
        )
        if isinstance(raw_customer_snapshot, dict)
        else None
    )
    return PendingBillingInvoice(
        invoice_id=invoice.id,
        purchase_id=purchase.id,
        document_status=invoice.document_status,
        purchase_status=purchase.status,
        provider=invoice.provider,
        document_kind=invoice.document_kind,
        refunded_amount_cents=purchase.refunded_amount_cents,
        reversed_amount_cents=purchase.reversed_amount_cents,
        reversed_credits=purchase.reversed_credits,
        dispute_active=purchase.dispute_active,
        requires_reversal_review=_requires_reversal_review(purchase),
        aade_document_type=invoice.aade_document_type,
        aade_series=invoice.aade_series,
        aade_aa=invoice.aade_aa,
        aade_mark=invoice.aade_mark,
        issued_at=invoice.issued_at,
        recorded_at=invoice.recorded_at,
        created_at=invoice.created_at,
        financial_retention_until=invoice.financial_retention_until,
        package=PendingBillingPackage(
            key=_snapshot_string(package_snapshot, "package_key"),
            credits=_snapshot_integer(package_snapshot, "credits"),
        ),
        payment=payment,
        customer=customer,
        tax=PendingBillingTax(
            gross_amount_cents=_snapshot_integer_with_fallback(
                tax_snapshot,
                document_snapshot,
                "gross_amount_cents",
            ),
            net_amount_cents=_snapshot_integer_with_fallback(
                tax_snapshot,
                document_snapshot,
                "net_amount_cents",
            ),
            vat_amount_cents=_snapshot_integer_with_fallback(
                tax_snapshot,
                document_snapshot,
                "vat_amount_cents",
            ),
            vat_rate_percent=_snapshot_integer_with_fallback(
                tax_snapshot,
                document_snapshot,
                "vat_rate_percent",
            ),
        ),
        service=PendingBillingService(
            code=_snapshot_string(document_snapshot, "service_code"),
            name=_snapshot_string(document_snapshot, "service_name"),
        ),
    )


def _requires_reversal_review(purchase: DbCreditPurchase) -> bool:
    return (
        purchase.refunded_amount_cents > 0
        or purchase.reversed_amount_cents > 0
        or purchase.reversed_credits > 0
        or purchase.dispute_active
    )


def _requires_reversal_review_predicate() -> ColumnElement[bool]:
    return or_(
        DbCreditPurchase.refunded_amount_cents > 0,
        DbCreditPurchase.reversed_amount_cents > 0,
        DbCreditPurchase.reversed_credits > 0,
        DbCreditPurchase.dispute_active.is_(True),
    )


def _payment_confirmation_at(
    *,
    invoice: DbBillingInvoice,
    purchase: DbCreditPurchase,
) -> int:
    snapshot = purchase.payment_snapshot
    if snapshot is None:
        document_snapshot = invoice.document_snapshot
        is_legacy_record = (
            isinstance(document_snapshot, dict)
            and document_snapshot.get("legacy_incomplete") is True
            and document_snapshot.get("migration_source") == "0013_durable_billing_records"
        )
        if invoice.document_status != "manual_review_required" or not is_legacy_record:
            raise HTTPException(
                status_code=409,
                detail="Stripe payment confirmation timestamp is unavailable",
            )
        if purchase.fulfilled_at is None:
            raise HTTPException(
                status_code=409,
                detail="Stripe payment fulfillment timestamp is unavailable",
            )
        fulfillment_at = int(purchase.fulfilled_at)
        if fulfillment_at <= 0:
            raise HTTPException(
                status_code=409,
                detail="Stripe payment fulfillment timestamp is invalid",
            )
        return fulfillment_at
    if not isinstance(snapshot, dict):
        raise HTTPException(
            status_code=409,
            detail="Stripe payment confirmation timestamp is invalid",
        )

    raw_confirmation_at = snapshot.get("stripe_event_created")
    if raw_confirmation_at is None or isinstance(raw_confirmation_at, bool):
        raise HTTPException(
            status_code=409,
            detail="Stripe payment confirmation timestamp is invalid",
        )
    try:
        confirmation_at = int(raw_confirmation_at)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail="Stripe payment confirmation timestamp is invalid",
        ) from exc
    if confirmation_at <= 0:
        raise HTTPException(
            status_code=409,
            detail="Stripe payment confirmation timestamp is invalid",
        )
    return confirmation_at
