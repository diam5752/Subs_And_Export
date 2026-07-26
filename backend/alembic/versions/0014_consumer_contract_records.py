"""Add immutable contract confirmations and online withdrawal requests.

Revision ID: 0014_consumer_contract_records
Revises: 0013_durable_billing_records
Create Date: 2026-07-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_consumer_contract_records"
down_revision = "0013_durable_billing_records"
branch_labels = None
depends_on = None


def _create_append_only_trigger(table_name: str, trigger_name: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER {trigger_name}
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


def _create_consumer_record_retention_triggers() -> None:
    op.execute(
        """
        CREATE FUNCTION public.gsubs_prepare_contract_confirmation_retention()
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
                            NEW.contract_concluded_at,
                            NEW.available_at,
                            NEW.created_at
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
        CREATE TRIGGER trg_billing_contract_confirmations_prepare_retention
        BEFORE INSERT ON public.billing_contract_confirmations
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_contract_confirmation_retention()
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.gsubs_prepare_withdrawal_request_retention()
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
                            NEW.submitted_at,
                            NEW.available_at,
                            NEW.created_at
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
        CREATE TRIGGER trg_billing_withdrawal_requests_prepare_retention
        BEFORE INSERT ON public.billing_withdrawal_requests
        FOR EACH ROW
        EXECUTE FUNCTION public.gsubs_prepare_withdrawal_request_retention()
        """
    )


def _assert_downgrade_safe() -> None:
    bind = op.get_bind()
    # Serialize the emptiness check with every current or future evidence
    # writer. Without this lock, an uncommitted insert is invisible to the
    # SELECT and can commit while the downgrade is waiting to DROP the table.
    bind.execute(
        sa.text(
            """
            LOCK TABLE
                public.billing_withdrawal_requests,
                public.billing_contract_confirmations
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
                        FROM public.billing_contract_confirmations
                    )
                    OR EXISTS (
                        SELECT 1
                        FROM public.billing_withdrawal_requests
                    )
                """
            )
        ).scalar_one()
    )
    if durable_record_exists:
        raise RuntimeError("Cannot downgrade while consumer-contract or withdrawal evidence exists.")


def upgrade() -> None:
    json_value = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")

    op.create_table(
        "billing_contract_confirmations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("purchase_id", sa.String(length=32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column("contract_concluded_at", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=160), nullable=False),
        sa.Column("content_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("consumer_contract_sha256", sa.String(length=64), nullable=False),
        sa.Column("delivery_channel", sa.String(length=32), nullable=False),
        sa.Column("delivery_status", sa.String(length=64), nullable=False),
        sa.Column("available_at", sa.BigInteger(), nullable=False),
        sa.Column("financial_retention_until", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "schema_version > 0",
            name="chk_billing_contract_confirmations_schema_version",
        ),
        sa.CheckConstraint(
            "locale IN ('el','en')",
            name="chk_billing_contract_confirmations_locale",
        ),
        sa.CheckConstraint(
            "content_sha256 ~ '^[0-9a-f]{64}$' "
            "AND consumer_contract_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(content_bytes) > 0 "
            "AND content_sha256 = encode(sha256(content_bytes), 'hex')",
            name="chk_billing_contract_confirmations_hashes",
        ),
        sa.CheckConstraint(
            "mime_type = 'application/json; charset=utf-8' AND filename = 'gsubs-contract-' || purchase_id || '.json'",
            name="chk_billing_contract_confirmations_artifact",
        ),
        sa.CheckConstraint(
            "(convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'document_type' = 'gsubs_consumer_contract_confirmation' "
            "AND convert_from(content_bytes, 'UTF8')::jsonb #>> "
            "'{purchase,purchase_id}' = purchase_id "
            "AND convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'consumer_contract_sha256' = consumer_contract_sha256 "
            "AND convert_from(content_bytes, 'UTF8')::jsonb #>> "
            "'{consumer_contract,locale}' = locale "
            "AND (convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'schema_version')::INTEGER = schema_version "
            "AND (convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'contract_concluded_at')::BIGINT = contract_concluded_at "
            "AND (convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'available_at')::BIGINT = available_at "
            "AND convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'delivery_channel' = delivery_channel "
            "AND convert_from(content_bytes, 'UTF8')::jsonb ->> "
            "'delivery_status' = delivery_status) IS TRUE",
            name="chk_billing_contract_confirmations_identity",
        ),
        sa.CheckConstraint(
            "delivery_channel = 'account_vault' AND delivery_status = 'available_pending_external_approval'",
            name="chk_billing_contract_confirmations_delivery",
        ),
        sa.CheckConstraint(
            "contract_concluded_at > 0 "
            "AND available_at >= contract_concluded_at "
            "AND created_at = available_at "
            "AND financial_retention_until > contract_concluded_at",
            name="chk_billing_contract_confirmations_timestamps",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["credit_purchases.id"],
            name="fk_billing_contract_confirmations_purchase_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_id",
            name="uq_billing_contract_confirmations_purchase_id",
        ),
    )
    op.create_index(
        "ix_billing_contract_confirmations_purchase_id",
        "billing_contract_confirmations",
        ["purchase_id"],
    )
    op.create_index(
        "ix_billing_contract_confirmations_retention",
        "billing_contract_confirmations",
        ["financial_retention_until"],
    )

    op.create_table(
        "billing_withdrawal_requests",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("purchase_id", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(length=8), nullable=False),
        sa.Column(
            "status",
            sa.String(length=64),
            nullable=False,
            server_default="pending_manual_review",
        ),
        sa.Column("request_snapshot", json_value, nullable=False),
        sa.Column("request_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("request_sha256", sa.String(length=64), nullable=False),
        sa.Column("submitted_at", sa.BigInteger(), nullable=False),
        sa.Column("acknowledgement_mime_type", sa.String(length=64), nullable=False),
        sa.Column("acknowledgement_filename", sa.String(length=160), nullable=False),
        sa.Column("acknowledgement_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("acknowledgement_sha256", sa.String(length=64), nullable=False),
        sa.Column("available_at", sa.BigInteger(), nullable=False),
        sa.Column("financial_retention_until", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "schema_version > 0",
            name="chk_billing_withdrawal_requests_schema_version",
        ),
        sa.CheckConstraint(
            "locale IN ('el','en')",
            name="chk_billing_withdrawal_requests_locale",
        ),
        sa.CheckConstraint(
            "status = 'pending_manual_review'",
            name="chk_billing_withdrawal_requests_status",
        ),
        sa.CheckConstraint(
            "request_sha256 ~ '^[0-9a-f]{64}$' "
            "AND acknowledgement_sha256 ~ '^[0-9a-f]{64}$' "
            "AND octet_length(request_bytes) > 0 "
            "AND octet_length(acknowledgement_bytes) > 0 "
            "AND request_sha256 = encode(sha256(request_bytes), 'hex') "
            "AND acknowledgement_sha256 = "
            "encode(sha256(acknowledgement_bytes), 'hex')",
            name="chk_billing_withdrawal_requests_hashes",
        ),
        sa.CheckConstraint(
            "acknowledgement_mime_type = "
            "'application/json; charset=utf-8' "
            "AND acknowledgement_filename = "
            "'gsubs-withdrawal-' || purchase_id || '.json'",
            name="chk_billing_withdrawal_requests_artifact",
        ),
        sa.CheckConstraint(
            "(jsonb_typeof(convert_from(request_bytes, 'UTF8')::jsonb) = "
            "'object' AND convert_from(request_bytes, 'UTF8')::jsonb = "
            "request_snapshot) IS TRUE",
            name="chk_billing_withdrawal_requests_snapshot",
        ),
        sa.CheckConstraint(
            "submitted_at > 0 "
            "AND available_at >= submitted_at "
            "AND created_at = available_at "
            "AND financial_retention_until > submitted_at",
            name="chk_billing_withdrawal_requests_timestamps",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["credit_purchases.id"],
            name="fk_billing_withdrawal_requests_purchase_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["billing_contract_confirmations.purchase_id"],
            name="fk_billing_withdrawal_requests_confirmation_purchase_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "purchase_id",
            name="uq_billing_withdrawal_requests_purchase_id",
        ),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_billing_withdrawal_requests_idempotency_key",
        ),
    )
    op.create_index(
        "ix_billing_withdrawal_requests_purchase_id",
        "billing_withdrawal_requests",
        ["purchase_id"],
    )
    op.create_index(
        "ix_billing_withdrawal_requests_status_submitted",
        "billing_withdrawal_requests",
        ["status", "submitted_at"],
    )
    op.create_index(
        "ix_billing_withdrawal_requests_retention",
        "billing_withdrawal_requests",
        ["financial_retention_until"],
    )
    _create_consumer_record_retention_triggers()

    op.execute(
        """
        CREATE FUNCTION public.gsubs_reject_append_only_billing_mutation()
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
    _create_append_only_trigger(
        "billing_contract_confirmations",
        "trg_billing_contract_confirmations_append_only",
    )
    _create_append_only_trigger(
        "billing_withdrawal_requests",
        "trg_billing_withdrawal_requests_append_only",
    )


