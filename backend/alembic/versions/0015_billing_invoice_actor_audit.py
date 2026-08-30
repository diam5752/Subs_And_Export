"""Add immutable pseudonymous actor audit to billing invoices.

Revision ID: 0015_billing_invoice_actor_audit
Revises: 0014_consumer_contract_records
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_billing_invoice_actor_audit"
down_revision = "0014_consumer_contract_records"
branch_labels = None
depends_on = None

_PRE_0015_ISSUED_IDENTITY_CHECK = """
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
"""

_ACTOR_AUDIT_ISSUED_IDENTITY_CHECK = """
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
"""


def _lock_billing_invoices() -> None:
    op.get_bind().execute(
        sa.text(
            """
            LOCK TABLE public.billing_invoices
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )


def _assert_upgrade_has_no_unattributed_terminal_records() -> None:
    _lock_billing_invoices()
    terminal_invoice_id = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT id
                FROM public.billing_invoices
                WHERE document_status IN ('issued', 'cancelled')
                LIMIT 1
                """
            )
        )
        .scalar_one_or_none()
    )
    if terminal_invoice_id is not None:
        raise RuntimeError(
            "Cannot add billing invoice actor audit while pre-existing "
            "issued or cancelled invoices lack truthful actor attribution."
        )


def _assert_downgrade_has_no_actor_audit_evidence() -> None:
    _lock_billing_invoices()
    durable_audit_invoice_id = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT id
                FROM public.billing_invoices
                WHERE document_status IN ('issued', 'cancelled')
                   OR recorded_by_user_id IS NOT NULL
                   OR recorded_at IS NOT NULL
                LIMIT 1
                """
            )
        )
        .scalar_one_or_none()
    )
    if durable_audit_invoice_id is not None:
        raise RuntimeError(
            "Cannot downgrade billing invoice actor audit while terminal or actor-audit financial evidence exists."
        )


def _replace_prepare_function_with_actor_audit() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.gsubs_prepare_billing_invoice()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            NEW.financial_retention_until :=
                GREATEST(
                    COALESCE(NEW.financial_retention_until, 0),
                    public.gsubs_financial_retention_deadline(
                        GREATEST(
                            COALESCE(NEW.issued_at, 0),
                            COALESCE(NEW.recorded_at, 0),
                            NEW.created_at,
                            NEW.updated_at
                        )
                    )
                );
            RETURN NEW;
        END
        $function$
        """
    )


def _restore_prepare_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.gsubs_prepare_billing_invoice()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            NEW.financial_retention_until :=
                GREATEST(
                    COALESCE(NEW.financial_retention_until, 0),
                    public.gsubs_financial_retention_deadline(
                        GREATEST(
                            COALESCE(NEW.issued_at, 0),
                            NEW.created_at,
                            NEW.updated_at
                        )
                    )
                );
            RETURN NEW;
        END
        $function$
        """
    )


def _replace_immutability_function_with_actor_audit() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.gsubs_enforce_billing_invoice_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF OLD.purchase_id IS DISTINCT FROM NEW.purchase_id THEN
                RAISE EXCEPTION 'billing_invoices.purchase_id is immutable';
            END IF;
            IF OLD.provider IS DISTINCT FROM NEW.provider THEN
                RAISE EXCEPTION 'billing_invoices.provider is immutable';
            END IF;
            IF OLD.document_kind IS DISTINCT FROM NEW.document_kind THEN
                RAISE EXCEPTION 'billing_invoices.document_kind is immutable';
            END IF;
            IF OLD.document_snapshot IS DISTINCT FROM NEW.document_snapshot THEN
                RAISE EXCEPTION 'billing_invoices.document_snapshot is immutable';
            END IF;
            IF OLD.document_status IS DISTINCT FROM NEW.document_status
               AND NOT (
                   OLD.document_status IN (
                       'pending_manual_issue',
                       'manual_review_required'
                   )
                   AND NEW.document_status IN ('issued', 'cancelled')
               ) THEN
                RAISE EXCEPTION 'billing_invoices.document_status transition is invalid';
            END IF;
            IF OLD.aade_document_type IS NOT NULL
               AND OLD.aade_document_type IS DISTINCT FROM NEW.aade_document_type THEN
                RAISE EXCEPTION 'billing_invoices.aade_document_type is immutable';
            END IF;
            IF OLD.aade_series IS NOT NULL
               AND OLD.aade_series IS DISTINCT FROM NEW.aade_series THEN
                RAISE EXCEPTION 'billing_invoices.aade_series is immutable';
            END IF;
            IF OLD.aade_aa IS NOT NULL
               AND OLD.aade_aa IS DISTINCT FROM NEW.aade_aa THEN
                RAISE EXCEPTION 'billing_invoices.aade_aa is immutable';
            END IF;
            IF OLD.aade_mark IS NOT NULL
               AND OLD.aade_mark IS DISTINCT FROM NEW.aade_mark THEN
                RAISE EXCEPTION 'billing_invoices.aade_mark is immutable';
            END IF;
            IF OLD.issued_at IS NOT NULL
               AND OLD.issued_at IS DISTINCT FROM NEW.issued_at THEN
                RAISE EXCEPTION 'billing_invoices.issued_at is immutable';
            END IF;
            IF OLD.recorded_by_user_id IS NOT NULL
               AND OLD.recorded_by_user_id IS DISTINCT FROM NEW.recorded_by_user_id THEN
                RAISE EXCEPTION 'billing_invoices.recorded_by_user_id is immutable';
            END IF;
            IF OLD.recorded_at IS NOT NULL
               AND OLD.recorded_at IS DISTINCT FROM NEW.recorded_at THEN
                RAISE EXCEPTION 'billing_invoices.recorded_at is immutable';
            END IF;
            IF OLD.financial_retention_until IS NOT NULL
               AND (
                   NEW.financial_retention_until IS NULL
                   OR NEW.financial_retention_until < OLD.financial_retention_until
               ) THEN
                RAISE EXCEPTION 'billing_invoices.financial_retention_until cannot be shortened';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )


