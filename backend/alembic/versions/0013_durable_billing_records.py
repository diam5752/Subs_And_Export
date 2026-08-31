"""Add durable payment, manual AADE invoice, and reversal records.

Revision ID: 0013_durable_billing_records
Revises: 0012_google_avatar_url
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_durable_billing_records"
down_revision = "0012_google_avatar_url"
branch_labels = None
depends_on = None


from app.db.migration_0013_durable_billing_data import (
    _backfill_legacy_financial_records,
    _ensure_downgrade_is_safe,
)
from app.db.migration_0013_durable_billing_schema import (
    _create_billing_invoice_triggers,
    _create_credit_purchase_reversal_triggers,
    _create_credit_purchase_triggers,
    _create_durable_billing_mutation_guards,
    _create_retention_function,
    _drop_credit_purchase_user_foreign_key,
)


def upgrade() -> None:
    json_value = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    _create_retention_function()

    op.add_column(
        "credit_purchases",
        sa.Column("account_reference_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "credit_purchases",
        sa.Column(
            "reversed_amount_cents",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "credit_purchases",
        sa.Column("payment_snapshot", json_value, nullable=True),
    )
    op.add_column(
        "credit_purchases",
        sa.Column("customer_snapshot", json_value, nullable=True),
    )
    op.add_column(
        "credit_purchases",
        sa.Column("tax_snapshot", json_value, nullable=True),
    )
    op.add_column(
        "credit_purchases",
        sa.Column("financial_retention_until", sa.BigInteger(), nullable=True),
    )
    op.execute(
        """
        UPDATE public.credit_purchases
        SET account_reference_hash =
            md5(
                'gsubs-financial-account'
                || chr(58)
                || 'v1'
                || chr(58)
                || user_id
            )
            || md5(
                user_id
                || chr(58)
                || 'gsubs-financial-account'
                || chr(58)
                || 'v1'
            )
        WHERE account_reference_hash IS NULL
          AND user_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE public.credit_purchases
        SET financial_retention_until =
            GREATEST(created_at, updated_at, 1) + 86400
        WHERE financial_retention_until IS NULL
        """
    )
    op.alter_column(
        "credit_purchases",
        "financial_retention_until",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
    op.create_check_constraint(
        "chk_credit_purchases_reversed_amount",
        "credit_purchases",
        "reversed_amount_cents >= 0 AND reversed_amount_cents <= amount_eur_cents",
    )
    op.create_index(
        "ix_credit_purchases_account_reference",
        "credit_purchases",
        ["account_reference_hash"],
    )
    op.create_index(
        "ix_credit_purchases_retention",
        "credit_purchases",
        ["financial_retention_until"],
    )

    _drop_credit_purchase_user_foreign_key()
    op.alter_column(
        "credit_purchases",
        "user_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_credit_purchases_user_id_users",
        "credit_purchases",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    _create_credit_purchase_triggers()

    op.create_table(
        "billing_invoices",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("purchase_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="aade_etimologio",
        ),
        sa.Column(
            "document_kind",
            sa.String(length=32),
            nullable=False,
            server_default="retail_service_receipt",
        ),
        sa.Column(
            "document_status",
            sa.String(length=64),
            nullable=False,
            server_default="pending_manual_issue",
        ),
        sa.Column("aade_document_type", sa.String(length=32), nullable=True),
        sa.Column("aade_series", sa.String(length=32), nullable=True),
        sa.Column("aade_aa", sa.String(length=64), nullable=True),
        sa.Column("aade_mark", sa.String(length=160), nullable=True),
        sa.Column("issued_at", sa.BigInteger(), nullable=True),
        sa.Column("document_snapshot", json_value, nullable=False),
        sa.Column("financial_retention_until", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
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
                AND issued_at > 0
                AND financial_retention_until > issued_at
            )
            """,
            name="chk_billing_invoices_issued_identity",
        ),
        sa.CheckConstraint(
            "btrim(provider) <> '' AND btrim(document_kind) <> ''",
            name="chk_billing_invoices_provenance",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["credit_purchases.id"],
            name="fk_billing_invoices_purchase_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_id",
            name="uq_billing_invoices_purchase_id",
        ),
        sa.UniqueConstraint(
            "aade_mark",
            name="uq_billing_invoices_aade_mark",
        ),
        sa.UniqueConstraint(
            "aade_series",
            "aade_aa",
            name="uq_billing_invoices_aade_series_aa",
        ),
    )
    op.create_index(
        "ix_billing_invoices_purchase_id",
        "billing_invoices",
        ["purchase_id"],
    )
    op.create_index(
        "ix_billing_invoices_status_created",
        "billing_invoices",
        ["document_status", "created_at"],
    )
    op.create_index(
        "ix_billing_invoices_retention",
        "billing_invoices",
        ["financial_retention_until"],
    )
    _create_billing_invoice_triggers()

    op.create_table(
        "credit_purchase_reversals",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("purchase_id", sa.String(length=32), nullable=False),
        sa.Column(
            "provider",
            sa.String(length=32),
            nullable=False,
            server_default="stripe",
        ),
        sa.Column("provider_reversal_id", sa.String(length=255), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=True),
        sa.Column("provider_event_created", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('refund','dispute')",
            name="chk_credit_purchase_reversals_kind",
        ),
        sa.CheckConstraint(
            "amount_cents > 0",
            name="chk_credit_purchase_reversals_amount_positive",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["credit_purchases.id"],
            name="fk_credit_purchase_reversals_purchase_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_reversal_id",
            name="uq_credit_purchase_reversals_provider_object",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_event_id",
            name="uq_credit_purchase_reversals_provider_event",
        ),
    )
    op.create_index(
        "ix_credit_purchase_reversals_purchase_id",
        "credit_purchase_reversals",
        ["purchase_id"],
    )
    op.create_index(
        "ix_credit_purchase_reversals_purchase_active",
        "credit_purchase_reversals",
        ["purchase_id", "active"],
    )
    op.create_index(
        "ix_credit_purchase_reversals_purchase_event",
        "credit_purchase_reversals",
        ["purchase_id", "provider_event_created"],
    )
    _create_credit_purchase_reversal_triggers()
    _backfill_legacy_financial_records()
    _create_durable_billing_mutation_guards()