def downgrade() -> None:
    _assert_downgrade_safe()

    op.execute(
        "DROP TRIGGER trg_billing_withdrawal_requests_prepare_retention "
        "ON public.billing_withdrawal_requests"
    )
    op.execute(
        "DROP FUNCTION public.gsubs_prepare_withdrawal_request_retention()"
    )
    op.execute(
        "DROP TRIGGER trg_billing_contract_confirmations_prepare_retention "
        "ON public.billing_contract_confirmations"
    )
    op.execute(
        "DROP FUNCTION public.gsubs_prepare_contract_confirmation_retention()"
    )

    op.execute(
        "DROP TRIGGER trg_billing_withdrawal_requests_reject_truncate "
        "ON public.billing_withdrawal_requests"
    )
    op.execute(
        "DROP TRIGGER trg_billing_contract_confirmations_reject_truncate "
        "ON public.billing_contract_confirmations"
    )
    op.execute(
        "DROP TRIGGER trg_billing_withdrawal_requests_append_only "
        "ON public.billing_withdrawal_requests"
    )
    op.execute(
        "DROP TRIGGER trg_billing_contract_confirmations_append_only "
        "ON public.billing_contract_confirmations"
    )
    op.execute("DROP FUNCTION public.gsubs_reject_append_only_billing_mutation()")

    op.drop_index(
        "ix_billing_withdrawal_requests_retention",
        table_name="billing_withdrawal_requests",
    )
    op.drop_index(
        "ix_billing_withdrawal_requests_status_submitted",
        table_name="billing_withdrawal_requests",
    )
    op.drop_index(
        "ix_billing_withdrawal_requests_purchase_id",
        table_name="billing_withdrawal_requests",
    )
    op.drop_table("billing_withdrawal_requests")

    op.drop_index(
        "ix_billing_contract_confirmations_retention",
        table_name="billing_contract_confirmations",
    )
    op.drop_index(
        "ix_billing_contract_confirmations_purchase_id",
        table_name="billing_contract_confirmations",
    )
    op.drop_table("billing_contract_confirmations")
