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


def _drop_credit_purchase_user_foreign_key() -> None:
    inspector = sa.inspect(op.get_bind())
    for constraint in inspector.get_foreign_keys("credit_purchases"):
        if constraint.get("constrained_columns") == ["user_id"]:
            name = constraint.get("name")
            if not name:
                raise RuntimeError("credit_purchases.user_id foreign key has no name")
            op.drop_constraint(name, "credit_purchases", type_="foreignkey")
            return
    raise RuntimeError("credit_purchases.user_id foreign key was not found")


def _create_retention_function() -> None:
    op.execute(
        """
        CREATE FUNCTION public.gsubs_financial_retention_deadline(reference_epoch BIGINT)
        RETURNS BIGINT
        LANGUAGE SQL
        IMMUTABLE
        STRICT
        SET search_path = pg_catalog, public
        AS $function$
            SELECT EXTRACT(
                EPOCH FROM (
                    make_timestamptz(
                        EXTRACT(
                            YEAR FROM (
                                to_timestamp(reference_epoch)
                                AT TIME ZONE 'Europe/Athens'
                            )
                        )::INTEGER + 6,
                        1,
                        1,
                        0,
                        0,
                        0,
                        'Europe/Athens'
                    ) - INTERVAL '1 second'
                )
            )::BIGINT
        $function$
        """
    )


def _create_credit_purchase_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION public.gsubs_prepare_credit_purchase_financial_record()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF NEW.account_reference_hash IS NULL AND NEW.user_id IS NOT NULL THEN
                NEW.account_reference_hash :=
                    md5(
                        'gsubs-financial-account'
                        || chr(58)
                        || 'v1'
                        || chr(58)
                        || NEW.user_id
                    )
                    || md5(
                        NEW.user_id
                        || chr(58)
                        || 'gsubs-financial-account'
                        || chr(58)
                        || 'v1'
                    );
            END IF;
            IF NEW.fulfilled_at IS NOT NULL
               OR NEW.payment_intent_id IS NOT NULL
               OR NEW.status NOT IN (
                   'creating',
                   'checkout_created',
                   'awaiting_payment',
                   'expired',
                   'failed'
               ) THEN
                NEW.financial_retention_until :=
                    GREATEST(
                        COALESCE(NEW.financial_retention_until, 0),
                        public.gsubs_financial_retention_deadline(
                            GREATEST(
                                NEW.created_at,
                                NEW.updated_at,
                                COALESCE(NEW.fulfilled_at, 0),
                                1
                            )
                        )
                    );
            ELSIF NEW.financial_retention_until IS NULL THEN
                NEW.financial_retention_until :=
                    GREATEST(
                        NEW.created_at,
                        NEW.updated_at,
                        1
                    ) + 86400;
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_credit_purchases_prepare_financial_record
        BEFORE INSERT OR UPDATE ON public.credit_purchases
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_credit_purchase_financial_record()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.gsubs_enforce_credit_purchase_immutability()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF OLD.snapshot IS DISTINCT FROM NEW.snapshot THEN
                RAISE EXCEPTION 'credit_purchases.snapshot is immutable';
            END IF;
            IF OLD.payment_snapshot IS NOT NULL
               AND OLD.payment_snapshot IS DISTINCT FROM NEW.payment_snapshot THEN
                RAISE EXCEPTION 'credit_purchases.payment_snapshot is immutable';
            END IF;
            IF OLD.customer_snapshot IS NOT NULL
               AND OLD.customer_snapshot IS DISTINCT FROM NEW.customer_snapshot THEN
                RAISE EXCEPTION 'credit_purchases.customer_snapshot is immutable';
            END IF;
            IF OLD.tax_snapshot IS NOT NULL
               AND OLD.tax_snapshot IS DISTINCT FROM NEW.tax_snapshot THEN
                RAISE EXCEPTION 'credit_purchases.tax_snapshot is immutable';
            END IF;
            IF OLD.account_reference_hash IS NOT NULL
               AND OLD.account_reference_hash IS DISTINCT FROM NEW.account_reference_hash THEN
                RAISE EXCEPTION 'credit_purchases.account_reference_hash is immutable';
            END IF;
            IF OLD.financial_retention_until IS NOT NULL
               AND (
                   NEW.financial_retention_until IS NULL
                   OR NEW.financial_retention_until < OLD.financial_retention_until
               ) THEN
                RAISE EXCEPTION 'credit_purchases.financial_retention_until cannot be shortened';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_credit_purchases_enforce_immutability
        BEFORE UPDATE ON public.credit_purchases
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_enforce_credit_purchase_immutability()
        """
    )


def _create_billing_invoice_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION public.gsubs_prepare_billing_invoice()
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
    op.execute(
        """
        CREATE TRIGGER trg_billing_invoices_prepare
        BEFORE INSERT OR UPDATE ON public.billing_invoices
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_billing_invoice()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.gsubs_enforce_billing_invoice_immutability()
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
    op.execute(
        """
        CREATE TRIGGER trg_billing_invoices_enforce_immutability
        BEFORE UPDATE ON public.billing_invoices
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_enforce_billing_invoice_immutability()
        """
    )


