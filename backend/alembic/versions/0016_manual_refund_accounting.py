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


def _create_append_only_triggers(table_name: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table_name}_append_only
        BEFORE UPDATE OR DELETE ON public.{table_name}
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_reject_append_only_billing_mutation()
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_{table_name}_reject_truncate
        BEFORE TRUNCATE ON public.{table_name}
        FOR EACH STATEMENT
        EXECUTE FUNCTION public.gsubs_reject_append_only_billing_mutation()
        """
    )


def _assert_downgrade_safe() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            LOCK TABLE
                public.billing_withdrawal_requests,
                public.billing_contract_confirmations,
                public.billing_withdrawal_resolutions,
                public.billing_adjustment_records
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    durable_record_exists = bool(
        bind.execute(
            sa.text(
                """
                SELECT
                    EXISTS (
                        SELECT 1
                        FROM public.billing_withdrawal_resolutions
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM public.billing_adjustment_records
                    )
                """
            )
        ).scalar_one()
    )
    if durable_record_exists:
        raise RuntimeError(
            "Cannot downgrade manual refund accounting while durable "
            "adjustment or withdrawal-resolution evidence exists."
        )


def _replace_append_only_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            public.gsubs_reject_append_only_billing_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            retention_cutoff BIGINT;
            server_now BIGINT;
            effective_cutoff BIGINT;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END IF;
            retention_cutoff := NULLIF(
                current_setting(
                    'gsubs.billing_retention_cutoff',
                    TRUE
                ),
                ''
            )::BIGINT;
            server_now := FLOOR(
                EXTRACT(EPOCH FROM clock_timestamp())
            )::BIGINT;
            IF retention_cutoff IS NOT NULL
               AND retention_cutoff > server_now + 5 THEN
                RAISE EXCEPTION 'retention cutoff is in the future';
            END IF;
            effective_cutoff := LEAST(retention_cutoff, server_now);
            IF TG_OP = 'DELETE'
               AND TG_TABLE_NAME IN (
                   'billing_contract_confirmations',
                   'billing_adjustment_records',
                   'billing_withdrawal_resolutions'
               )
               AND retention_cutoff IS NOT NULL
               AND OLD.financial_retention_until <= effective_cutoff THEN
                RETURN OLD;
            END IF;
            IF TG_OP = 'DELETE'
               AND TG_TABLE_NAME = 'billing_withdrawal_requests'
               AND retention_cutoff IS NOT NULL
               AND OLD.financial_retention_until <= effective_cutoff
               AND EXISTS (
                    SELECT 1
                    FROM public.billing_withdrawal_resolutions
                    WHERE withdrawal_id = OLD.id
                      AND financial_retention_until <= effective_cutoff
               ) THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END
        $function$
        """
    )


