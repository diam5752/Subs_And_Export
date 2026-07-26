"""Fail-closed admin handoff for manually issued AADE documents."""

from __future__ import annotations

import os
import re
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from backend.app.core.auth import User
from backend.app.core.database import Database
from backend.app.db.models import DbBillingInvoice, DbCreditPurchase
from backend.app.services.financial_records import financial_retention_deadline

from ..deps import get_current_user, get_db

router = APIRouter()
_PENDING_DOCUMENT_STATUSES = (
    "pending_manual_issue",
    "manual_review_required",
)
_ALLOWED_SERIES_PUNCTUATION = frozenset("-._/")
_ADMIN_USER_ID = re.compile(r"^[0-9a-f]{16,64}$")


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
    created_at: int
    financial_retention_until: int
    package_snapshot: dict[str, Any]
    payment_snapshot: dict[str, Any] | None
    customer_snapshot: dict[str, Any] | None
    tax_snapshot: dict[str, Any] | None
    document_snapshot: dict[str, Any]


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
    mark: str = Field(..., min_length=1, max_length=160, pattern=r"^[0-9]+$")
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


class RecordedAadeDocumentResponse(BaseModel):
    invoice_id: str
    purchase_id: str
    document_status: str
    aade_document_type: str
    aade_series: str
    aade_aa: str
    aade_mark: str
    issued_at: int
    financial_retention_until: int


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


def _pending_invoice(
    *,
    invoice: DbBillingInvoice,
    purchase: DbCreditPurchase,
) -> PendingBillingInvoice:
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
        created_at=invoice.created_at,
        financial_retention_until=invoice.financial_retention_until,
        package_snapshot=purchase.snapshot,
        payment_snapshot=purchase.payment_snapshot,
        customer_snapshot=purchase.customer_snapshot,
        tax_snapshot=purchase.tax_snapshot,
        document_snapshot=invoice.document_snapshot,
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
        return int(purchase.fulfilled_at or purchase.created_at)
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


@router.post(
    "/admin/invoices/{invoice_id}/record-issued",
    response_model=RecordedAadeDocumentResponse,
)
def record_issued_aade_document(
    payload: RecordIssuedAadeDocumentRequest,
    invoice_id: str = Path(
        ...,
        min_length=32,
        max_length=32,
        pattern=r"^[0-9a-f]{32}$",
    ),
    current_user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> RecordedAadeDocumentResponse:
    """Record, without issuing, one already-issued AADE document exactly once."""
    _ensure_admin(current_user)
    now = int(time.time())
    if payload.issued_at > now:
        raise HTTPException(
            status_code=400,
            detail="AADE issued_at cannot be in the future",
        )

    try:
        with db.session() as session:
            purchase_id = session.scalar(
                select(DbBillingInvoice.purchase_id)
                .where(DbBillingInvoice.id == invoice_id)
                .limit(1)
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
                select(DbCreditPurchase)
                .where(DbCreditPurchase.id == purchase_id)
                .with_for_update()
                .limit(1)
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
            if (
                invoice.document_status not in _PENDING_DOCUMENT_STATUSES
                or invoice.aade_document_type is not None
                or invoice.aade_series is not None
                or invoice.aade_aa is not None
                or invoice.aade_mark is not None
                or invoice.issued_at is not None
            ):
                raise HTTPException(
                    status_code=409,
                    detail="AADE document has already been recorded",
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

            issued_retention = financial_retention_deadline(payload.issued_at)
            invoice.aade_document_type = payload.document_type
            invoice.aade_series = payload.series
            invoice.aade_aa = payload.aa
            invoice.aade_mark = payload.mark
            invoice.issued_at = payload.issued_at
            invoice.document_status = "issued"
            invoice.financial_retention_until = max(
                int(invoice.financial_retention_until),
                issued_retention,
            )
            invoice.updated_at = now
            purchase.financial_retention_until = max(
                int(purchase.financial_retention_until),
                issued_retention,
            )
            purchase.updated_at = max(int(purchase.updated_at), now)
            session.flush()

            response = RecordedAadeDocumentResponse(
                invoice_id=invoice.id,
                purchase_id=purchase.id,
                document_status=invoice.document_status,
                aade_document_type=invoice.aade_document_type,
                aade_series=invoice.aade_series,
                aade_aa=invoice.aade_aa,
                aade_mark=invoice.aade_mark,
                issued_at=invoice.issued_at,
                financial_retention_until=invoice.financial_retention_until,
            )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="AADE document identity conflicts with an existing record",
        ) from exc
    return response