def _create_credit_purchase_reversal_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION public.gsubs_enforce_credit_purchase_reversal_timestamps()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            IF TG_OP = 'UPDATE' THEN
                IF OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                    RAISE EXCEPTION 'credit_purchase_reversals.created_at is immutable';
                END IF;
                IF NEW.provider_event_created < OLD.provider_event_created THEN
                    RAISE EXCEPTION 'credit_purchase_reversals.provider_event_created cannot move backwards';
                END IF;
                IF NEW.updated_at < OLD.updated_at THEN
                    RAISE EXCEPTION 'credit_purchase_reversals.updated_at cannot move backwards';
                END IF;
            END IF;
            IF NEW.provider_event_created <= 0
               OR NEW.created_at <= 0
               OR NEW.updated_at < NEW.created_at THEN
                RAISE EXCEPTION 'credit_purchase_reversals timestamps are invalid';
            END IF;
            RETURN NEW;
        END
        $function$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_credit_purchase_reversals_enforce_timestamps
        BEFORE INSERT OR UPDATE ON public.credit_purchase_reversals
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_enforce_credit_purchase_reversal_timestamps()
        """
    )


def _create_durable_billing_mutation_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION public.gsubs_reject_durable_billing_truncate()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        BEGIN
            RAISE EXCEPTION '% contains durable financial evidence and cannot be truncated',
                TG_TABLE_NAME;
            RETURN NULL;
        END
        $function$
        """
    )
    for table_name in (
        "credit_purchases",
        "billing_invoices",
        "credit_purchase_reversals",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_reject_truncate
            BEFORE TRUNCATE ON public.{table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.gsubs_reject_durable_billing_truncate()
            """
        )
    op.execute(
        """
        CREATE FUNCTION public.gsubs_guard_durable_billing_delete()
        RETURNS trigger
        LANGUAGE plpgsql
        SET search_path = pg_catalog, public
        AS $function$
        DECLARE
            retention_cutoff BIGINT;
            server_now BIGINT;
            effective_cutoff BIGINT;
            record_purchase_id TEXT;
            purchase_record public.credit_purchases%ROWTYPE;
            has_invoice BOOLEAN := FALSE;
            has_reversal BOOLEAN := FALSE;
            has_blocking_reversal BOOLEAN := FALSE;
            has_confirmation BOOLEAN := FALSE;
            has_unexpired_confirmation BOOLEAN := FALSE;
            has_withdrawal BOOLEAN := FALSE;
            has_pending_withdrawal BOOLEAN := FALSE;
            linked_invoice_status TEXT;
            linked_invoice_retention BIGINT;
        BEGIN
            IF NULLIF(
                current_setting(
                    'gsubs.billing_retention_cutoff',
                    TRUE
                ),
                ''
            ) IS NULL THEN
                RAISE EXCEPTION 'billing retention cutoff is required';
            END IF;
            retention_cutoff := current_setting(
                'gsubs.billing_retention_cutoff',
                TRUE
            )::BIGINT;
            IF retention_cutoff <= 0 THEN
                RAISE EXCEPTION 'billing retention cutoff must be positive';
            END IF;
            server_now := FLOOR(
                EXTRACT(EPOCH FROM clock_timestamp())
            )::BIGINT;
            IF retention_cutoff > server_now + 5 THEN
                RAISE EXCEPTION 'billing retention cutoff is in the future';
            END IF;
            effective_cutoff := LEAST(retention_cutoff, server_now);
            IF TG_TABLE_NAME = 'credit_purchases' THEN
                record_purchase_id := OLD.id;
            ELSE
                record_purchase_id := OLD.purchase_id;
            END IF;

            -- Every application writer locks the purchase before its invoice
            -- or reversal. Matching that order serializes cleanup with Stripe
            -- webhook and AADE-link writers without a child/parent deadlock.
            SELECT purchase.*
            INTO purchase_record
            FROM public.credit_purchases AS purchase
            WHERE purchase.id = record_purchase_id
            FOR UPDATE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'billing purchase is unavailable for retention cleanup';
            END IF;

            SELECT
                EXISTS (
                    SELECT 1
                    FROM public.credit_purchase_reversals AS reversal
                    WHERE reversal.purchase_id = record_purchase_id
                ),
                EXISTS (
                SELECT 1
                FROM public.credit_purchase_reversals AS reversal
                WHERE reversal.purchase_id = record_purchase_id
                  AND reversal.active IS TRUE
                  AND (
                      reversal.kind = 'dispute'
                      OR (
                          reversal.kind = 'refund'
                          AND reversal.status IN (
                              'pending',
                              'requires_action'
                          )
                      )
                  )
                )
            INTO has_reversal, has_blocking_reversal;

            IF to_regclass(
                'public.billing_contract_confirmations'
            ) IS NOT NULL THEN
                EXECUTE
                    'SELECT EXISTS (
                        SELECT 1
                        FROM public.billing_contract_confirmations
                        WHERE purchase_id = $1
                    ),
                    EXISTS (
                        SELECT 1
                        FROM public.billing_contract_confirmations
                        WHERE purchase_id = $1
                          AND financial_retention_until > $2
                    )'
                INTO has_confirmation, has_unexpired_confirmation
                USING record_purchase_id, effective_cutoff;
            END IF;
            IF to_regclass(
                'public.billing_withdrawal_requests'
            ) IS NOT NULL THEN
                EXECUTE
                    'SELECT EXISTS (
                        SELECT 1
                        FROM public.billing_withdrawal_requests
                        WHERE purchase_id = $1
                    ),
                    EXISTS (
                        SELECT 1
                        FROM public.billing_withdrawal_requests
                        WHERE purchase_id = $1
                          AND status = ''pending_manual_review''
                    )'
                INTO has_withdrawal, has_pending_withdrawal
                USING record_purchase_id;
            END IF;

            IF TG_TABLE_NAME = 'credit_purchases' THEN
                SELECT EXISTS (
                    SELECT 1
                    FROM public.billing_invoices
                    WHERE purchase_id = record_purchase_id
                )
                INTO has_invoice;
                IF purchase_record.financial_retention_until <= effective_cutoff
                   AND purchase_record.status IN ('expired', 'failed')
                   AND purchase_record.fulfilled_at IS NULL
                   AND purchase_record.payment_intent_id IS NULL
                   AND (
                       purchase_record.payment_snapshot IS NULL
                       OR purchase_record.payment_snapshot = 'null'::jsonb
                   )
                   AND purchase_record.refunded_amount_cents = 0
                   AND purchase_record.dispute_active IS FALSE
                   AND purchase_record.reversed_credits = 0
                   AND purchase_record.reversal_debt_credits = 0
                   AND purchase_record.reversed_amount_cents = 0
                   AND NOT has_invoice
                   AND NOT has_reversal
                   AND NOT has_confirmation
                   AND NOT has_withdrawal THEN
                    RETURN OLD;
                END IF;

                IF purchase_record.financial_retention_until <= effective_cutoff
                   AND (
                       purchase_record.fulfilled_at IS NOT NULL
                       OR purchase_record.payment_intent_id IS NOT NULL
                       OR (
                           purchase_record.payment_snapshot IS NOT NULL
                           AND purchase_record.payment_snapshot <> 'null'::jsonb
                       )
                       OR purchase_record.refunded_amount_cents > 0
                       OR purchase_record.reversed_credits > 0
                       OR purchase_record.reversal_debt_credits > 0
                       OR purchase_record.reversed_amount_cents > 0
                   )
                   AND purchase_record.dispute_active IS FALSE
                   AND NOT has_invoice
                   AND NOT has_reversal
                   AND NOT has_pending_withdrawal
                   AND NOT has_unexpired_confirmation THEN
                    RETURN OLD;
                END IF;
            ELSIF TG_TABLE_NAME = 'billing_invoices' THEN
                IF OLD.document_status = 'issued'
                   AND OLD.financial_retention_until <= effective_cutoff
                   AND purchase_record.financial_retention_until <= effective_cutoff
                   AND purchase_record.dispute_active IS FALSE
                   AND NOT has_reversal
                   AND NOT has_blocking_reversal
                   AND NOT has_pending_withdrawal
                   AND NOT has_unexpired_confirmation THEN
                    RETURN OLD;
                END IF;
            ELSIF TG_TABLE_NAME = 'credit_purchase_reversals' THEN
                SELECT
                    invoice.document_status,
                    invoice.financial_retention_until
                INTO
                    linked_invoice_status,
                    linked_invoice_retention
                FROM public.billing_invoices AS invoice
                WHERE invoice.purchase_id = record_purchase_id;
                IF linked_invoice_status = 'issued'
                   AND linked_invoice_retention <= effective_cutoff
                   AND purchase_record.financial_retention_until <= effective_cutoff
                   AND public.gsubs_financial_retention_deadline(
                       GREATEST(
                           OLD.provider_event_created,
                           OLD.created_at,
                           OLD.updated_at
                       )
                   ) <= effective_cutoff
                   AND purchase_record.dispute_active IS FALSE
                   AND NOT has_blocking_reversal
                   AND NOT has_pending_withdrawal
                   AND NOT has_unexpired_confirmation THEN
                    RETURN OLD;
                END IF;
            END IF;

            RAISE EXCEPTION '% contains retained financial evidence and cannot be deleted',
                TG_TABLE_NAME;
        END
        $function$
        """
    )
    for table_name in (
        "credit_purchases",
        "billing_invoices",
        "credit_purchase_reversals",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_guard_delete
            BEFORE DELETE ON public.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION public.gsubs_guard_durable_billing_delete()
            """
        )


