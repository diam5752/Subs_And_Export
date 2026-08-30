"""Validated request and privacy-minimized response models for billing admin."""

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)

_ALLOWED_SERIES_PUNCTUATION = frozenset("-._/")
_MAX_SIGNED_64_BIT_INTEGER = 9_223_372_036_854_775_807


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
