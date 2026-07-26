"""Fail-closed admin handoff for manually issued AADE documents."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from backend.app.core.auth import SessionStore, User
from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordConflictError,
    verify_contract_confirmation,
    verify_withdrawal_record,
)
from backend.app.services.billing_manual_records import (
    BillingManualRecordError,
    new_billing_adjustment_record,
    new_withdrawal_resolution,
    verify_billing_adjustment_record,
    verify_withdrawal_resolution,
)
from backend.app.services.billing_records import (
    AADE_GREEK_B2C_DOCUMENT_TYPE,
    AADE_GREEK_B2C_SERIES,
)
from backend.app.services.financial_records import financial_retention_deadline

from ..deps import (
    get_current_session_token,
    get_current_user,
    get_db,
    get_session_store,
)

router = APIRouter()
_PENDING_DOCUMENT_STATUSES = (
    "pending_manual_issue",
    "manual_review_required",
)
_ALLOWED_SERIES_PUNCTUATION = frozenset("-._/")
_ADMIN_USER_ID = re.compile(r"^[0-9a-f]{16,64}$")
_MAX_SIGNED_64_BIT_INTEGER = 9_223_372_036_854_775_807
_ADMIN_WRITE_SESSION_MAX_AGE_SECONDS = 15 * 60


class _PrivacyMinimizedResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PendingBillingPackage(_PrivacyMinimizedResponseModel):
    key: str | None
    credits: int | None


class PendingBillingPayment(_PrivacyMinimizedResponseModel):
    checkout_session_id: str | None
    payment_intent_id: str | None
    confirmed_at: int | None
    livemode: bool | None
    amount_paid_cents: int | None
    currency: str | None
    payment_status: str | None


class PendingBillingCustomer(_PrivacyMinimizedResponseModel):
    name: str | None
    email: str | None
    country: str | None
    city: str | None
    postal_code: str | None
    line1: str | None
    line2: str | None
    state: str | None
    status: str | None
    missing_required_fields: list[str]


class PendingBillingTax(_PrivacyMinimizedResponseModel):
    gross_amount_cents: int | None
    net_amount_cents: int | None
    vat_amount_cents: int | None
    vat_rate_percent: int | None


class PendingBillingService(_PrivacyMinimizedResponseModel):
    code: str | None
    name: str | None


class PendingBillingInvoice(BaseModel):
    invoice_id: str
    purchase_id: str
    document_status: str
    purchase_status: str
    provider: str
    document_kind: str
    refunded_amount_cents: int
    reversed_amount_cents: int
    reversed_credits: int
    dispute_active: bool
    requires_reversal_review: bool
    aade_document_type: str | None
    aade_series: str | None
    aade_aa: str | None
    aade_mark: str | None
    issued_at: int | None
    recorded_at: int | None
    created_at: int
    financial_retention_until: int
    package: PendingBillingPackage
    payment: PendingBillingPayment | None
    customer: PendingBillingCustomer | None
    tax: PendingBillingTax
    service: PendingBillingService


class PendingBillingInvoicesResponse(BaseModel):
    items: list[PendingBillingInvoice]
    count: int
    next_cursor: str | None


class RecordIssuedAadeDocumentRequest(BaseModel):
    document_type: str = Field(
        ...,
        min_length=1,
        max_length=32,
        pattern=r"^[0-9]{1,2}(?:\.[0-9]{1,2})?$",
    )
    series: str = Field(..., min_length=1, max_length=32)
    aa: str = Field(..., min_length=1, max_length=64, pattern=r"^[0-9]+$")
    mark: str = Field(
        ...,
        min_length=1,
        max_length=19,
        pattern=r"^[1-9][0-9]{0,18}$",
    )
    issued_at: int = Field(..., gt=0)

    @field_validator("series")
    @classmethod
    def validate_series(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("AADE series cannot be empty")
        if any(not (character.isalnum() or character in _ALLOWED_SERIES_PUNCTUATION) for character in normalized):
            raise ValueError("AADE series contains unsupported characters")
        return normalized

    @field_validator("mark")
    @classmethod
    def validate_mark(cls, value: str) -> str:
        if int(value) > _MAX_SIGNED_64_BIT_INTEGER:
            raise ValueError("AADE MARK exceeds the signed 64-bit range")
        return value


class RecordedAadeDocumentResponse(BaseModel):
    invoice_id: str
    purchase_id: str
    document_status: str
    aade_document_type: str
    aade_series: str
    aade_aa: str
    aade_mark: str
    issued_at: int
    recorded_at: int
    financial_retention_until: int


class RecordManualRefundAccountingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_document: RecordIssuedAadeDocumentRequest | None = None
    adjustment_document: RecordIssuedAadeDocumentRequest
    final_manual_actions_confirmed: StrictBool

    @model_validator(mode="after")
    def require_manual_confirmation(
        self,
    ) -> RecordManualRefundAccountingRequest:
        if not self.final_manual_actions_confirmed:
            raise ValueError(
                "Final manual refund and AADE actions must be confirmed",
            )
        return self


class PendingRefundReview(_PrivacyMinimizedResponseModel):
    reversal_id: str
    stripe_refund_id: str
    stripe_refund_status: str
    stripe_refund_created_at: int
    amount_cents: int
    currency: str
    linked_withdrawal_id: str | None
    original_invoice: PendingBillingInvoice


class PendingRefundReviewsResponse(BaseModel):
    items: list[PendingRefundReview]
    count: int
    next_cursor: str | None


class RecordedManualRefundAccountingResponse(BaseModel):
    adjustment_id: str
    purchase_id: str
    reversal_id: str
    stripe_refund_id: str
    amount_cents: int
    currency: str
    aade_document_type: str
    aade_series: str
    aade_aa: str
    aade_mark: str
    issued_at: int
    recorded_at: int
    financial_retention_until: int
    original_invoice_status: str
    original_invoice_mark: str


class PendingWithdrawalAdjustment(_PrivacyMinimizedResponseModel):
    adjustment_id: str
    stripe_refund_id: str
    amount_cents: int
    currency: str
    aade_document_type: str
    aade_series: str
    aade_aa: str
    aade_mark: str
    issued_at: int


class PendingWithdrawalReview(_PrivacyMinimizedResponseModel):
    withdrawal_id: str
    purchase_id: str
    locale: str
    submitted_at: int
    contract_concluded_at: int
    confirmed_name: str
    confirmation_email: str
    available_adjustments: list[PendingWithdrawalAdjustment]


class PendingWithdrawalReviewsResponse(BaseModel):
    items: list[PendingWithdrawalReview]
    count: int
    next_cursor: str | None


class ResolveWithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["accepted_refunded", "rejected"]
    adjustment_id: str | None = Field(
        default=None,
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-f]{32}$",
    )
    customer_explanation: str = Field(
        ...,
        min_length=20,
        max_length=1_000,
    )
    final_manual_review_confirmed: StrictBool

    @field_validator("customer_explanation")
    @classmethod
    def validate_customer_explanation(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError(
                "Customer explanation cannot have surrounding whitespace",
            )
        return value

    @model_validator(mode="after")
    def require_matching_evidence(self) -> ResolveWithdrawalRequest:
        if not self.final_manual_review_confirmed:
            raise ValueError(
                "Final manual withdrawal review must be confirmed",
            )
        if self.decision == "accepted_refunded" and self.adjustment_id is None:
            raise ValueError(
                "Accepted withdrawal requires an adjustment record",
            )
        if self.decision == "rejected" and self.adjustment_id is not None:
            raise ValueError(
                "Rejected withdrawal cannot claim an adjustment record",
            )
        return self


class WithdrawalResolutionResponse(BaseModel):
    resolution_id: str
    withdrawal_id: str
    purchase_id: str
    decision: Literal["accepted_refunded", "rejected"]
    reason_code: str
    adjustment_id: str | None
    resolved_at: int
    resolution_sha256: str
    resolution_url: str


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


@router.get(
    "/admin/invoices/pending",
    response_model=PendingBillingInvoicesResponse,
)
def list_pending_billing_invoices(
    response: Response,
    limit: int = Query(100, ge=1, le=100),
    after: str | None = Query(
        None,
        min_length=34,
        max_length=53,
        pattern=r"^[0-9]{1,20}:[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> PendingBillingInvoicesResponse:
    """List pending documents and issued documents needing reversal review."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    cursor_created_at: int | None = None
    cursor_invoice_id: str | None = None
    if after is not None:
        raw_created_at, cursor_invoice_id = after.split(":", maxsplit=1)
        cursor_created_at = int(raw_created_at)

    with db.session() as session:
        query = (
            select(DbBillingInvoice, DbCreditPurchase)
            .join(
                DbCreditPurchase,
                DbCreditPurchase.id == DbBillingInvoice.purchase_id,
            )
            .where(
                or_(
                    DbBillingInvoice.document_status.in_(_PENDING_DOCUMENT_STATUSES),
                    _requires_reversal_review_predicate(),
                )
            )
        )
        if cursor_created_at is not None and cursor_invoice_id is not None:
            query = query.where(
                or_(
                    DbBillingInvoice.created_at > cursor_created_at,
                    and_(
                        DbBillingInvoice.created_at == cursor_created_at,
                        DbBillingInvoice.id > cursor_invoice_id,
                    ),
                )
            )
        rows = session.execute(
            query.order_by(
                DbBillingInvoice.created_at.asc(),
                DbBillingInvoice.id.asc(),
            ).limit(limit + 1)
        ).all()
        page = rows[:limit]
        items = [_pending_invoice(invoice=invoice, purchase=purchase) for invoice, purchase in page]
        next_cursor = None
        if len(rows) > limit and page:
            last_invoice = page[-1][0]
            next_cursor = f"{last_invoice.created_at}:{last_invoice.id}"
    return PendingBillingInvoicesResponse(
        items=items,
        count=len(items),
        next_cursor=next_cursor,
    )


