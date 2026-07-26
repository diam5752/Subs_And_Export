"""Public credit catalog and authenticated Stripe Checkout routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from backend.app.core.auth import User
from backend.app.services.billing import (
    BillingConflictError,
    BillingDisabledError,
    BillingProviderError,
    BillingService,
    BillingValidationError,
    public_credit_catalog,
)
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordConflictError,
    BillingConsumerRecordNotFoundError,
    BillingConsumerRecordStore,
    BillingConsumerRecordValidationError,
)
from backend.app.services.consumer_contracts import ConsumerContractAcceptance

from ..deps import (
    get_billing_consumer_record_store,
    get_billing_service,
    get_current_user,
)

router = APIRouter()
_MAX_WEBHOOK_BYTES = 1_000_000


class ConsumerContractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disclosure_id: str = Field(..., min_length=1, max_length=160)
    disclosure_sha256: str = Field(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    locale: Literal["el", "en"]
    policy_version: str = Field(..., min_length=1, max_length=64)
    terms_version: str = Field(..., min_length=1, max_length=64)
    withdrawal_notice_version: str = Field(..., min_length=1, max_length=64)
    terms_accepted: StrictBool
    immediate_performance_requested: StrictBool
    withdrawal_consequences_acknowledged: StrictBool

    @model_validator(mode="after")
    def require_all_acceptances(self) -> ConsumerContractRequest:
        if not (
            self.terms_accepted and self.immediate_performance_requested and self.withdrawal_consequences_acknowledged
        ):
            raise ValueError("All consumer-contract acceptances are required")
        return self


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    package_key: str = Field(..., min_length=1, max_length=32)
    catalog_version: str = Field(..., min_length=1, max_length=64)
    consumer_contract: ConsumerContractRequest


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


class WithdrawalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["el", "en"]
    withdrawal_requested: StrictBool
    confirmed_name: str = Field(..., min_length=1, max_length=100)
    confirmation_email: str = Field(
        ...,
        min_length=3,
        max_length=255,
        pattern=(
            r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
            r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
            r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
        ),
    )

    @model_validator(mode="after")
    def require_express_request(self) -> WithdrawalRequest:
        if not self.withdrawal_requested:
            raise ValueError("An express withdrawal request is required")
        return self


class WithdrawalResponse(BaseModel):
    withdrawal_id: str
    purchase_id: str
    status: str
    submitted_at: int
    timeliness_assessment_status: str
    acknowledgement_sha256: str
    acknowledgement_url: str


class BillingPurchaseResponse(BaseModel):
    purchase_id: str
    package_key: str
    credits: int
    amount_eur_cents: int
    currency: str
    status: str
    created_at: int
    fulfilled_at: int | None
    contract_confirmation_available: bool
    contract_confirmation_url: str | None
    contract_concluded_at: int | None
    withdrawal_action_available: bool
    withdrawal_status: str | None
    withdrawal_acknowledgement_available: bool
    withdrawal_acknowledgement_url: str | None


@router.get("/catalog")
def get_catalog(
    locale: Literal["el", "en"] = Query(default="el"),
) -> dict[str, Any]:
    """Expose immutable package amounts and video-duration brackets."""
    return public_credit_catalog(locale)


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
            consumer_contract=ConsumerContractAcceptance(
                catalog_version=payload.catalog_version,
                disclosure_id=payload.consumer_contract.disclosure_id,
                disclosure_sha256=payload.consumer_contract.disclosure_sha256,
                locale=payload.consumer_contract.locale,
                policy_version=payload.consumer_contract.policy_version,
                terms_version=payload.consumer_contract.terms_version,
                withdrawal_notice_version=(payload.consumer_contract.withdrawal_notice_version),
                terms_accepted=payload.consumer_contract.terms_accepted,
                immediate_performance_requested=(payload.consumer_contract.immediate_performance_requested),
                withdrawal_consequences_acknowledged=(payload.consumer_contract.withdrawal_consequences_acknowledged),
            ),
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
    if content_length is not None:
        if not content_length or not content_length.isascii() or not content_length.isdecimal():
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if int(content_length) > _MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")

    payload_buffer = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        if len(payload_buffer) + len(chunk) > _MAX_WEBHOOK_BYTES:
            raise HTTPException(status_code=413, detail="Webhook payload is too large")
        payload_buffer.extend(chunk)
    payload = bytes(payload_buffer)
    if not payload:
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


@router.get("/purchases", response_model=list[BillingPurchaseResponse])
def list_billing_purchases(
    current_user: User = Depends(get_current_user),
    record_store: BillingConsumerRecordStore = Depends(
        get_billing_consumer_record_store,
    ),
) -> list[BillingPurchaseResponse]:
    try:
        purchases = record_store.list_purchases(
            user_id=current_user.id,
        )
    except Exception as exc:
        raise _http_billing_error(exc) from exc
    return [
        BillingPurchaseResponse(
            purchase_id=purchase.purchase_id,
            package_key=purchase.package_key,
            credits=purchase.credits,
            amount_eur_cents=purchase.amount_eur_cents,
            currency=purchase.currency,
            status=purchase.status,
            created_at=purchase.created_at,
            fulfilled_at=purchase.fulfilled_at,
            contract_confirmation_available=(purchase.contract_confirmation_available),
            contract_confirmation_url=(
                f"/billing/purchases/{purchase.purchase_id}/contract-confirmation"
                if purchase.contract_confirmation_available
                else None
            ),
            contract_concluded_at=purchase.contract_concluded_at,
            withdrawal_action_available=(purchase.withdrawal_action_available),
            withdrawal_status=purchase.withdrawal_status,
            withdrawal_acknowledgement_available=(purchase.withdrawal_acknowledgement_available),
            withdrawal_acknowledgement_url=(
                f"/billing/purchases/{purchase.purchase_id}/withdrawal-acknowledgement"
                if purchase.withdrawal_acknowledgement_available
                else None
            ),
        )
        for purchase in purchases
    ]


@router.get("/purchases/{purchase_id}/contract-confirmation")
def download_contract_confirmation(
    purchase_id: str = Path(..., min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
    current_user: User = Depends(get_current_user),
    record_store: BillingConsumerRecordStore = Depends(
        get_billing_consumer_record_store,
    ),
) -> Response:
    try:
        confirmation = record_store.get_contract_confirmation(
            user_id=current_user.id,
            purchase_id=purchase_id,
        )
    except Exception as exc:
        raise _http_billing_error(exc) from exc
    return _artifact_response(
        content=confirmation.content_bytes,
        mime_type=confirmation.mime_type,
        filename=confirmation.filename,
        sha256=confirmation.content_sha256,
    )


@router.post(
    "/purchases/{purchase_id}/withdrawals",
    response_model=WithdrawalResponse,
)
def submit_withdrawal(
    payload: WithdrawalRequest,
    purchase_id: str = Path(..., min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
    idempotency_key: str = Header(..., alias="Idempotency-Key", max_length=64),
    current_user: User = Depends(get_current_user),
    record_store: BillingConsumerRecordStore = Depends(
        get_billing_consumer_record_store,
    ),
) -> WithdrawalResponse:
    try:
        result = record_store.submit_withdrawal(
            user_id=current_user.id,
            purchase_id=purchase_id,
            idempotency_key=idempotency_key,
            locale=payload.locale,
            withdrawal_requested=payload.withdrawal_requested,
            confirmed_name=payload.confirmed_name,
            confirmation_email=payload.confirmation_email,
        )
    except Exception as exc:
        raise _http_billing_error(exc) from exc
    return WithdrawalResponse(
        withdrawal_id=result.withdrawal_id,
        purchase_id=result.purchase_id,
        status=result.status,
        submitted_at=result.submitted_at,
        timeliness_assessment_status=(result.timeliness_assessment_status),
        acknowledgement_sha256=result.acknowledgement_sha256,
        acknowledgement_url=(f"/billing/purchases/{result.purchase_id}/withdrawal-acknowledgement"),
    )


@router.get("/purchases/{purchase_id}/withdrawal-acknowledgement")
def download_withdrawal_acknowledgement(
    purchase_id: str = Path(..., min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
    current_user: User = Depends(get_current_user),
    record_store: BillingConsumerRecordStore = Depends(
        get_billing_consumer_record_store,
    ),
) -> Response:
    try:
        withdrawal = record_store.get_withdrawal_acknowledgement(
            user_id=current_user.id,
            purchase_id=purchase_id,
        )
    except Exception as exc:
        raise _http_billing_error(exc) from exc
    return _artifact_response(
        content=withdrawal.acknowledgement_bytes,
        mime_type=withdrawal.acknowledgement_mime_type,
        filename=withdrawal.acknowledgement_filename,
        sha256=withdrawal.acknowledgement_sha256,
    )


def _artifact_response(
    *,
    content: bytes,
    mime_type: str,
    filename: str,
    sha256: str,
) -> Response:
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Cache-Control": "private, no-transform",
            "Content-Disposition": f'attachment; filename="{filename}"',
            "ETag": f'"{sha256}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _http_billing_error(exc: Exception) -> HTTPException:
    if isinstance(exc, BillingDisabledError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, BillingConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, BillingConsumerRecordNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, BillingConsumerRecordConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, BillingValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, BillingConsumerRecordValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, BillingProviderError):
        return HTTPException(status_code=502, detail=str(exc))
    return HTTPException(status_code=500, detail="Billing operation failed")
