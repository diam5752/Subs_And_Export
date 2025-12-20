"""SQLAlchemy ORM models for the application's relational database."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text
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
    updated_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("balance >= 0", name="chk_user_points_balance_nonnegative"),
    )


class DbPointTransaction(Base):
    __tablename__ = "point_transactions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    delta: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(64))
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSON_VALUE, nullable=True)
    created_at: Mapped[int] = mapped_column(Integer)

    __table_args__ = (
        CheckConstraint("delta != 0", name="chk_point_transactions_delta_nonzero"),
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


class DbRateLimit(Base):
    """Rate limiting state for DB-backed rate limiting (multi-instance safe)."""

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    window_start: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[int] = mapped_column(Integer, index=True)