def downgrade() -> None:
    _ensure_downgrade_is_safe()

    op.execute("DROP TRIGGER trg_credit_purchase_reversals_guard_delete ON public.credit_purchase_reversals")
    op.execute("DROP TRIGGER trg_billing_invoices_guard_delete ON public.billing_invoices")
    op.execute("DROP TRIGGER trg_credit_purchases_guard_delete ON public.credit_purchases")
    op.execute("DROP FUNCTION public.gsubs_guard_durable_billing_delete()")

    op.execute("DROP TRIGGER trg_credit_purchase_reversals_reject_truncate ON public.credit_purchase_reversals")
    op.execute("DROP TRIGGER trg_billing_invoices_reject_truncate ON public.billing_invoices")
    op.execute("DROP TRIGGER trg_credit_purchases_reject_truncate ON public.credit_purchases")
    op.execute("DROP FUNCTION public.gsubs_reject_durable_billing_truncate()")

    op.execute("DROP TRIGGER trg_credit_purchase_reversals_enforce_timestamps ON public.credit_purchase_reversals")
    op.execute("DROP FUNCTION public.gsubs_enforce_credit_purchase_reversal_timestamps()")

    op.drop_index(
        "ix_credit_purchase_reversals_purchase_event",
        table_name="credit_purchase_reversals",
    )
    op.drop_index(
        "ix_credit_purchase_reversals_purchase_active",
        table_name="credit_purchase_reversals",
    )
    op.drop_index(
        "ix_credit_purchase_reversals_purchase_id",
        table_name="credit_purchase_reversals",
    )
    op.drop_table("credit_purchase_reversals")

    op.execute("DROP TRIGGER trg_billing_invoices_enforce_immutability ON public.billing_invoices")
    op.execute("DROP FUNCTION public.gsubs_enforce_billing_invoice_immutability()")
    op.execute("DROP TRIGGER trg_billing_invoices_prepare ON public.billing_invoices")
    op.execute("DROP FUNCTION public.gsubs_prepare_billing_invoice()")
    op.drop_index(
        "ix_billing_invoices_retention",
        table_name="billing_invoices",
    )
    op.drop_index(
        "ix_billing_invoices_status_created",
        table_name="billing_invoices",
    )
    op.drop_index(
        "ix_billing_invoices_purchase_id",
        table_name="billing_invoices",
    )
    op.drop_table("billing_invoices")

    op.execute("DROP TRIGGER trg_credit_purchases_enforce_immutability ON public.credit_purchases")
    op.execute("DROP FUNCTION public.gsubs_enforce_credit_purchase_immutability()")
    op.execute("DROP TRIGGER trg_credit_purchases_prepare_financial_record ON public.credit_purchases")
    op.execute("DROP FUNCTION public.gsubs_prepare_credit_purchase_financial_record()")

    op.drop_constraint(
        "fk_credit_purchases_user_id_users",
        "credit_purchases",
        type_="foreignkey",
    )
    op.alter_column(
        "credit_purchases",
        "user_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_foreign_key(
        "credit_purchases_user_id_fkey",
        "credit_purchases",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_index(
        "ix_credit_purchases_retention",
        table_name="credit_purchases",
    )
    op.drop_index(
        "ix_credit_purchases_account_reference",
        table_name="credit_purchases",
    )
    op.drop_constraint(
        "chk_credit_purchases_reversed_amount",
        "credit_purchases",
        type_="check",
    )
    op.drop_column("credit_purchases", "financial_retention_until")
    op.drop_column("credit_purchases", "tax_snapshot")
    op.drop_column("credit_purchases", "customer_snapshot")
    op.drop_column("credit_purchases", "payment_snapshot")
    op.drop_column("credit_purchases", "reversed_amount_cents")
    op.drop_column("credit_purchases", "account_reference_hash")
    op.execute("DROP FUNCTION public.gsubs_financial_retention_deadline(BIGINT)")