def _backfill_legacy_financial_records() -> None:
    """Preserve pre-0013 paid and reversal evidence for manual review.

    The legacy schema did not retain immutable payment/customer/tax snapshots
    or provider reversal object identifiers. The migration therefore records
    only facts that already exist, labels every generated record as incomplete,
    and keeps reversal baselines active until an operator reviews them.
    """
    op.execute(
        """
        UPDATE public.credit_purchases
        SET
            reversed_amount_cents = LEAST(
                amount_eur_cents,
                GREATEST(
                    refunded_amount_cents,
                    CASE
                        WHEN dispute_active THEN amount_eur_cents
                        WHEN reversed_credits <= 0 THEN 0
                        WHEN reversed_credits >= credits THEN amount_eur_cents
                        ELSE (
                            FLOOR(
                                (
                                    (reversed_credits - 1)::NUMERIC
                                    * amount_eur_cents
                                )
                                / credits
                            )::INTEGER + 1
                        )
                    END
                )
            ),
            financial_retention_until = GREATEST(
                financial_retention_until,
                public.gsubs_financial_retention_deadline(
                    GREATEST(
                        created_at,
                        updated_at,
                        COALESCE(fulfilled_at, 0),
                        1
                    )
                )
            )
        WHERE fulfilled_at IS NOT NULL
           OR payment_intent_id IS NOT NULL
           OR refunded_amount_cents > 0
           OR dispute_active IS TRUE
           OR reversed_credits > 0
           OR reversal_debt_credits > 0
        """
    )
    op.execute(
        """
        INSERT INTO public.billing_invoices (
            id,
            purchase_id,
            provider,
            document_kind,
            document_status,
            aade_document_type,
            aade_series,
            aade_aa,
            aade_mark,
            issued_at,
            document_snapshot,
            financial_retention_until,
            created_at,
            updated_at
        )
        SELECT
            md5('gsubs-legacy-aade-invoice:v1:' || purchase.id),
            purchase.id,
            'aade_etimologio',
            'retail_service_receipt',
            'manual_review_required',
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            jsonb_build_object(
                'schema_version', 1,
                'migration_source', '0013_durable_billing_records',
                'record_origin', 'legacy_pre_0013_purchase',
                'legacy_incomplete', TRUE,
                'manual_review_required', TRUE,
                'missing_evidence', jsonb_build_array(
                    'payment_snapshot',
                    'customer_snapshot',
                    'tax_snapshot',
                    'aade_document_identity'
                ),
                'source_purchase_id', purchase.id,
                'package_key', purchase.package_key,
                'credits', purchase.credits,
                'gross_amount_cents', purchase.amount_eur_cents,
                'currency', lower(purchase.currency),
                'fulfilled_at', purchase.fulfilled_at,
                'payment_intent_present',
                    purchase.payment_intent_id IS NOT NULL
            ),
            purchase.financial_retention_until,
            GREATEST(
                purchase.created_at,
                COALESCE(purchase.fulfilled_at, 0),
                1
            ),
            GREATEST(
                purchase.updated_at,
                purchase.created_at,
                COALESCE(purchase.fulfilled_at, 0),
                1
            )
        FROM public.credit_purchases AS purchase
        WHERE purchase.fulfilled_at IS NOT NULL
           OR purchase.payment_intent_id IS NOT NULL
        ON CONFLICT (purchase_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO public.credit_purchase_reversals (
            id,
            purchase_id,
            provider,
            provider_reversal_id,
            provider_event_id,
            provider_event_created,
            kind,
            amount_cents,
            currency,
            status,
            active,
            created_at,
            updated_at
        )
        SELECT
            md5('gsubs-legacy-reversal:v1:refund:' || purchase.id),
            purchase.id,
            'legacy_migration',
            'legacy:0013:refund:' || purchase.id,
            NULL,
            GREATEST(
                purchase.created_at,
                purchase.updated_at,
                COALESCE(purchase.fulfilled_at, 0),
                1
            ),
            'refund',
            LEAST(
                purchase.amount_eur_cents,
                GREATEST(
                    purchase.refunded_amount_cents,
                    CASE
                        WHEN purchase.dispute_active THEN 0
                        WHEN purchase.reversed_credits <= 0 THEN 0
                        WHEN purchase.reversed_credits >= purchase.credits
                            THEN purchase.amount_eur_cents
                        ELSE (
                            FLOOR(
                                (
                                    (purchase.reversed_credits - 1)::NUMERIC
                                    * purchase.amount_eur_cents
                                )
                                / purchase.credits
                            )::INTEGER + 1
                        )
                    END
                )
            ),
            lower(purchase.currency),
            CASE
                WHEN purchase.refunded_amount_cents > 0
                    THEN 'legacy_refund_manual_review'
                ELSE 'legacy_reversal_manual_review'
            END,
            TRUE,
            GREATEST(purchase.created_at, 1),
            GREATEST(purchase.updated_at, purchase.created_at, 1)
        FROM public.credit_purchases AS purchase
        WHERE purchase.refunded_amount_cents > 0
           OR (
                purchase.dispute_active IS FALSE
                AND purchase.reversed_credits > 0
           )
        ON CONFLICT (provider, provider_reversal_id) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO public.credit_purchase_reversals (
            id,
            purchase_id,
            provider,
            provider_reversal_id,
            provider_event_id,
            provider_event_created,
            kind,
            amount_cents,
            currency,
            status,
            active,
            created_at,
            updated_at
        )
        SELECT
            md5('gsubs-legacy-reversal:v1:dispute:' || purchase.id),
            purchase.id,
            'legacy_migration',
            'legacy:0013:dispute:' || purchase.id,
            NULL,
            GREATEST(
                purchase.created_at,
                purchase.updated_at,
                COALESCE(purchase.fulfilled_at, 0),
                1
            ),
            'dispute',
            purchase.amount_eur_cents,
            lower(purchase.currency),
            'legacy_dispute_manual_review',
            TRUE,
            GREATEST(purchase.created_at, 1),
            GREATEST(purchase.updated_at, purchase.created_at, 1)
        FROM public.credit_purchases AS purchase
        WHERE purchase.dispute_active IS TRUE
        ON CONFLICT (provider, provider_reversal_id) DO NOTHING
        """
    )


