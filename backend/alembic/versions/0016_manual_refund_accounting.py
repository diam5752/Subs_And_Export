"""Add append-only manual refund accounting and withdrawal resolutions.

Revision ID: 0016_manual_refund_accounting
Revises: 0015_billing_invoice_actor_audit
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_manual_refund_accounting"
down_revision = "0015_billing_invoice_actor_audit"
branch_labels = None
depends_on = None


from app.db.migration_0016_manual_refund_helpers import (
    _assert_downgrade_safe,
    _create_append_only_triggers,
    _create_integrity_triggers,
    _replace_append_only_function,
    _restore_append_only_function,
)


def upgrade() -> None:
    op.create_table(
        "billing_adjustment_records",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("purchase_id", sa.String(length=32), nullable=False),
        sa.Column("reversal_id", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=32),
            server_default="aade_etimologio",
            nullable=False,
        ),
        sa.Column(
            "document_kind",
            sa.String(length=64),
            server_default="refund_adjustment",
            nullable=False,
        ),
        sa.Column("aade_document_type", sa.String(length=32), nullable=False),
        sa.Column("aade_series", sa.String(length=32), nullable=False),
        sa.Column("aade_aa", sa.String(length=64), nullable=False),
        sa.Column("aade_mark", sa.String(length=160), nullable=False),
        sa.Column("issued_at", sa.BigInteger(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "recorded_by_user_id",
            sa.String(length=64),
            nullable=False,
            comment=("Pseudonymous internal actor ID retained without a user FK; never stores an email."),
        ),
        sa.Column("recorded_at", sa.BigInteger(), nullable=False),
        sa.Column(
            "document_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "financial_retention_until",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 1",
            name="chk_billing_adjustment_records_schema_version",
        ),
        sa.CheckConstraint(
            "provider = 'aade_etimologio' AND document_kind = 'refund_adjustment'",
            name="chk_billing_adjustment_records_provenance",
        ),
        sa.CheckConstraint(
            "aade_document_type ~ '^[0-9]{1,2}(\\.[0-9]{1,2})?$' "
            "AND btrim(aade_series) <> '' "
            "AND aade_aa ~ '^[0-9]+$' "
            "AND aade_mark ~ '^[1-9][0-9]{0,18}$' "
            "AND aade_mark::NUMERIC <= 9223372036854775807",
            name="chk_billing_adjustment_records_aade_identity",
        ),
        sa.CheckConstraint(
            "amount_cents > 0 AND currency = lower(currency) AND currency ~ '^[a-z]{3}$'",
            name="chk_billing_adjustment_records_amount",
        ),
        sa.CheckConstraint(
            "recorded_by_user_id ~ '^[0-9a-f]{16,64}$'",
            name="chk_billing_adjustment_records_actor",
        ),
        sa.CheckConstraint(
            "issued_at > 0 AND recorded_at >= issued_at "
            "AND created_at = recorded_at "
            "AND financial_retention_until > recorded_at",
            name="chk_billing_adjustment_records_timestamps",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["credit_purchases.id"],
            name="fk_billing_adjustment_records_purchase_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_id"],
            ["credit_purchase_reversals.id"],
            name="fk_billing_adjustment_records_reversal_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reversal_id",
            name="uq_billing_adjustment_records_reversal_id",
        ),
        sa.UniqueConstraint(
            "aade_mark",
            name="uq_billing_adjustment_records_aade_mark",
        ),
        sa.UniqueConstraint(
            "aade_series",
            "aade_aa",
            name="uq_billing_adjustment_records_aade_series_aa",
        ),
    )
    op.create_index(
        "ix_billing_adjustment_records_purchase_id",
        "billing_adjustment_records",
        ["purchase_id"],
    )
    op.create_index(
        "ix_billing_adjustment_records_retention",
        "billing_adjustment_records",
        ["financial_retention_until"],
    )

    op.create_table(
        "billing_withdrawal_resolutions",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("withdrawal_id", sa.String(length=32), nullable=False),
        sa.Column("purchase_id", sa.String(length=32), nullable=False),
        sa.Column(
            "adjustment_id",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("decision", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column(
            "resolution_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "resolution_mime_type",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "resolution_filename",
            sa.String(length=160),
            nullable=False,
        ),
        sa.Column("resolution_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("resolution_sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "resolved_by_user_id",
            sa.String(length=64),
            nullable=False,
            comment=("Pseudonymous internal actor ID retained without a user FK; never stores an email."),
        ),
        sa.Column("resolved_at", sa.BigInteger(), nullable=False),
        sa.Column("available_at", sa.BigInteger(), nullable=False),
        sa.Column(
            "financial_retention_until",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "schema_version = 1",
            name="chk_billing_withdrawal_resolutions_schema_version",
        ),
        sa.CheckConstraint(
            "locale IN ('el','en')",
            name="chk_billing_withdrawal_resolutions_locale",
        ),
        sa.CheckConstraint(
            "(decision = 'accepted_refunded' "
            "AND reason_code = 'statutory_right_accepted' "
            "AND adjustment_id IS NOT NULL) "
            "OR (decision = 'rejected' "
            "AND reason_code = 'request_not_eligible' "
            "AND adjustment_id IS NULL)",
            name="chk_billing_withdrawal_resolutions_decision",
        ),
        sa.CheckConstraint(
            "resolution_mime_type = 'application/json; charset=utf-8' "
            "AND resolution_filename = "
            "'gsubs-withdrawal-resolution-' || purchase_id || '.json'",
            name="chk_billing_withdrawal_resolutions_artifact",
        ),
        sa.CheckConstraint(
            "resolution_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(resolution_bytes) > 0 "
            "AND resolution_sha256 = "
            "encode(sha256(resolution_bytes), 'hex')",
            name="chk_billing_withdrawal_resolutions_hash",
        ),
        sa.CheckConstraint(
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
        sa.CheckConstraint(
            "resolved_by_user_id ~ '^[0-9a-f]{16,64}$'",
            name="chk_billing_withdrawal_resolutions_actor",
        ),
        sa.CheckConstraint(
            "resolved_at > 0 AND available_at = resolved_at "
            "AND created_at = resolved_at "
            "AND financial_retention_until > resolved_at",
            name="chk_billing_withdrawal_resolutions_timestamps",
        ),
        sa.ForeignKeyConstraint(
            ["withdrawal_id"],
            ["billing_withdrawal_requests.id"],
            name="fk_billing_withdrawal_resolutions_withdrawal_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["credit_purchases.id"],
            name="fk_billing_withdrawal_resolutions_purchase_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["adjustment_id"],
            ["billing_adjustment_records.id"],
            name="fk_billing_withdrawal_resolutions_adjustment_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "withdrawal_id",
            name="uq_billing_withdrawal_resolutions_withdrawal_id",
        ),
        sa.UniqueConstraint(
            "adjustment_id",
            name="uq_billing_withdrawal_resolutions_adjustment_id",
        ),
    )
    op.create_index(
        "ix_billing_withdrawal_resolutions_purchase_id",
        "billing_withdrawal_resolutions",
        ["purchase_id"],
    )
    op.create_index(
        "ix_billing_withdrawal_resolutions_retention",
        "billing_withdrawal_resolutions",
        ["financial_retention_until"],
    )

    _replace_append_only_function()
    _create_append_only_triggers("billing_adjustment_records")
    _create_append_only_triggers("billing_withdrawal_resolutions")
    _create_integrity_triggers()


def downgrade() -> None:
    _assert_downgrade_safe()
    op.execute("DROP TRIGGER trg_billing_withdrawal_resolutions_prepare ON public.billing_withdrawal_resolutions")
    op.execute("DROP FUNCTION public.gsubs_prepare_withdrawal_resolution()")
    op.execute("DROP TRIGGER trg_billing_adjustment_records_prepare ON public.billing_adjustment_records")
    op.execute("DROP FUNCTION public.gsubs_prepare_billing_adjustment_record()")
    op.execute(
        "DROP TRIGGER trg_billing_withdrawal_resolutions_reject_truncate ON public.billing_withdrawal_resolutions"
    )
    op.execute("DROP TRIGGER trg_billing_withdrawal_resolutions_append_only ON public.billing_withdrawal_resolutions")
    op.execute("DROP TRIGGER trg_billing_adjustment_records_reject_truncate ON public.billing_adjustment_records")
    op.execute("DROP TRIGGER trg_billing_adjustment_records_append_only ON public.billing_adjustment_records")
    _restore_append_only_function()

    op.drop_index(
        "ix_billing_withdrawal_resolutions_retention",
        table_name="billing_withdrawal_resolutions",
    )
    op.drop_index(
        "ix_billing_withdrawal_resolutions_purchase_id",
        table_name="billing_withdrawal_resolutions",
    )
    op.drop_table("billing_withdrawal_resolutions")
    op.drop_index(
        "ix_billing_adjustment_records_retention",
        table_name="billing_adjustment_records",
    )
    op.drop_index(
        "ix_billing_adjustment_records_purchase_id",
        table_name="billing_adjustment_records",
    )
    op.drop_table("billing_adjustment_records")
