"""SQLAlchemy ORM models for the application's relational database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
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
    google_sub: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    created_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (
        CheckConstraint("provider IN ('local','google')", name="chk_users_provider"),
    )


class DbDeletedEmail(Base):
    __tablename__ = "deleted_emails"

    email_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    deleted_at: Mapped[int] = mapped_column(Integer)


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

    __table_args__ = (
        Index("idx_history_user_ts", "user_id", "ts"),
    )


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
            "status IN ('pending','processing','completed','failed','cancelled')",
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

    __table_args__ = (
        Index("idx_oauth_states_provider", "provider"),
    )


class DbGcsUploadSession(Base):
    __tablename__ = "gcs_uploads"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    object_name: Mapped[str] = mapped_column(String(1024))
    content_type: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
    used_at: Mapped[int | None] = mapped_column(Integer, nullable=True)

    __table_args__ = (
        Index("idx_gcs_uploads_user_created_at", "user_id", "created_at"),
    )


class DbUserPoints(Base):
    __tablename__ = "user_points"

    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    balance: Mapped[int] = mapped_column(Integer, default=1000, server_default="1000")
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


class DbCreditPurchase(Base):
    """Immutable package snapshot plus Stripe fulfillment/reversal state."""

    __tablename__ = "credit_purchases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
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
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_VALUE)
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
        UniqueConstraint(
            "payment_intent_id",
            name="uq_credit_purchases_payment_intent",
        ),
        Index("ix_credit_purchases_user_created", "user_id", "created_at"),
        Index("ix_credit_purchases_status", "status"),
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

    __table_args__ = (
        Index("ix_stripe_webhook_events_status_created", "status", "created_at"),
    )


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
    daily_window_key: Mapped[str] = mapped_column(
        ForeignKey("provider_budget_windows.key", ondelete="RESTRICT")
    )
    monthly_window_key: Mapped[str] = mapped_column(
        ForeignKey("provider_budget_windows.key", ondelete="RESTRICT")
    )
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
