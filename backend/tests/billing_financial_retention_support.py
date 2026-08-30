from __future__ import annotations

import uuid

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
    DbUser,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    build_consumer_contract_snapshot,
    consumer_contract_snapshot_sha256,
    public_consumer_contract,
)
from backend.app.services.financial_records import financial_retention_deadline

REFERENCE_AT = 1_577_836_800


def _purchase(
    *,
    user_id: str,
    suffix: str | None = None,
) -> DbCreditPurchase:
    resolved_suffix = suffix or uuid.uuid4().hex
    return DbCreditPurchase(
        id=resolved_suffix[:32],
        user_id=user_id,
        provider="stripe",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        idempotency_key=f"billing-{resolved_suffix}"[:64],
        checkout_session_id=f"cs_test_{resolved_suffix}",
        checkout_url=None,
        payment_intent_id=f"pi_{resolved_suffix}",
        integration_identifier=f"gsubs_credits_{resolved_suffix[:8]}",
        status="paid",
        fulfilled_at=REFERENCE_AT,
        refunded_amount_cents=0,
        dispute_active=False,
        reversed_credits=0,
        reversal_debt_credits=0,
        reversed_amount_cents=0,
        snapshot={
            "catalog_version": "test",
            "package_key": "starter",
            "credits": 100,
            "amount_eur_cents": 100,
            "currency": "eur",
        },
        payment_snapshot={
            "checkout_session_id": f"cs_test_{resolved_suffix}",
            "payment_intent_id": f"pi_{resolved_suffix}",
            "paid_amount_cents": 100,
            "currency": "eur",
            "livemode": False,
        },
        customer_snapshot={
            "name": "Accounting Customer",
            "email": f"{resolved_suffix}@example.com",
            "country": "GR",
        },
        tax_snapshot={
            "tax_behavior": "inclusive",
            "tax_rate_basis_points": 2400,
            "automatic_tax": False,
        },
        error=None,
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )


def _invoice(
    *,
    purchase_id: str,
    suffix: str | None = None,
    document_status: str = "issued",
    recorded_by_user_id: str | None = None,
) -> DbBillingInvoice:
    resolved_suffix = suffix or uuid.uuid4().hex
    has_aade_identity = document_status in {"issued", "cancelled"}
    resolved_recorder = recorded_by_user_id or resolved_suffix
    return DbBillingInvoice(
        id=resolved_suffix[:32],
        purchase_id=purchase_id,
        provider="aade_etimologio",
        document_kind="retail_service_receipt",
        document_status=document_status,
        aade_document_type="11.2" if has_aade_identity else None,
        aade_series="0" if has_aade_identity else None,
        aade_aa=resolved_suffix[:12] if has_aade_identity else None,
        aade_mark=f"4{resolved_suffix[:15]}" if has_aade_identity else None,
        issued_at=REFERENCE_AT if has_aade_identity else None,
        recorded_by_user_id=resolved_recorder if has_aade_identity else None,
        recorded_at=REFERENCE_AT if has_aade_identity else None,
        document_snapshot={
            "description": "GSUBS Credits",
            "gross_amount_cents": 100,
            "currency": "eur",
            "tax_behavior": "inclusive",
        },
        financial_retention_until=financial_retention_deadline(REFERENCE_AT),
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )


def _seed_user(db: Database) -> str:
    suffix = uuid.uuid4().hex
    user_id = suffix[:32]
    with db.session() as session:
        session.add(
            DbUser(
                id=user_id,
                email=f"{suffix}@example.com",
                name="Financial Records",
                provider="local",
                password_hash="x",
                google_sub=None,
                avatar_url=None,
                created_at="now",
                email_verified=True,
            )
        )
    return user_id


def _add_consumer_contract_snapshot(
    purchase: DbCreditPurchase,
) -> None:
    disclosure = public_consumer_contract("el")
    consumer_contract = build_consumer_contract_snapshot(
        ConsumerContractAcceptance(
            catalog_version="test",
            disclosure_id=str(disclosure["disclosure_id"]),
            disclosure_sha256=str(disclosure["disclosure_sha256"]),
            locale="el",
            policy_version=str(disclosure["policy_version"]),
            terms_version=str(disclosure["terms_version"]),
            withdrawal_notice_version=str(
                disclosure["withdrawal_notice_version"],
            ),
            terms_accepted=True,
            immediate_performance_requested=True,
            withdrawal_consequences_acknowledged=True,
        ),
        expected_catalog_version="test",
        accepted_at=REFERENCE_AT,
    )
    purchase.snapshot = {
        **purchase.snapshot,
        "consumer_contract": consumer_contract,
        "consumer_contract_sha256": (consumer_contract_snapshot_sha256(consumer_contract)),
    }
