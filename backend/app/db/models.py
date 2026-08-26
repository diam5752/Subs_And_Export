"""SQLAlchemy ORM models for the application's relational database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from .base import Base

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")


class DbUser(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(32))
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
    )
    avatar_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    created_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (CheckConstraint("provider IN ('local','google')", name="chk_users_provider"),)


class DbSession(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)


class DbHistoryEvent(Base):
    __tablename__ = "history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)

    __table_args__ = (Index("idx_history_user_ts", "user_id", "ts"),)


class DbJob(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_data: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','cancelling','completed','failed','cancelled')",
            name="chk_jobs_status",
        ),
        Index("idx_jobs_user_created_at", "user_id", "created_at"),
    )


class DbOAuthState(Base):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (Index("idx_oauth_states_provider", "provider"),)


class DbUserPoints(Base):
    __tablename__ = "user_points"

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    paid_balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reversal_debt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("balance >= 0", name="chk_user_points_balance_nonnegative"),
        CheckConstraint("paid_balance >= 0", name="chk_user_points_paid_balance_nonnegative"),
        CheckConstraint("paid_balance <= balance", name="chk_user_points_paid_balance_within_total"),
        CheckConstraint("reversal_debt >= 0", name="chk_user_points_reversal_debt_nonnegative"),
    )


class DbPointTransaction(Base):
    __tablename__ = "point_transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    paid_delta: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reversal_debt_delta: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    reason: Mapped[str] = mapped_column(String(64))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "delta != 0 OR reversal_debt_delta != 0",
            name="chk_point_transactions_effect_nonzero",
        ),
        Index("idx_point_transactions_user_created_at", "user_id", "created_at"),
    )


class DbCreditPromotionCampaign(Base):
    __tablename__ = "credit_promotion_campaigns"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    max_claims: Mapped[int] = mapped_column(Integer)
    credit_amount: Mapped[int] = mapped_column(Integer)
    claimed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "max_claims > 0",
            name="chk_credit_promotion_campaigns_max_claims_positive",
        ),
        CheckConstraint(
            "credit_amount > 0",
            name="chk_credit_promotion_campaigns_credit_amount_positive",
        ),
        CheckConstraint(
            "claimed_count >= 0 AND claimed_count <= max_claims",
            name="chk_credit_promotion_campaigns_claimed_count",
        ),
    )


class DbCreditPromotionClaim(Base):
    __tablename__ = "credit_promotion_claims"

    campaign_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("credit_promotion_campaigns.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    slot_number: Mapped[int] = mapped_column(Integer)
    credit_amount: Mapped[int] = mapped_column(Integer)
    point_transaction_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("point_transactions.id", ondelete="CASCADE"),
        unique=True,
    )
    claimed_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint(
            "slot_number > 0",
            name="chk_credit_promotion_claims_slot_positive",
        ),
        CheckConstraint(
            "credit_amount > 0",
            name="chk_credit_promotion_claims_credit_amount_positive",
        ),
        UniqueConstraint(
            "campaign_id",
            "slot_number",
            name="uq_credit_promotion_claims_campaign_slot",
        ),
        Index("ix_credit_promotion_claims_user_id", "user_id"),
    )


class DbAIModel(Base):
    """
    Stores pricing information for AI models to allow dynamic updates.
    Prices are stored per 1 million tokens.
    """

    __tablename__ = "ai_models"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # e.g. "gpt-4o-mini"
    input_price_per_1m: Mapped[float] = mapped_column(default=0.0)
    output_price_per_1m: Mapped[float] = mapped_column(default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    active: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[int] = mapped_column(Integer)  # Unix timestamp


class DbTokenUsage(Base):
    """
    Audit log for every AI model interaction, tracking exact cost.
    """

    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    model_id: Mapped[str] = mapped_column(ForeignKey("ai_models.id"), index=True)

    prompt_tokens: Mapped[int] = mapped_column(Integer)
    completion_tokens: Mapped[int] = mapped_column(Integer)
    total_tokens: Mapped[int] = mapped_column(Integer)

    cost: Mapped[float] = mapped_column(default=0.0)  # Calculated cost in currency
    timestamp: Mapped[int] = mapped_column(Integer, index=True)

    __table_args__ = (
        Index("idx_token_usage_job_id", "job_id"),
        Index("idx_token_usage_timestamp", "timestamp"),
    )


class DbUsageLedger(Base):
    """
    Usage ledger for external API calls, tied to credits and cost tracking.
    """

    __tablename__ = "usage_ledger"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(32))
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)
    units: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    credits_reserved: Mapped[int] = mapped_column(Integer, default=0)
    paid_credits_reserved: Mapped[int] = mapped_column(Integer, default=0)
    credits_charged: Mapped[int] = mapped_column(Integer, default=0)
    min_credits: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        Index("idx_usage_ledger_user_created", "user_id", "created_at"),
        Index("idx_usage_ledger_action", "action"),
        Index("idx_usage_ledger_status", "status"),
    )


class DbUsageResult(Base):
    """Temporary provider result retained for idempotent replay."""

    __tablename__ = "usage_results"

    ledger_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("usage_ledger.id", ondelete="CASCADE"),
        primary_key=True,
    )
    job_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("jobs.id", ondelete="CASCADE"),
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)


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


class DbCreditPurchaseReversal(Base):
    """Latest provider state for one independent refund or dispute object."""

    __tablename__ = "credit_purchase_reversals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey(
            "credit_purchases.id",
            name="fk_credit_purchase_reversals_purchase_id",
            ondelete="RESTRICT",
        ),
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(32),
        default="stripe",
        server_default="stripe",
    )
    provider_reversal_id: Mapped[str] = mapped_column(String(255))
    provider_event_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    provider_event_created: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(32))
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(64))
    active: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        CheckConstraint(
            "kind IN ('refund','dispute')",
            name="chk_credit_purchase_reversals_kind",
        ),
        CheckConstraint(
            "amount_cents > 0",
            name="chk_credit_purchase_reversals_amount_positive",
        ),
        UniqueConstraint(
            "provider",
            "provider_reversal_id",
            name="uq_credit_purchase_reversals_provider_object",
        ),
        UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_credit_purchase_reversals_provider_event",
        ),
        Index(
            "ix_credit_purchase_reversals_purchase_active",
            "purchase_id",
            "active",
        ),
        Index(
            "ix_credit_purchase_reversals_purchase_event",
            "purchase_id",
            "provider_event_created",
        ),
    )


class DbBillingAdjustmentRecord(Base):
    """Append-only AADE identity for one completed Stripe refund."""

    __tablename__ = "billing_adjustment_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey(
            "credit_purchases.id",
            name="fk_billing_adjustment_records_purchase_id",
            ondelete="RESTRICT",
        ),
    )
    reversal_id: Mapped[str] = mapped_column(
        ForeignKey(
            "credit_purchase_reversals.id",
            name="fk_billing_adjustment_records_reversal_id",
            ondelete="RESTRICT",
        ),
    )
    schema_version: Mapped[int] = mapped_column(Integer)
    provider: Mapped[str] = mapped_column(
        String(32),
        default="aade_etimologio",
        server_default="aade_etimologio",
    )
    document_kind: Mapped[str] = mapped_column(
        String(64),
        default="refund_adjustment",
        server_default="refund_adjustment",
    )
    aade_document_type: Mapped[str] = mapped_column(String(32))
    aade_series: Mapped[str] = mapped_column(String(32))
    aade_aa: Mapped[str] = mapped_column(String(64))
    aade_mark: Mapped[str] = mapped_column(String(160))
    issued_at: Mapped[int] = mapped_column(BigInteger)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    recorded_by_user_id: Mapped[str] = mapped_column(
        String(64),
        comment=("Pseudonymous internal actor ID retained without a user FK; never stores an email."),
    )
    recorded_at: Mapped[int] = mapped_column(BigInteger)
    document_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    financial_retention_until: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint(
            "reversal_id",
            name="uq_billing_adjustment_records_reversal_id",
        ),
        UniqueConstraint(
            "aade_mark",
            name="uq_billing_adjustment_records_aade_mark",
        ),
        UniqueConstraint(
            "aade_series",
            "aade_aa",
            name="uq_billing_adjustment_records_aade_series_aa",
        ),
        CheckConstraint(
            "schema_version = 1",
            name="chk_billing_adjustment_records_schema_version",
        ),
        CheckConstraint(
            "provider = 'aade_etimologio' AND document_kind = 'refund_adjustment'",
            name="chk_billing_adjustment_records_provenance",
        ),
        CheckConstraint(
            "aade_document_type ~ '^[0-9]{1,2}(\\.[0-9]{1,2})?$' "
            "AND btrim(aade_series) <> '' "
            "AND aade_aa ~ '^[0-9]+$' "
            "AND aade_mark ~ '^[1-9][0-9]{0,18}$' "
            "AND aade_mark::NUMERIC <= 9223372036854775807",
            name="chk_billing_adjustment_records_aade_identity",
        ),
        CheckConstraint(
            "amount_cents > 0 AND currency = lower(currency) AND currency ~ '^[a-z]{3}$'",
            name="chk_billing_adjustment_records_amount",
        ),
        CheckConstraint(
            "recorded_by_user_id ~ '^[0-9a-f]{16,64}$'",
            name="chk_billing_adjustment_records_actor",
        ),
        CheckConstraint(
            "issued_at > 0 AND recorded_at >= issued_at "
            "AND created_at = recorded_at "
            "AND financial_retention_until > recorded_at",
            name="chk_billing_adjustment_records_timestamps",
        ),
        CheckConstraint(
            "(jsonb_typeof(document_snapshot) = 'object' "
            "AND document_snapshot ->> 'document_type' = "
            "'gsubs_aade_refund_adjustment_record' "
            "AND document_snapshot ->> 'purchase_id' = purchase_id "
            "AND document_snapshot ->> 'reversal_id' = reversal_id "
            "AND (document_snapshot ->> 'schema_version')::INTEGER = "
            "schema_version "
            "AND document_snapshot #>> '{aade,provider}' = provider "
            "AND document_snapshot #>> '{aade,document_kind}' = "
            "document_kind "
            "AND document_snapshot #>> '{aade,document_type}' = "
            "aade_document_type "
            "AND document_snapshot #>> '{aade,series}' = aade_series "
            "AND document_snapshot #>> '{aade,aa}' = aade_aa "
            "AND document_snapshot #>> '{aade,mark}' = aade_mark "
            "AND (document_snapshot #>> '{aade,issued_at}')::BIGINT = "
            "issued_at "
            "AND (document_snapshot ->> 'amount_cents')::INTEGER = "
            "amount_cents "
            "AND document_snapshot ->> 'currency' = currency "
            "AND (document_snapshot ->> 'recorded_at')::BIGINT = "
            "recorded_at) IS TRUE",
            name="chk_billing_adjustment_records_snapshot",
        ),
        Index(
            "ix_billing_adjustment_records_purchase_id",
            "purchase_id",
        ),
        Index(
            "ix_billing_adjustment_records_retention",
            "financial_retention_until",
        ),
    )


class DbBillingWithdrawalResolution(Base):
    """Append-only customer-visible outcome of a manual withdrawal review."""

    __tablename__ = "billing_withdrawal_resolutions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    withdrawal_id: Mapped[str] = mapped_column(
        ForeignKey(
            "billing_withdrawal_requests.id",
            name="fk_billing_withdrawal_resolutions_withdrawal_id",
            ondelete="CASCADE",
        ),
    )
    purchase_id: Mapped[str] = mapped_column(
        ForeignKey(
            "credit_purchases.id",
            name="fk_billing_withdrawal_resolutions_purchase_id",
            ondelete="RESTRICT",
        ),
    )
    adjustment_id: Mapped[str | None] = mapped_column(
        ForeignKey(
            "billing_adjustment_records.id",
            name="fk_billing_withdrawal_resolutions_adjustment_id",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer)
    locale: Mapped[str] = mapped_column(String(8))
    decision: Mapped[str] = mapped_column(String(64))
    reason_code: Mapped[str] = mapped_column(String(64))
    resolution_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
    resolution_mime_type: Mapped[str] = mapped_column(String(64))
    resolution_filename: Mapped[str] = mapped_column(String(160))
    resolution_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    resolution_sha256: Mapped[str] = mapped_column(String(64))
    resolved_by_user_id: Mapped[str] = mapped_column(
        String(64),
        comment=("Pseudonymous internal actor ID retained without a user FK; never stores an email."),
    )
    resolved_at: Mapped[int] = mapped_column(BigInteger)
    available_at: Mapped[int] = mapped_column(BigInteger)
    financial_retention_until: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint(
            "withdrawal_id",
            name="uq_billing_withdrawal_resolutions_withdrawal_id",
        ),
        UniqueConstraint(
            "adjustment_id",
            name="uq_billing_withdrawal_resolutions_adjustment_id",
        ),
        CheckConstraint(
            "schema_version = 1",
            name="chk_billing_withdrawal_resolutions_schema_version",
        ),
        CheckConstraint(
            "locale IN ('el','en')",
            name="chk_billing_withdrawal_resolutions_locale",
        ),
        CheckConstraint(
            "(decision = 'accepted_refunded' "
            "AND reason_code = 'statutory_right_accepted' "
            "AND adjustment_id IS NOT NULL) "
            "OR (decision = 'rejected' "
            "AND reason_code = 'request_not_eligible' "
            "AND adjustment_id IS NULL)",
            name="chk_billing_withdrawal_resolutions_decision",
        ),
        CheckConstraint(
            "resolution_mime_type = 'application/json; charset=utf-8' "
            "AND resolution_filename = "
            "'gsubs-withdrawal-resolution-' || purchase_id || '.json'",
            name="chk_billing_withdrawal_resolutions_artifact",
        ),
        CheckConstraint(
            "resolution_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(resolution_bytes) > 0 "
            "AND resolution_sha256 = "
            "encode(sha256(resolution_bytes), 'hex')",
            name="chk_billing_withdrawal_resolutions_hash",
        ),
        CheckConstraint(
            "(jsonb_typeof(resolution_snapshot) = 'object' "
            "AND convert_from(resolution_bytes, 'UTF8')::jsonb = "
            "resolution_snapshot "
            "AND resolution_snapshot ->> 'document_type' = "
            "'gsubs_withdrawal_resolution' "
            "AND resolution_snapshot ->> 'withdrawal_id' = withdrawal_id "
            "AND resolution_snapshot ->> 'purchase_id' = purchase_id "
            "AND (resolution_snapshot ->> 'schema_version')::INTEGER = "
            "schema_version "
            "AND resolution_snapshot ->> 'locale' = locale "
            "AND resolution_snapshot ->> 'decision' = decision "
            "AND resolution_snapshot ->> 'reason_code' = reason_code "
            "AND resolution_snapshot ->> 'adjustment_id' "
            "IS NOT DISTINCT FROM adjustment_id "
            "AND (resolution_snapshot ->> 'resolved_at')::BIGINT = "
            "resolved_at) IS TRUE",
            name="chk_billing_withdrawal_resolutions_snapshot",
        ),
        CheckConstraint(
            "resolved_by_user_id ~ '^[0-9a-f]{16,64}$'",
            name="chk_billing_withdrawal_resolutions_actor",
        ),
        CheckConstraint(
            "resolved_at > 0 AND available_at = resolved_at "
            "AND created_at = resolved_at "
            "AND financial_retention_until > resolved_at",
            name="chk_billing_withdrawal_resolutions_timestamps",
        ),
        Index(
            "ix_billing_withdrawal_resolutions_purchase_id",
            "purchase_id",
        ),
        Index(
            "ix_billing_withdrawal_resolutions_retention",
            "financial_retention_until",
        ),
    )


class DbStripeWebhookEvent(Base):
    """Persistent Stripe event receipt used for replay-safe processing."""

    __tablename__ = "stripe_webhook_events"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(128))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)
    processed_at: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (Index("ix_stripe_webhook_events_status_created", "status", "created_at"),)


class DbProviderBudgetWindow(Base):
    """Concurrency-safe aggregate for daily/monthly provider-money caps."""

    __tablename__ = "provider_budget_windows"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    scope: Mapped[str] = mapped_column(String(8))
    period_start: Mapped[int] = mapped_column(Integer)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("scope IN ('day','month')", name="chk_provider_budget_windows_scope"),
        CheckConstraint("reserved_usd >= 0", name="chk_provider_budget_windows_reserved"),
        CheckConstraint("spent_usd >= 0", name="chk_provider_budget_windows_spent"),
    )


class DbProviderBudgetReservation(Base):
    """One cost reservation per idempotent external-provider operation."""

    __tablename__ = "provider_budget_reservations"

    idempotency_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    daily_window_key: Mapped[str] = mapped_column(ForeignKey("provider_budget_windows.key", ondelete="RESTRICT"))
    monthly_window_key: Mapped[str] = mapped_column(ForeignKey("provider_budget_windows.key", ondelete="RESTRICT"))
    estimated_usd: Mapped[float] = mapped_column(Float)
    actual_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("estimated_usd >= 0", name="chk_provider_budget_reservation_estimate"),
        CheckConstraint("actual_usd >= 0", name="chk_provider_budget_reservation_actual"),
        CheckConstraint(
            "status IN ('reserved','finalized','released')",
            name="chk_provider_budget_reservation_status",
        ),
        Index("ix_provider_budget_reservations_status", "status", "created_at"),
    )


class DbRateLimit(Base):
    """Rate limiting state for DB-backed rate limiting (multi-instance safe)."""

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    window_start: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