@router.get(
    "/admin/refunds/pending",
    response_model=PendingRefundReviewsResponse,
)
def list_pending_refund_reviews(
    response: Response,
    limit: int = Query(100, ge=1, le=100),
    after: str | None = Query(
        None,
        min_length=34,
        max_length=53,
        pattern=r"^[0-9]{1,20}:[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> PendingRefundReviewsResponse:
    """List completed Stripe refunds missing a recorded AADE adjustment."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    cursor_created_at: int | None = None
    cursor_reversal_id: str | None = None
    if after is not None:
        raw_created_at, cursor_reversal_id = after.split(":", maxsplit=1)
        cursor_created_at = int(raw_created_at)

    with db.session() as session:
        query = (
            select(
                DbCreditPurchaseReversal,
                DbCreditPurchase,
                DbBillingInvoice,
            )
            .join(
                DbCreditPurchase,
                DbCreditPurchase.id == DbCreditPurchaseReversal.purchase_id,
            )
            .join(
                DbBillingInvoice,
                DbBillingInvoice.purchase_id == DbCreditPurchase.id,
            )
            .outerjoin(
                DbBillingAdjustmentRecord,
                DbBillingAdjustmentRecord.reversal_id == DbCreditPurchaseReversal.id,
            )
            .where(
                DbCreditPurchaseReversal.provider == "stripe",
                DbCreditPurchaseReversal.kind == "refund",
                DbCreditPurchaseReversal.provider_reversal_id.like(
                    "re_%",
                ),
                DbCreditPurchaseReversal.status == "succeeded",
                DbCreditPurchaseReversal.active.is_(True),
                DbBillingAdjustmentRecord.id.is_(None),
            )
        )
        if cursor_created_at is not None and cursor_reversal_id is not None:
            query = query.where(
                or_(
                    DbCreditPurchaseReversal.provider_event_created > cursor_created_at,
                    and_(
                        DbCreditPurchaseReversal.provider_event_created == cursor_created_at,
                        DbCreditPurchaseReversal.id > cursor_reversal_id,
                    ),
                )
            )
        rows = session.execute(
            query.order_by(
                DbCreditPurchaseReversal.provider_event_created.asc(),
                DbCreditPurchaseReversal.id.asc(),
            ).limit(limit + 1)
        ).all()
        page = rows[:limit]
        purchase_ids = [purchase.id for _, purchase, _ in page]
        linked_withdrawals = (
            {
                withdrawal.purchase_id: withdrawal.id
                for withdrawal in session.scalars(
                    select(DbBillingWithdrawalRequest)
                    .outerjoin(
                        DbBillingWithdrawalResolution,
                        DbBillingWithdrawalResolution.withdrawal_id == DbBillingWithdrawalRequest.id,
                    )
                    .where(
                        DbBillingWithdrawalRequest.purchase_id.in_(
                            purchase_ids,
                        ),
                        DbBillingWithdrawalResolution.id.is_(None),
                    )
                )
            }
            if purchase_ids
            else {}
        )
        items = [
            PendingRefundReview(
                reversal_id=reversal.id,
                stripe_refund_id=reversal.provider_reversal_id,
                stripe_refund_status=reversal.status,
                stripe_refund_created_at=(reversal.provider_event_created),
                amount_cents=reversal.amount_cents,
                currency=reversal.currency,
                linked_withdrawal_id=linked_withdrawals.get(
                    purchase.id,
                ),
                original_invoice=_pending_invoice(
                    invoice=invoice,
                    purchase=purchase,
                ),
            )
            for reversal, purchase, invoice in page
        ]
        next_cursor = None
        if len(rows) > limit and page:
            last_reversal = page[-1][0]
            next_cursor = f"{last_reversal.provider_event_created}:{last_reversal.id}"
    return PendingRefundReviewsResponse(
        items=items,
        count=len(items),
        next_cursor=next_cursor,
    )


@router.get(
    "/admin/withdrawals/pending",
    response_model=PendingWithdrawalReviewsResponse,
)
def list_pending_withdrawal_reviews(
    response: Response,
    limit: int = Query(100, ge=1, le=100),
    after: str | None = Query(
        None,
        min_length=34,
        max_length=53,
        pattern=r"^[0-9]{1,20}:[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> PendingWithdrawalReviewsResponse:
    """List unresolved consumer requests and completed manual evidence."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    cursor_submitted_at: int | None = None
    cursor_withdrawal_id: str | None = None
    if after is not None:
        raw_submitted_at, cursor_withdrawal_id = after.split(
            ":",
            maxsplit=1,
        )
        cursor_submitted_at = int(raw_submitted_at)

    with db.session() as session:
        query = (
            select(
                DbBillingWithdrawalRequest,
                DbCreditPurchase,
                DbBillingContractConfirmation,
            )
            .join(
                DbCreditPurchase,
                DbCreditPurchase.id == DbBillingWithdrawalRequest.purchase_id,
            )
            .join(
                DbBillingContractConfirmation,
                DbBillingContractConfirmation.purchase_id == DbBillingWithdrawalRequest.purchase_id,
            )
            .outerjoin(
                DbBillingWithdrawalResolution,
                DbBillingWithdrawalResolution.withdrawal_id == DbBillingWithdrawalRequest.id,
            )
            .where(DbBillingWithdrawalResolution.id.is_(None))
        )
        if cursor_submitted_at is not None and cursor_withdrawal_id is not None:
            query = query.where(
                or_(
                    DbBillingWithdrawalRequest.submitted_at > cursor_submitted_at,
                    and_(
                        DbBillingWithdrawalRequest.submitted_at == cursor_submitted_at,
                        DbBillingWithdrawalRequest.id > cursor_withdrawal_id,
                    ),
                )
            )
        rows = session.execute(
            query.order_by(
                DbBillingWithdrawalRequest.submitted_at.asc(),
                DbBillingWithdrawalRequest.id.asc(),
            ).limit(limit + 1)
        ).all()
        page = rows[:limit]
        purchase_ids = [purchase.id for _, purchase, _ in page]
        adjustment_rows = (
            session.execute(
                select(
                    DbBillingAdjustmentRecord,
                    DbCreditPurchaseReversal,
                )
                .join(
                    DbCreditPurchaseReversal,
                    DbCreditPurchaseReversal.id == DbBillingAdjustmentRecord.reversal_id,
                )
                .outerjoin(
                    DbBillingWithdrawalResolution,
                    DbBillingWithdrawalResolution.adjustment_id == DbBillingAdjustmentRecord.id,
                )
                .where(
                    DbBillingAdjustmentRecord.purchase_id.in_(purchase_ids),
                    DbBillingWithdrawalResolution.id.is_(None),
                    DbCreditPurchaseReversal.status == "succeeded",
                    DbCreditPurchaseReversal.active.is_(True),
                )
            ).all()
            if purchase_ids
            else []
        )
        adjustments_by_purchase: dict[
            str,
            list[
                tuple[
                    DbBillingAdjustmentRecord,
                    DbCreditPurchaseReversal,
                ]
            ],
        ] = {}
        for adjustment, reversal in adjustment_rows:
            adjustments_by_purchase.setdefault(
                adjustment.purchase_id,
                [],
            ).append((adjustment, reversal))

        items: list[PendingWithdrawalReview] = []
        for withdrawal, purchase, confirmation in page:
            try:
                verify_contract_confirmation(
                    confirmation,
                    purchase=purchase,
                )
                verify_withdrawal_record(
                    withdrawal,
                    purchase=purchase,
                    confirmation=confirmation,
                )
            except BillingConsumerRecordConflictError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Withdrawal review is unavailable because durable request evidence failed integrity validation"
                    ),
                ) from exc
            request_snapshot = _snapshot_mapping(
                withdrawal.request_snapshot,
            )
            electronic_means = _snapshot_mapping(
                request_snapshot.get("confirmation_electronic_means"),
            )
            confirmed_name = _snapshot_string(
                request_snapshot,
                "confirmed_name",
            )
            confirmation_email = _snapshot_string(
                electronic_means,
                "address",
            )
            if confirmed_name is None or confirmation_email is None:
                raise HTTPException(
                    status_code=409,
                    detail=("Withdrawal request contact evidence is incomplete"),
                )
            available_adjustments: list[PendingWithdrawalAdjustment] = []
            for adjustment, reversal in adjustments_by_purchase.get(
                purchase.id,
                [],
            ):
                try:
                    verify_billing_adjustment_record(
                        adjustment,
                        purchase=purchase,
                        reversal=reversal,
                    )
                except BillingManualRecordError as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=("Withdrawal review is unavailable because refund evidence failed integrity validation"),
                    ) from exc
                available_adjustments.append(
                    PendingWithdrawalAdjustment(
                        adjustment_id=adjustment.id,
                        stripe_refund_id=(reversal.provider_reversal_id),
                        amount_cents=adjustment.amount_cents,
                        currency=adjustment.currency,
                        aade_document_type=(adjustment.aade_document_type),
                        aade_series=adjustment.aade_series,
                        aade_aa=adjustment.aade_aa,
                        aade_mark=adjustment.aade_mark,
                        issued_at=adjustment.issued_at,
                    )
                )
            items.append(
                PendingWithdrawalReview(
                    withdrawal_id=withdrawal.id,
                    purchase_id=purchase.id,
                    locale=withdrawal.locale,
                    submitted_at=withdrawal.submitted_at,
                    contract_concluded_at=(confirmation.contract_concluded_at),
                    confirmed_name=confirmed_name,
                    confirmation_email=confirmation_email,
                    available_adjustments=available_adjustments,
                )
            )
        next_cursor = None
        if len(rows) > limit and page:
            last_withdrawal = page[-1][0]
            next_cursor = f"{last_withdrawal.submitted_at}:{last_withdrawal.id}"
    return PendingWithdrawalReviewsResponse(
        items=items,
        count=len(items),
        next_cursor=next_cursor,
    )