def _restore_append_only_function() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION
            public.gsubs_reject_append_only_billing_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            retention_cutoff BIGINT;
            server_now BIGINT;
            effective_cutoff BIGINT;
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
            END IF;
            retention_cutoff := NULLIF(
                current_setting(
                    'gsubs.billing_retention_cutoff',
                    TRUE
                ),
                ''
            )::BIGINT;
            server_now := FLOOR(
                EXTRACT(EPOCH FROM clock_timestamp())
            )::BIGINT;
            IF retention_cutoff IS NOT NULL
               AND retention_cutoff > server_now + 5 THEN
                RAISE EXCEPTION 'retention cutoff is in the future';
            END IF;
            effective_cutoff := LEAST(retention_cutoff, server_now);
            IF TG_OP = 'DELETE'
               AND TG_TABLE_NAME = 'billing_contract_confirmations'
               AND retention_cutoff IS NOT NULL
               AND OLD.financial_retention_until <= effective_cutoff THEN
                RETURN OLD;
            END IF;
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
        END
        $function$
        """
    )


def _create_integrity_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION public.gsubs_prepare_billing_adjustment_record()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            refund_record RECORD;
            invoice_record RECORD;
            retention_deadline BIGINT;
        BEGIN
            PERFORM 1
            FROM public.credit_purchases
            WHERE id = NEW.purchase_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'billing adjustment purchase is unavailable';
            END IF;

            SELECT
                id,
                document_status,
                aade_mark,
                aade_series,
                aade_aa
            INTO invoice_record
            FROM public.billing_invoices
            WHERE purchase_id = NEW.purchase_id
            FOR UPDATE;
            IF NOT FOUND OR invoice_record.document_status <> 'issued' THEN
                RAISE EXCEPTION
                    'original AADE document must be recorded before adjustment';
            END IF;

            SELECT
                id,
                purchase_id,
                provider,
                provider_reversal_id,
                provider_event_created,
                kind,
                amount_cents,
                currency,
                status,
                active,
                created_at,
                updated_at
            INTO refund_record
            FROM public.credit_purchase_reversals
            WHERE id = NEW.reversal_id
            FOR UPDATE;
            IF NOT FOUND
               OR refund_record.purchase_id <> NEW.purchase_id
               OR refund_record.provider <> 'stripe'
               OR refund_record.kind <> 'refund'
               OR refund_record.provider_reversal_id
                    !~ '^re_[A-Za-z0-9_]+$'
               OR refund_record.status <> 'succeeded'
               OR refund_record.active IS NOT TRUE
               OR refund_record.amount_cents <> NEW.amount_cents
               OR lower(refund_record.currency) <> NEW.currency THEN
                RAISE EXCEPTION
                    'billing adjustment requires one completed Stripe refund';
            END IF;
            IF NEW.issued_at < refund_record.provider_event_created THEN
                RAISE EXCEPTION
                    'AADE adjustment cannot predate the Stripe refund';
            END IF;
            IF NEW.document_snapshot #>> '{stripe,refund_id}'
                    <> refund_record.provider_reversal_id
               OR NEW.document_snapshot #>> '{stripe,status}'
                    <> refund_record.status
               OR (
                    NEW.document_snapshot
                        #>> '{stripe,provider_event_created}'
                  )::BIGINT <> refund_record.provider_event_created THEN
                RAISE EXCEPTION
                    'billing adjustment snapshot conflicts with Stripe refund';
            END IF;
            IF invoice_record.aade_mark = NEW.aade_mark
               OR (
                    invoice_record.aade_series = NEW.aade_series
                    AND invoice_record.aade_aa = NEW.aade_aa
               )
               OR EXISTS (
                    SELECT 1
                    FROM public.billing_invoices
                    WHERE aade_mark = NEW.aade_mark
                       OR (
                            aade_series = NEW.aade_series
                            AND aade_aa = NEW.aade_aa
                       )
               ) THEN
                RAISE EXCEPTION
                    'AADE adjustment identity conflicts with an original document';
            END IF;

            retention_deadline :=
                public.gsubs_financial_retention_deadline(
                    GREATEST(
                        NEW.issued_at,
                        NEW.recorded_at,
                        refund_record.provider_event_created,
                        refund_record.created_at,
                        refund_record.updated_at
                    )
                );
            NEW.financial_retention_until :=
                GREATEST(
                    COALESCE(NEW.financial_retention_until, 0),
                    retention_deadline
                );
            UPDATE public.billing_invoices
            SET
                financial_retention_until = GREATEST(
                    financial_retention_until,
                    NEW.financial_retention_until
                ),
                updated_at = GREATEST(updated_at, NEW.recorded_at)
            WHERE purchase_id = NEW.purchase_id;
            UPDATE public.credit_purchases
            SET
                financial_retention_until = GREATEST(
                    financial_retention_until,
                    NEW.financial_retention_until
                ),
                updated_at = GREATEST(updated_at, NEW.recorded_at)
            WHERE id = NEW.purchase_id;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_billing_adjustment_records_prepare
        BEFORE INSERT ON public.billing_adjustment_records
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_billing_adjustment_record()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.gsubs_prepare_withdrawal_resolution()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            withdrawal_record RECORD;
            adjustment_record RECORD;
            refund_record RECORD;
            retention_deadline BIGINT;
        BEGIN
            PERFORM 1
            FROM public.credit_purchases
            WHERE id = NEW.purchase_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION
                    'withdrawal resolution purchase is unavailable';
            END IF;

            SELECT
                id,
                purchase_id,
                locale,
                submitted_at,
                financial_retention_until
            INTO withdrawal_record
            FROM public.billing_withdrawal_requests
            WHERE id = NEW.withdrawal_id;
            IF NOT FOUND
               OR withdrawal_record.purchase_id <> NEW.purchase_id
               OR withdrawal_record.locale <> NEW.locale
               OR NEW.resolved_at < withdrawal_record.submitted_at THEN
                RAISE EXCEPTION
                    'withdrawal resolution conflicts with request evidence';
            END IF;

            retention_deadline :=
                GREATEST(
                    withdrawal_record.financial_retention_until,
                    public.gsubs_financial_retention_deadline(
                        NEW.resolved_at
                    )
                );
            IF NEW.decision = 'accepted_refunded' THEN
                SELECT
                    id,
                    purchase_id,
                    reversal_id,
                    amount_cents,
                    currency,
                    financial_retention_until
                INTO adjustment_record
                FROM public.billing_adjustment_records
                WHERE id = NEW.adjustment_id;
                IF NOT FOUND
                   OR adjustment_record.purchase_id <> NEW.purchase_id THEN
                    RAISE EXCEPTION
                        'accepted withdrawal requires its AADE adjustment';
                END IF;
                SELECT
                    provider_reversal_id,
                    status,
                    active
                INTO refund_record
                FROM public.credit_purchase_reversals
                WHERE id = adjustment_record.reversal_id
                FOR UPDATE;
                IF NOT FOUND
                   OR refund_record.status <> 'succeeded'
                   OR refund_record.active IS NOT TRUE THEN
                    RAISE EXCEPTION
                        'accepted withdrawal requires a completed Stripe refund';
                END IF;
                IF NEW.resolution_snapshot
                        #>> '{manual_actions,stripe_refund_id}'
                        <> refund_record.provider_reversal_id
                   OR NEW.resolution_snapshot
                        #>> '{manual_actions,aade_adjustment_id}'
                        <> adjustment_record.id
                   OR (
                        NEW.resolution_snapshot
                            #>> '{manual_actions,refunded_amount_cents}'
                      )::INTEGER <> adjustment_record.amount_cents
                   OR NEW.resolution_snapshot
                        #>> '{manual_actions,currency}'
                        <> adjustment_record.currency THEN
                    RAISE EXCEPTION
                        'withdrawal resolution conflicts with manual actions';
                END IF;
                retention_deadline :=
                    GREATEST(
                        retention_deadline,
                        adjustment_record.financial_retention_until
                    );
            ELSIF NEW.resolution_snapshot -> 'manual_actions'
                    IS DISTINCT FROM 'null'::JSONB THEN
                RAISE EXCEPTION
                    'rejected withdrawal cannot claim manual refund actions';
            END IF;

            NEW.financial_retention_until :=
                GREATEST(
                    COALESCE(NEW.financial_retention_until, 0),
                    retention_deadline
                );
            UPDATE public.billing_invoices
            SET
                financial_retention_until = GREATEST(
                    financial_retention_until,
                    NEW.financial_retention_until
                ),
                updated_at = GREATEST(updated_at, NEW.resolved_at)
            WHERE purchase_id = NEW.purchase_id;
            UPDATE public.credit_purchases
            SET
                financial_retention_until = GREATEST(
                    financial_retention_until,
                    NEW.financial_retention_until
                ),
                updated_at = GREATEST(updated_at, NEW.resolved_at)
            WHERE id = NEW.purchase_id;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_billing_withdrawal_resolutions_prepare
        BEFORE INSERT ON public.billing_withdrawal_resolutions
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_withdrawal_resolution()
        """
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