def _restore_immutability_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.gsubs_enforce_billing_invoice_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF OLD.purchase_id IS DISTINCT FROM NEW.purchase_id THEN
                RAISE EXCEPTION 'billing_invoices.purchase_id is immutable';
            END IF;
            IF OLD.provider IS DISTINCT FROM NEW.provider THEN
                RAISE EXCEPTION 'billing_invoices.provider is immutable';
            END IF;
            IF OLD.document_kind IS DISTINCT FROM NEW.document_kind THEN
                RAISE EXCEPTION 'billing_invoices.document_kind is immutable';
            END IF;
            IF OLD.document_snapshot IS DISTINCT FROM NEW.document_snapshot THEN
                RAISE EXCEPTION 'billing_invoices.document_snapshot is immutable';
            END IF;
            IF OLD.document_status IS DISTINCT FROM NEW.document_status
               AND NOT (
                   OLD.document_status IN (
                       'pending_manual_issue',
                       'manual_review_required'
                   )
                   AND NEW.document_status IN ('issued', 'cancelled')
               ) THEN
                RAISE EXCEPTION 'billing_invoices.document_status transition is invalid';
            END IF;
            IF OLD.aade_document_type IS NOT NULL
               AND OLD.aade_document_type IS DISTINCT FROM NEW.aade_document_type THEN
                RAISE EXCEPTION 'billing_invoices.aade_document_type is immutable';
            END IF;
            IF OLD.aade_series IS NOT NULL
               AND OLD.aade_series IS DISTINCT FROM NEW.aade_series THEN
                RAISE EXCEPTION 'billing_invoices.aade_series is immutable';
            END IF;
            IF OLD.aade_aa IS NOT NULL
               AND OLD.aade_aa IS DISTINCT FROM NEW.aade_aa THEN
                RAISE EXCEPTION 'billing_invoices.aade_aa is immutable';
            END IF;
            IF OLD.aade_mark IS NOT NULL
               AND OLD.aade_mark IS DISTINCT FROM NEW.aade_mark THEN
                RAISE EXCEPTION 'billing_invoices.aade_mark is immutable';
            END IF;
            IF OLD.issued_at IS NOT NULL
               AND OLD.issued_at IS DISTINCT FROM NEW.issued_at THEN
                RAISE EXCEPTION 'billing_invoices.issued_at is immutable';
            END IF;
            IF OLD.financial_retention_until IS NOT NULL
               AND (
                   NEW.financial_retention_until IS NULL
                   OR NEW.financial_retention_until < OLD.financial_retention_until
               ) THEN
                RAISE EXCEPTION 'billing_invoices.financial_retention_until cannot be shortened';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )


def upgrade() -> None:
    _assert_upgrade_has_no_unattributed_terminal_records()
    op.add_column(
        "billing_invoices",
        sa.Column(
            "recorded_by_user_id",
            sa.String(length=64),
            nullable=True,
            comment=("Pseudonymous internal actor ID retained without a user FK; never stores an email."),
        ),
    )
    op.add_column(
        "billing_invoices",
        sa.Column("recorded_at", sa.BigInteger(), nullable=True),
    )

    _replace_prepare_function_with_actor_audit()
    _replace_immutability_function_with_actor_audit()
    op.drop_constraint(
        "chk_billing_invoices_issued_identity",
        "billing_invoices",
        type_="check",
    )
    op.create_check_constraint(
        "chk_billing_invoices_issued_identity",
        "billing_invoices",
        _ACTOR_AUDIT_ISSUED_IDENTITY_CHECK,
    )


def downgrade() -> None:
    _assert_downgrade_has_no_actor_audit_evidence()
    _restore_prepare_function()
    _restore_immutability_function()
    op.drop_constraint(
        "chk_billing_invoices_issued_identity",
        "billing_invoices",
        type_="check",
    )
    op.create_check_constraint(
        "chk_billing_invoices_issued_identity",
        "billing_invoices",
        _PRE_0015_ISSUED_IDENTITY_CHECK,
    )
    op.drop_column("billing_invoices", "recorded_at")
    op.drop_column("billing_invoices", "recorded_by_user_id")
