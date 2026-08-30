"""Frozen data and downgrade helpers for revision 0013_durable_billing_records."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_1 = """
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

_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_2 = """
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

_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_3 = """
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

_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_4 = """
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

_SQL_ENSURE_DOWNGRADE_IS_SAFE_1 = """
            LOCK TABLE
                public.credit_purchases,
                public.credit_purchase_reversals,
                public.billing_invoices
            IN ACCESS EXCLUSIVE MODE
            """

_SQL_ENSURE_DOWNGRADE_IS_SAFE_2 = """
            SELECT id
            FROM public.credit_purchases
            WHERE user_id IS NULL
            LIMIT 1
            """

_SQL_ENSURE_DOWNGRADE_IS_SAFE_3 = """
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


def _backfill_legacy_financial_records() -> None:
    """Preserve pre-0013 paid and reversal evidence for manual review.

    The legacy schema did not retain immutable payment/customer/tax snapshots
    or provider reversal object identifiers. The migration therefore records
    only facts that already exist, labels every generated record as incomplete,
    and keeps reversal baselines active until an operator reviews them.
    """
    op.execute(_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_1)
    op.execute(_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_2)
    op.execute(_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_3)
    op.execute(_SQL_BACKFILL_LEGACY_FINANCIAL_RECORDS_4)


def _ensure_downgrade_is_safe() -> None:
    """Refuse rollback before dropping any durable financial evidence."""
    bind = op.get_bind()
    # Serialize every safety check and destructive DDL step with current and
    # future financial-evidence writers. Otherwise an uncommitted insert can be
    # invisible to the checks and commit while the downgrade waits to DROP.
    bind.execute(sa.text(_SQL_ENSURE_DOWNGRADE_IS_SAFE_1))
    orphaned_purchase = bind.execute(sa.text(_SQL_ENSURE_DOWNGRADE_IS_SAFE_2)).scalar_one_or_none()
    if orphaned_purchase is not None:
        raise RuntimeError("Cannot downgrade durable billing records while anonymized credit purchases exist.")

    durable_record_exists = bool(bind.execute(sa.text(_SQL_ENSURE_DOWNGRADE_IS_SAFE_3)).scalar_one())
    if durable_record_exists:
        raise RuntimeError("Cannot downgrade durable billing records while durable paid financial records exist.")
