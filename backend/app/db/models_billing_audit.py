"""Refund, withdrawal-resolution, and Stripe receipt ORM models."""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
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
