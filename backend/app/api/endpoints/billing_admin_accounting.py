"""Idempotent recording of already-issued AADE documents."""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from backend.app.api.endpoints.billing_admin_models import (
    RecordedAadeDocumentResponse,
    RecordedManualRefundAccountingResponse,
    RecordIssuedAadeDocumentRequest,
    RecordManualRefundAccountingRequest,
)
from backend.app.api.endpoints.billing_admin_support import (
    _PENDING_DOCUMENT_STATUSES,
    _disable_sensitive_response_caching,
    _ensure_admin,
    _ensure_greek_b2c_aade_baseline,
    _ensure_recent_admin_session,
    _is_exact_adjustment_replay,
    _is_exact_issued_document_replay,
    _payment_confirmation_at,
    _record_original_document_for_refund,
    _recorded_document_response,
    _recorded_manual_refund_response,
    _requires_reversal_review,
)
from backend.app.core.auth import SessionStore, User
from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingInvoice,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_manual_records import (
    BillingManualRecordError,
    new_billing_adjustment_record,
    verify_billing_adjustment_record,
)
from backend.app.services.financial_records import financial_retention_deadline

from ..deps import (
    get_current_session_token,
    get_current_user,
    get_db,
    get_session_store,
)

router = APIRouter()


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
