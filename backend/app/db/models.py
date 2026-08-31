"""SQLAlchemy ORM models for the application's relational database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base
from .model_types import JSON_VALUE as JSON_VALUE


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

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
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


from .models_billing import DbBillingContractConfirmation as DbBillingContractConfirmation
from .models_billing import DbBillingInvoice as DbBillingInvoice
from .models_billing import DbBillingWithdrawalRequest as DbBillingWithdrawalRequest
from .models_billing import DbCreditPurchase as DbCreditPurchase
from .models_billing_audit import DbBillingAdjustmentRecord as DbBillingAdjustmentRecord
from .models_billing_audit import DbBillingWithdrawalResolution as DbBillingWithdrawalResolution
from .models_billing_audit import DbCreditPurchaseReversal as DbCreditPurchaseReversal
from .models_billing_audit import DbStripeWebhookEvent as DbStripeWebhookEvent


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


class DbProductFeedback(Base):
    """Durable product inbox row and retryable email-outbox state."""

    __tablename__ = "product_feedback"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    category: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="new", server_default="new")
    message: Mapped[str] = mapped_column(Text)
    source_path: Mapped[str] = mapped_column(String(512))
    page_title: Mapped[str] = mapped_column(String(255))
    submitter_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    submitter_key_hash: Mapped[str] = mapped_column(String(64))
    message_hash: Mapped[str] = mapped_column(String(64))
    dedupe_day: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(BigInteger)
    notification_status: Mapped[str] = mapped_column(
        String(16),
        default="pending",
        server_default="pending",
    )
    notification_attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default="0",
    )
    notification_next_attempt_at: Mapped[int] = mapped_column(BigInteger)
    notification_sent_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    notification_last_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('idea','bug','complaint','chat')",
            name="chk_product_feedback_category",
        ),
        CheckConstraint(
            "status IN ('new','reviewed','closed')",
            name="chk_product_feedback_status",
        ),
        CheckConstraint(
            "char_length(message) BETWEEN 10 AND 2000",
            name="chk_product_feedback_message_length",
        ),
        CheckConstraint(
            "notification_status IN ('pending','sending','sent')",
            name="chk_product_feedback_notification_status",
        ),
        CheckConstraint(
            "notification_attempts >= 0",
            name="chk_product_feedback_notification_attempts",
        ),
        UniqueConstraint(
            "submitter_key_hash",
            "message_hash",
            "dedupe_day",
            name="uq_product_feedback_daily_duplicate",
        ),
        Index(
            "ix_product_feedback_status_created",
            "status",
            "created_at",
        ),
        Index(
            "ix_product_feedback_notification_queue",
            "notification_status",
            "notification_next_attempt_at",
            "created_at",
        ),
    )


class DbRateLimit(Base):
    """Rate limiting state for DB-backed rate limiting (multi-instance safe)."""

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    window_start: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