def _ensure_downgrade_is_safe() -> None:
    """Refuse rollback before dropping any durable financial evidence."""
    bind = op.get_bind()
    # Serialize every safety check and destructive DDL step with current and
    # future financial-evidence writers. Otherwise an uncommitted insert can be
    # invisible to the checks and commit while the downgrade waits to DROP.
    bind.execute(
        sa.text(
            """
            LOCK TABLE
                public.credit_purchases,
                public.credit_purchase_reversals,
                public.billing_invoices
            IN ACCESS EXCLUSIVE MODE
            """
        )
    )
    orphaned_purchase = bind.execute(
        sa.text(
            """
            SELECT id
            FROM public.credit_purchases
            WHERE user_id IS NULL
            LIMIT 1
            """
        )
    ).scalar_one_or_none()
    if orphaned_purchase is not None:
        raise RuntimeError("Cannot downgrade durable billing records while anonymized credit purchases exist.")

    durable_record_exists = bool(
        bind.execute(
            sa.text(
                """
                SELECT
                    EXISTS (SELECT 1 FROM public.billing_invoices)
                    OR EXISTS (SELECT 1 FROM public.credit_purchase_reversals)
                    OR EXISTS (
                        SELECT 1
                        FROM public.credit_purchases
                        WHERE payment_snapshot IS NOT NULL
                           OR customer_snapshot IS NOT NULL
                           OR tax_snapshot IS NOT NULL
                           OR fulfilled_at IS NOT NULL
                           OR payment_intent_id IS NOT NULL
                           OR refunded_amount_cents > 0
                           OR dispute_active IS TRUE
                           OR reversed_credits > 0
                           OR reversal_debt_credits > 0
                           OR reversed_amount_cents > 0
                           OR status NOT IN (
                               'creating',
                               'checkout_created',
                               'awaiting_payment',
                               'expired',
                               'failed'
                           )
                    )
                """
            )
        ).scalar_one()
    )
    if durable_record_exists:
        raise RuntimeError("Cannot downgrade durable billing records while durable paid financial records exist.")


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

    op.execute(
        "DROP TRIGGER trg_credit_purchase_reversals_reject_truncate "
        "ON public.credit_purchase_reversals"
    )
    op.execute("DROP TRIGGER trg_billing_invoices_reject_truncate ON public.billing_invoices")
    op.execute("DROP TRIGGER trg_credit_purchases_reject_truncate ON public.credit_purchases")
    op.execute("DROP FUNCTION public.gsubs_reject_durable_billing_truncate()")

    op.execute(
        "DROP TRIGGER trg_credit_purchase_reversals_enforce_timestamps "
        "ON public.credit_purchase_reversals"
    )
    op.execute(
        "DROP FUNCTION public.gsubs_enforce_credit_purchase_reversal_timestamps()"
    )

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

    op.execute(
        "DROP TRIGGER trg_billing_invoices_enforce_immutability "
        "ON public.billing_invoices"
    )
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

    op.execute(
        "DROP TRIGGER trg_credit_purchases_enforce_immutability "
        "ON public.credit_purchases"
    )
    op.execute("DROP FUNCTION public.gsubs_enforce_credit_purchase_immutability()")
    op.execute(
        "DROP TRIGGER trg_credit_purchases_prepare_financial_record "
        "ON public.credit_purchases"
    )
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