@router.post(
    "/admin/invoices/{invoice_id}/record-issued",
    response_model=RecordedAadeDocumentResponse,
)
def record_issued_aade_document(
    payload: RecordIssuedAadeDocumentRequest,
    response: Response,
    invoice_id: str = Path(
        ...,
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    current_token: str = Depends(get_current_session_token),
    session_store: SessionStore = Depends(get_session_store),
    db: Database = Depends(get_db),
) -> RecordedAadeDocumentResponse:
    """Record, without issuing, one already-issued AADE document exactly once."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    now = int(time.time())
    _ensure_recent_admin_session(
        token=current_token,
        session_store=session_store,
        now=now,
    )
    if payload.issued_at > now:
        raise HTTPException(
            status_code=400,
            detail="AADE issued_at cannot be in the future",
        )

    try:
        with db.session() as session:
            purchase_id = session.scalar(
                select(DbBillingInvoice.purchase_id).where(DbBillingInvoice.id == invoice_id).limit(1)
            )
            if purchase_id is None:
                raise HTTPException(
                    status_code=404,
                    detail="Billing invoice not found",
                )
            # Every financial writer and retention cleanup path locks the
            # purchase before its invoice/reversal children. A joined
            # SELECT ... FOR UPDATE leaves PostgreSQL free to lock the invoice
            # first, which can deadlock against those parent-first writers.
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            if purchase is None:
                raise HTTPException(
                    status_code=404,
                    detail="Billing invoice not found",
                )
            invoice = session.scalar(
                select(DbBillingInvoice)
                .where(
                    DbBillingInvoice.id == invoice_id,
                    DbBillingInvoice.purchase_id == purchase.id,
                )
                .with_for_update()
                .limit(1)
            )
            if invoice is None:
                raise HTTPException(
                    status_code=404,
                    detail="Billing invoice not found",
                )
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
                if _is_exact_issued_document_replay(
                    invoice=invoice,
                    payload=payload,
                ):
                    if _requires_reversal_review(purchase):
                        raise HTTPException(
                            status_code=409,
                            detail=("Purchase requires reversal accounting review before recording an AADE document"),
                        )
                    return _recorded_document_response(
                        invoice=invoice,
                        purchase=purchase,
                    )
                raise HTTPException(
                    status_code=409,
                    detail="AADE document has already been recorded",
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
                    detail="AADE issued_at cannot predate the confirmed payment",
                )
            if _requires_reversal_review(purchase):
                raise HTTPException(
                    status_code=409,
                    detail=("Purchase requires reversal accounting review before recording an AADE document"),
                )

            audit_retention = max(
                financial_retention_deadline(payload.issued_at),
                financial_retention_deadline(now),
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
                audit_retention,
            )
            invoice.updated_at = now
            purchase.financial_retention_until = max(
                int(purchase.financial_retention_until),
                audit_retention,
            )
            purchase.updated_at = max(int(purchase.updated_at), now)
            session.flush()

            recorded_document_response = _recorded_document_response(
                invoice=invoice,
                purchase=purchase,
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="AADE document identity conflicts with an existing record",
        ) from exc
    return recorded_document_response


@router.post(
    "/admin/refunds/{reversal_id}/record-aade-adjustment",
    response_model=RecordedManualRefundAccountingResponse,
)
def record_manual_refund_accounting(
    payload: RecordManualRefundAccountingRequest,
    response: Response,
    reversal_id: str = Path(
        ...,
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    current_token: str = Depends(get_current_session_token),
    session_store: SessionStore = Depends(get_session_store),
    db: Database = Depends(get_db),
) -> RecordedManualRefundAccountingResponse:
    """Record completed Stripe and AADE actions; never perform either one."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    now = int(time.time())
    _ensure_recent_admin_session(
        token=current_token,
        session_store=session_store,
        now=now,
    )
    if payload.adjustment_document.issued_at > now:
        raise HTTPException(
            status_code=400,
            detail="AADE adjustment issued_at cannot be in the future",
        )
    if payload.original_document is not None and payload.original_document.issued_at > now:
        raise HTTPException(
            status_code=400,
            detail="Original AADE issued_at cannot be in the future",
        )

    try:
        with db.session() as session:
            purchase_id = session.scalar(
                select(DbCreditPurchaseReversal.purchase_id).where(DbCreditPurchaseReversal.id == reversal_id).limit(1)
            )
            if purchase_id is None:
                raise HTTPException(
                    status_code=404,
                    detail="Stripe refund review not found",
                )
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            if purchase is None:
                raise HTTPException(
                    status_code=404,
                    detail="Stripe refund review not found",
                )
            invoice = session.scalar(
                select(DbBillingInvoice)
                .where(
                    DbBillingInvoice.purchase_id == purchase.id,
                )
                .with_for_update()
                .limit(1)
            )
            reversal = session.scalar(
                select(DbCreditPurchaseReversal)
                .where(
                    DbCreditPurchaseReversal.id == reversal_id,
                    DbCreditPurchaseReversal.purchase_id == purchase.id,
                )
                .with_for_update()
                .limit(1)
            )
            if invoice is None or reversal is None:
                raise HTTPException(
                    status_code=404,
                    detail="Stripe refund review not found",
                )

            existing = session.scalar(
                select(DbBillingAdjustmentRecord)
                .where(
                    DbBillingAdjustmentRecord.reversal_id == reversal.id,
                )
                .limit(1)
            )
            if existing is not None:
                verify_billing_adjustment_record(
                    existing,
                    purchase=purchase,
                    reversal=reversal,
                )
                _record_original_document_for_refund(
                    invoice=invoice,
                    purchase=purchase,
                    payload=payload.original_document,
                    current_user=current_user,
                    now=now,
                )
                if not _is_exact_adjustment_replay(
                    adjustment=existing,
                    payload=payload.adjustment_document,
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=("AADE refund adjustment has already been recorded with different evidence"),
                    )
                return _recorded_manual_refund_response(
                    adjustment=existing,
                    reversal=reversal,
                    invoice=invoice,
                )

            _record_original_document_for_refund(
                invoice=invoice,
                purchase=purchase,
                payload=payload.original_document,
                current_user=current_user,
                now=now,
            )
            session.flush()
            adjustment = new_billing_adjustment_record(
                purchase=purchase,
                reversal=reversal,
                document_type=(payload.adjustment_document.document_type),
                series=payload.adjustment_document.series,
                aa=payload.adjustment_document.aa,
                mark=payload.adjustment_document.mark,
                issued_at=payload.adjustment_document.issued_at,
                actor_user_id=current_user.id,
                recorded_at=now,
            )
            session.add(adjustment)
            session.flush()
            verify_billing_adjustment_record(
                adjustment,
                purchase=purchase,
                reversal=reversal,
            )
            recorded_response = _recorded_manual_refund_response(
                adjustment=adjustment,
                reversal=reversal,
                invoice=invoice,
            )
    except BillingManualRecordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=("AADE refund adjustment identity conflicts with an existing financial record"),
        ) from exc
    return recorded_response


