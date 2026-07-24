"""Public credit catalog and authenticated Stripe Checkout routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from backend.app.core.auth import User
from backend.app.services.billing import (
    BillingConflictError,
    BillingDisabledError,
    BillingProviderError,
    BillingService,
    BillingValidationError,
    public_credit_catalog,
)

from ..deps import get_billing_service, get_current_user

router = APIRouter()
_MAX_WEBHOOK_BYTES = 1_000_000


class CheckoutRequest(BaseModel):
    package_key: str = Field(..., min_length=1, max_length=32)


class CheckoutResponse(BaseModel):
    purchase_id: str
    checkout_session_id: str | None
    checkout_url: str | None
    status: str


class WalletResponse(BaseModel):
    balance: int
    paid_balance: int
    promotional_balance: int
    reversal_debt: int
    ai_spendable_balance: int


class PurchaseStatusResponse(BaseModel):
    purchase_id: str
    package_key: str
    credits: int
    amount_eur_cents: int
    status: str
    checkout_session_id: str | None
    wallet: WalletResponse


@router.get("/catalog")
def get_catalog() -> dict[str, Any]:
    """Expose immutable package amounts and video-duration brackets."""
    return public_credit_catalog()


@router.post("/checkout", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    idempotency_key: str = Header(..., alias="Idempotency-Key", max_length=64),
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> CheckoutResponse:
    try:
        result = billing_service.create_checkout(
            user_id=current_user.id,
            customer_email=current_user.email,
            package_key=payload.package_key,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise _http_billing_error(exc) from exc
    return CheckoutResponse(
        purchase_id=result.purchase_id,
        checkout_session_id=result.checkout_session_id,
        checkout_url=result.checkout_url,
        status=result.status,
    )


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="Stripe-Signature", max_length=2048),
    billing_service: BillingService = Depends(get_billing_service),
) -> dict[str, str]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > _MAX_WEBHOOK_BYTES:
                raise HTTPException(status_code=413, detail="Webhook payload is too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    payload = await request.body()
    if not payload or len(payload) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    try:
        result = billing_service.verify_and_process_webhook(
            payload=payload,
            signature=stripe_signature,
        )
    except Exception as exc:
        raise _http_billing_error(exc) from exc
    return {
        "event_id": result.event_id,
        "event_type": result.event_type,
        "status": result.status,
    }


@router.get("/checkout/{checkout_session_id}", response_model=PurchaseStatusResponse)
def checkout_status(
    checkout_session_id: str,
    current_user: User = Depends(get_current_user),
    billing_service: BillingService = Depends(get_billing_service),
) -> PurchaseStatusResponse:
    try:
        result = billing_service.get_purchase_status(
            user_id=current_user.id,
            checkout_session_id=checkout_session_id,
        )
    except Exception as exc:
        raise _http_billing_error(exc) from exc
    return PurchaseStatusResponse(
        purchase_id=result.purchase_id,
        package_key=result.package_key,
        credits=result.credits,
        amount_eur_cents=result.amount_eur_cents,
        status=result.status,
        checkout_session_id=result.checkout_session_id,
        wallet=WalletResponse(
            balance=result.wallet.balance,
            paid_balance=result.wallet.paid_balance,
            promotional_balance=result.wallet.promotional_balance,
            reversal_debt=result.wallet.reversal_debt,
            ai_spendable_balance=result.wallet.ai_spendable_balance,
        ),
    )


def _http_billing_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BillingDisabledError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, BillingConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, BillingValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, BillingProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Billing operation failed")
