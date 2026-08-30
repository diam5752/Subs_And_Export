"""Core purchase, invoice, contract, and withdrawal ORM models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .model_types import JSON_VALUE


class DbCreditPurchase(Base):
    """Immutable package snapshot plus Stripe fulfillment/reversal state."""

    __tablename__ = "credit_purchases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "users.id",
            name="fk_credit_purchases_user_id_users",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
    account_reference_hash: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(32), default="stripe")
    package_key: Mapped[str] = mapped_column(String(32))
    credits: Mapped[int] = mapped_column(Integer)
    amount_eur_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="eur")
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    checkout_session_id: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    checkout_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    integration_identifier: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    fulfilled_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refunded_amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    dispute_active: Mapped[bool] = mapped_column(Boolean, default=False)
    reversed_credits: Mapped[int] = mapped_column(Integer, default=0)
    reversal_debt_credits: Mapped[int] = mapped_column(Integer, default=0)
    reversed_amount_cents: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    payment_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VALUE,
        nullable=True,
    )
    customer_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VALUE,
        nullable=True,
    )
    tax_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_VALUE,
        nullable=True,
    )
    financial_retention_until: Mapped[int] = mapped_column(BigInteger)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("credits > 0", name="chk_credit_purchases_credits_positive"),
        CheckConstraint("amount_eur_cents > 0", name="chk_credit_purchases_amount_positive"),
        CheckConstraint("refunded_amount_cents >= 0", name="chk_credit_purchases_refund_nonnegative"),
        CheckConstraint(
            "reversed_credits >= 0 AND reversed_credits <= credits",
            name="chk_credit_purchases_reversed_credits",
        ),
        CheckConstraint(
            "reversal_debt_credits >= 0 AND reversal_debt_credits <= reversed_credits",
            name="chk_credit_purchases_reversal_debt",
        ),
        CheckConstraint(
            "reversed_amount_cents >= 0 AND reversed_amount_cents <= amount_eur_cents",
            name="chk_credit_purchases_reversed_amount",
        ),
        UniqueConstraint(
            "payment_intent_id",
            name="uq_credit_purchases_payment_intent",
        ),
        Index("ix_credit_purchases_user_created", "user_id", "created_at"),
        Index(
            "ix_credit_purchases_account_reference",
            "account_reference_hash",
        ),
        Index(
            "ix_credit_purchases_retention",
            "financial_retention_until",
        ),
        Index("ix_credit_purchases_status", "status"),
    )


class DbBillingInvoice(Base):
    """Manual AADE document link retained with its pseudonymous actor audit.

    ``recorded_by_user_id`` intentionally has no user foreign key: it is an
    internal pseudonymous identifier (never an email) that remains attached to
    the statutory financial record when an operator account is deleted.
    """

    __tablename__ = "billing_invoices"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey(
            "credit_purchases.id",
            name="fk_billing_invoices_purchase_id",
            ondelete="RESTRICT",
        ),
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        default="aade_etimologio",
        server_default="aade_etimologio",
    )
    document_kind: Mapped[str] = mapped_column(
        String(32),
        default="retail_service_receipt",
        server_default="retail_service_receipt",
    )
    document_status: Mapped[str] = mapped_column(
        String(64),
        default="pending_manual_issue",
        server_default="pending_manual_issue",
    )
    aade_document_type: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    aade_series: Mapped[str | None] = mapped_column(String(32), nullable=True)
    aade_aa: Mapped[str | None] = mapped_column(String(64), nullable=True)
    aade_mark: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )
    issued_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recorded_by_user_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment=("Pseudonymous internal actor ID retained without a user FK; never stores an email."),
    )
    recorded_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    document_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    financial_retention_until: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint(
            "purchase_id",
            name="uq_billing_invoices_purchase_id",
        ),
        UniqueConstraint(
            "aade_mark",
            name="uq_billing_invoices_aade_mark",
        ),
        CheckConstraint(
            """
            (
                document_status IN (
                    'pending_manual_issue',
                    'manual_review_required'
                )
                AND aade_document_type IS NULL
                AND aade_series IS NULL
                AND aade_aa IS NULL
                AND aade_mark IS NULL
                AND issued_at IS NULL
                AND recorded_by_user_id IS NULL
                AND recorded_at IS NULL
            )
            OR (
                document_status IN ('issued','cancelled')
                AND aade_document_type IS NOT NULL
                AND btrim(aade_document_type) <> ''
                AND aade_series IS NOT NULL
                AND btrim(aade_series) <> ''
                AND aade_aa IS NOT NULL
                AND btrim(aade_aa) <> ''
                AND aade_mark IS NOT NULL
                AND btrim(aade_mark) <> ''
                AND issued_at IS NOT NULL
                AND issued_at > 0
                AND recorded_by_user_id IS NOT NULL
                AND btrim(recorded_by_user_id) <> ''
                AND recorded_by_user_id ~ '^[0-9a-f]{16,64}$'
                AND recorded_at IS NOT NULL
                AND recorded_at > 0
                AND financial_retention_until > issued_at
            )
            """,
            name="chk_billing_invoices_issued_identity",
        ),
        CheckConstraint(
            "btrim(provider) <> '' AND btrim(document_kind) <> ''",
            name="chk_billing_invoices_provenance",
        ),
        UniqueConstraint(
            "aade_series",
            "aade_aa",
            name="uq_billing_invoices_aade_series_aa",
        ),
        Index(
            "ix_billing_invoices_purchase_id",
            "purchase_id",
        ),
        Index(
            "ix_billing_invoices_status_created",
            "document_status",
            "created_at",
        ),
        Index(
            "ix_billing_invoices_retention",
            "financial_retention_until",
        ),
    )


class DbBillingContractConfirmation(Base):
    """Append-only durable copy of the concluded consumer contract."""

    __tablename__ = "billing_contract_confirmations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey(
            "credit_purchases.id",
            name="fk_billing_contract_confirmations_purchase_id",
            ondelete="RESTRICT",
        ),
    )
    schema_version: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(String(8))
    contract_concluded_at: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(String(64))
    filename: Mapped[str] = mapped_column(String(160))
    content_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    content_sha256: Mapped[str] = mapped_column(String(64))
    consumer_contract_sha256: Mapped[str] = mapped_column(String(64))
    delivery_channel: Mapped[str] = mapped_column(String(32))
    delivery_status: Mapped[str] = mapped_column(String(64))
    available_at: Mapped[int] = mapped_column(BigInteger)
    financial_retention_until: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint(
            "purchase_id",
            name="uq_billing_contract_confirmations_purchase_id",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="chk_billing_contract_confirmations_schema_version",
        ),
        CheckConstraint(
            "locale IN ('el','en')",
            name="chk_billing_contract_confirmations_locale",
        ),
        CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$' "
            "AND consumer_contract_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(content_bytes) > 0 "
            "AND content_sha256 = encode(sha256(content_bytes), 'hex')",
            name="chk_billing_contract_confirmations_hashes",
        ),
        CheckConstraint(
            "mime_type = 'application/json; charset=utf-8' AND filename = 'gsubs-contract-' || purchase_id || '.json'",
            name="chk_billing_contract_confirmations_artifact",
        ),
        CheckConstraint(
            "(convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'document_type' = 'gsubs_consumer_contract_confirmation' "
            "AND convert_from(content_bytes, 'UTF8')::jsonb #>> "
            "'{purchase,purchase_id}' = purchase_id "
            "AND convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'consumer_contract_sha256' = consumer_contract_sha256 "
            "AND convert_from(content_bytes, 'UTF8')::jsonb #>> "
            "'{consumer_contract,locale}' = locale "
            "AND (convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'schema_version')::INTEGER = schema_version "
            "AND (convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'contract_concluded_at')::BIGINT = contract_concluded_at "
            "AND (convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'available_at')::BIGINT = available_at "
            "AND convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'delivery_channel' = delivery_channel "
            "AND convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'delivery_status' = delivery_status) IS TRUE",
            name="chk_billing_contract_confirmations_identity",
        ),
        CheckConstraint(
            "delivery_channel = 'account_vault' "
            "AND delivery_status IN "
            "('available_pending_external_approval', 'available_approved')",
            name="chk_billing_contract_confirmations_delivery",
        ),
        CheckConstraint(
            "contract_concluded_at > 0 "
            "AND available_at >= contract_concluded_at "
            "AND created_at = available_at "
            "AND financial_retention_until > contract_concluded_at",
            name="chk_billing_contract_confirmations_timestamps",
        ),
        Index(
            "ix_billing_contract_confirmations_purchase_id",
            "purchase_id",
        ),
        Index(
            "ix_billing_contract_confirmations_retention",
            "financial_retention_until",
        ),
    )


class DbBillingWithdrawalRequest(Base):
    """Append-only online withdrawal request pending manual review."""

    __tablename__ = "billing_withdrawal_requests"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey(
            "credit_purchases.id",
            name="fk_billing_withdrawal_requests_purchase_id",
            ondelete="RESTRICT",
        ),
    )
    idempotency_key: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(64))
    request_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    request_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    request_sha256: Mapped[str] = mapped_column(String(64))
    submitted_at: Mapped[int] = mapped_column(BigInteger)
    acknowledgement_mime_type: Mapped[str] = mapped_column(String(64))
    acknowledgement_filename: Mapped[str] = mapped_column(String(160))
    acknowledgement_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    acknowledgement_sha256: Mapped[str] = mapped_column(String(64))
    available_at: Mapped[int] = mapped_column(BigInteger)
    financial_retention_until: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint(
            "purchase_id",
            name="uq_billing_withdrawal_requests_purchase_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_billing_withdrawal_requests_idempotency_key",
        ),
        CheckConstraint(
            "schema_version > 0",
            name="chk_billing_withdrawal_requests_schema_version",
        ),
        CheckConstraint(
            "locale IN ('el','en')",
            name="chk_billing_withdrawal_requests_locale",
        ),
        CheckConstraint(
            "status = 'pending_manual_review'",
            name="chk_billing_withdrawal_requests_status",
        ),
        CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$' "
            "AND acknowledgement_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(request_bytes) > 0 "
            "AND octet_length(acknowledgement_bytes) > 0 "
            "AND request_sha256 = encode(sha256(request_bytes), 'hex') "
            "AND acknowledgement_sha256 = "
            "encode(sha256(acknowledgement_bytes), 'hex')",
            name="chk_billing_withdrawal_requests_hashes",
        ),
        CheckConstraint(
            "acknowledgement_mime_type = "
            "'application/json; charset=utf-8' "
            "AND acknowledgement_filename = "
            "'gsubs-withdrawal-' || purchase_id || '.json'",
            name="chk_billing_withdrawal_requests_artifact",
        ),
        CheckConstraint(
            "(jsonb_typeof(convert_from(request_bytes, 'UTF8')::jsonb) = "
            "'object' AND convert_from(request_bytes, 'UTF8')::jsonb = "
            "request_snapshot) IS TRUE",
            name="chk_billing_withdrawal_requests_snapshot",
        ),
        CheckConstraint(
            "submitted_at > 0 "
            "AND available_at >= submitted_at "
            "AND created_at = available_at "
            "AND financial_retention_until > submitted_at",
            name="chk_billing_withdrawal_requests_timestamps",
        ),
        ForeignKeyConstraint(
            ["purchase_id"],
            ["billing_contract_confirmations.purchase_id"],
            name="fk_billing_withdrawal_requests_confirmation_purchase_id",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_billing_withdrawal_requests_purchase_id",
            "purchase_id",
        ),
        Index(
            "ix_billing_withdrawal_requests_status_submitted",
            "status",
            "submitted_at",
        ),
        Index(
            "ix_billing_withdrawal_requests_retention",
            "financial_retention_until",
        ),
    )