@router.post(
    "/admin/withdrawals/{withdrawal_id}/resolve",
    response_model=WithdrawalResolutionResponse,
)
def resolve_withdrawal_review(
    payload: ResolveWithdrawalRequest,
    response: Response,
    withdrawal_id: str = Path(
        ...,
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    current_token: str = Depends(get_current_session_token),
    session_store: SessionStore = Depends(get_session_store),
    db: Database = Depends(get_db),
) -> WithdrawalResolutionResponse:
    """Record a final human decision after all accepted-case actions exist."""
    _disable_sensitive_response_caching(response)
    _ensure_admin(current_user)
    now = int(time.time())
    _ensure_recent_admin_session(
        token=current_token,
        session_store=session_store,
        now=now,
    )
    try:
        with db.session() as session:
            purchase_id = session.scalar(
                select(DbBillingWithdrawalRequest.purchase_id)
                .where(
                    DbBillingWithdrawalRequest.id == withdrawal_id,
                )
                .limit(1)
            )
            if purchase_id is None:
                raise HTTPException(
                    status_code=404,
                    detail="Withdrawal review not found",
                )
            purchase = session.scalar(
                select(DbCreditPurchase).where(DbCreditPurchase.id == purchase_id).with_for_update().limit(1)
            )
            withdrawal = session.scalar(
                select(DbBillingWithdrawalRequest)
                .where(
                    DbBillingWithdrawalRequest.id == withdrawal_id,
                    DbBillingWithdrawalRequest.purchase_id == purchase_id,
                )
                .with_for_update()
                .limit(1)
            )
            confirmation = session.scalar(
                select(DbBillingContractConfirmation)
                .where(
                    DbBillingContractConfirmation.purchase_id == purchase_id,
                )
                .limit(1)
            )
            if purchase is None or withdrawal is None or confirmation is None:
                raise HTTPException(
                    status_code=404,
                    detail="Withdrawal review not found",
                )
            verify_contract_confirmation(
                confirmation,
                purchase=purchase,
            )
            verify_withdrawal_record(
                withdrawal,
                purchase=purchase,
                confirmation=confirmation,
            )

            adjustment: DbBillingAdjustmentRecord | None = None
            reversal: DbCreditPurchaseReversal | None = None
            if payload.adjustment_id is not None:
                adjustment = session.scalar(
                    select(DbBillingAdjustmentRecord)
                    .where(
                        DbBillingAdjustmentRecord.id == payload.adjustment_id,
                        DbBillingAdjustmentRecord.purchase_id == purchase.id,
                    )
                    .limit(1)
                )
                if adjustment is None:
                    raise HTTPException(
                        status_code=409,
                        detail=("Accepted withdrawal adjustment was not found"),
                    )
                reversal = session.scalar(
                    select(DbCreditPurchaseReversal)
                    .where(
                        DbCreditPurchaseReversal.id == adjustment.reversal_id,
                        DbCreditPurchaseReversal.purchase_id == purchase.id,
                    )
                    .with_for_update()
                    .limit(1)
                )
                if reversal is None:
                    raise HTTPException(
                        status_code=409,
                        detail=("Accepted withdrawal Stripe refund was not found"),
                    )

            existing = session.scalar(
                select(DbBillingWithdrawalResolution)
                .where(
                    DbBillingWithdrawalResolution.withdrawal_id == withdrawal.id,
                )
                .limit(1)
            )
            if existing is not None:
                verify_withdrawal_resolution(
                    existing,
                    withdrawal=withdrawal,
                    purchase=purchase,
                    adjustment=adjustment,
                    reversal=reversal,
                )
                if (
                    existing.decision != payload.decision
                    or existing.adjustment_id != payload.adjustment_id
                    or existing.resolution_snapshot.get(
                        "customer_explanation",
                    )
                    != payload.customer_explanation
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=("Withdrawal review has already been resolved with different evidence"),
                    )
                return _withdrawal_resolution_response(existing)

            resolution = new_withdrawal_resolution(
                withdrawal=withdrawal,
                purchase=purchase,
                decision=payload.decision,
                customer_explanation=payload.customer_explanation,
                actor_user_id=current_user.id,
                resolved_at=now,
                adjustment=adjustment,
                reversal=reversal,
            )
            session.add(resolution)
            session.flush()
            verify_withdrawal_resolution(
                resolution,
                withdrawal=withdrawal,
                purchase=purchase,
                adjustment=adjustment,
                reversal=reversal,
            )
            resolution_response = _withdrawal_resolution_response(
                resolution,
            )
    except BillingConsumerRecordConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=("Withdrawal request evidence failed integrity validation"),
        ) from exc
    except BillingManualRecordError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail=("Withdrawal review conflicts with an existing resolution"),
        ) from exc
    return resolution_response
