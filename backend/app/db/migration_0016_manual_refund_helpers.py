"""Frozen helpers for Alembic revision 0016_manual_refund_accounting."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

_SQL_REPLACE_APPEND_ONLY_FUNCTION_1 = """
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

_SQL_CREATE_INTEGRITY_TRIGGERS_1 = """
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

_SQL_CREATE_INTEGRITY_TRIGGERS_2 = """
        CREATE TRIGGER trg_billing_adjustment_records_prepare
        BEFORE INSERT ON public.billing_adjustment_records
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_billing_adjustment_record()
        """

_SQL_CREATE_INTEGRITY_TRIGGERS_3 = """
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

_SQL_CREATE_INTEGRITY_TRIGGERS_4 = """
        CREATE TRIGGER trg_billing_withdrawal_resolutions_prepare
        BEFORE INSERT ON public.billing_withdrawal_resolutions
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_withdrawal_resolution()
        """


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
    op.execute(_SQL_REPLACE_APPEND_ONLY_FUNCTION_1)


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
    op.execute(_SQL_CREATE_INTEGRITY_TRIGGERS_1)
    op.execute(_SQL_CREATE_INTEGRITY_TRIGGERS_2)
    op.execute(_SQL_CREATE_INTEGRITY_TRIGGERS_3)
    op.execute(_SQL_CREATE_INTEGRITY_TRIGGERS_4)
