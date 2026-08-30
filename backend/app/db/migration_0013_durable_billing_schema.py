"""Frozen schema helpers for Alembic revision 0013_durable_billing_records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_1 = """
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

_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_2 = """
        CREATE TRIGGER trg_credit_purchases_prepare_financial_record
        BEFORE INSERT OR UPDATE ON public.credit_purchases
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_credit_purchase_financial_record()
        """

_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_3 = """
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

_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_4 = """
        CREATE TRIGGER trg_credit_purchases_enforce_immutability
        BEFORE UPDATE ON public.credit_purchases
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_enforce_credit_purchase_immutability()
        """

_SQL_CREATE_BILLING_INVOICE_TRIGGERS_1 = """
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

_SQL_CREATE_BILLING_INVOICE_TRIGGERS_2 = """
        CREATE TRIGGER trg_billing_invoices_prepare
        BEFORE INSERT OR UPDATE ON public.billing_invoices
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_billing_invoice()
        """

_SQL_CREATE_BILLING_INVOICE_TRIGGERS_3 = """
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

_SQL_CREATE_BILLING_INVOICE_TRIGGERS_4 = """
        CREATE TRIGGER trg_billing_invoices_enforce_immutability
        BEFORE UPDATE ON public.billing_invoices
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_enforce_billing_invoice_immutability()
        """

_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_1 = """
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

_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_2 = """
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

_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_3 = """
            CREATE TRIGGER trg_{table_name}_reject_truncate
            BEFORE TRUNCATE ON public.{table_name}
            FOR EACH STATEMENT
            EXECUTE FUNCTION public.gsubs_reject_durable_billing_truncate()
            """

_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_4 = """
            CREATE TRIGGER trg_{table_name}_guard_delete
            BEFORE DELETE ON public.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION public.gsubs_guard_durable_billing_delete()
            """


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
    op.execute(_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_1)
    op.execute(_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_2)
    op.execute(_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_3)
    op.execute(_SQL_CREATE_CREDIT_PURCHASE_TRIGGERS_4)


def _create_billing_invoice_triggers() -> None:
    op.execute(_SQL_CREATE_BILLING_INVOICE_TRIGGERS_1)
    op.execute(_SQL_CREATE_BILLING_INVOICE_TRIGGERS_2)
    op.execute(_SQL_CREATE_BILLING_INVOICE_TRIGGERS_3)
    op.execute(_SQL_CREATE_BILLING_INVOICE_TRIGGERS_4)


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
    op.execute(_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_1)
    for table_name in (
        "credit_purchases",
        "billing_invoices",
        "credit_purchase_reversals",
    ):
        op.execute(_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_3.format(table_name=table_name))
    op.execute(_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_2)
    for table_name in (
        "credit_purchases",
        "billing_invoices",
        "credit_purchase_reversals",
    ):
        op.execute(_SQL_CREATE_DURABLE_BILLING_MUTATION_GUARDS_4.format(table_name=table_name))
