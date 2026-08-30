"""Shared durable financial-record setup for GDPR tests."""

import time
import uuid

from backend.app.core.database import Database
from backend.app.db.models import DbBillingInvoice, DbCreditPurchase, DbCreditPurchaseReversal
from backend.app.services.financial_records import financial_retention_deadline

FINANCIAL_RECORDS_NOTICE = (
    "Account and media are permanently deleted; legally required financial records are retained in detached form."
)


def seed_financial_record(*, user_id: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex
    now = int(time.time())
    purchase_id = suffix[:32]
    invoice_id = uuid.uuid4().hex
    purchase = DbCreditPurchase(
        id=purchase_id,
        user_id=user_id,
        provider="stripe",
        package_key="creator",
        credits=350,
        amount_eur_cents=300,
        currency="eur",
        idempotency_key=f"gdpr-export-{suffix}",
        checkout_session_id=f"cs_test_{suffix}",
        checkout_url=None,
        payment_intent_id=f"pi_{suffix}",
        integration_identifier="gsubs_credits_v1",
        status="paid",
        fulfilled_at=now,
        refunded_amount_cents=0,
        dispute_active=False,
        reversed_credits=0,
        reversal_debt_credits=0,
        reversed_amount_cents=0,
        snapshot={
            "catalog_version": "test",
            "package_key": "creator",
            "credits": 350,
            "amount_eur_cents": 300,
            "currency": "eur",
        },
        payment_snapshot={
            "checkout_session_id": f"cs_test_{suffix}",
            "payment_intent_id": f"pi_{suffix}",
            "amount_paid_cents": 300,
            "currency": "eur",
        },
        customer_snapshot={
            "name": "GDPR Customer",
            "email": "gdpr-customer@example.com",
            "country": "GR",
        },
        tax_snapshot={
            "tax_behavior": "inclusive",
            "vat_rate_percent": 24,
            "vat_amount_cents": 58,
        },
        financial_retention_until=financial_retention_deadline(now),
        error=None,
        created_at=now,
        updated_at=now,
    )
    invoice = DbBillingInvoice(
        id=invoice_id,
        purchase_id=purchase_id,
        provider="aade_etimologio",
        document_kind="retail_service_receipt",
        document_status="issued",
        aade_document_type="11.2",
        aade_series="0",
        aade_aa=suffix[:12],
        aade_mark=f"4{suffix[:15]}",
        issued_at=now,
        recorded_by_user_id=user_id,
        recorded_at=now,
        document_snapshot={
            "service_code": "4",
            "service_name": "GSUBS Credits",
            "gross_amount_cents": 300,
        },
        financial_retention_until=financial_retention_deadline(now),
        created_at=now,
        updated_at=now,
    )
    db = Database()
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)
    return purchase_id, invoice_id


def seed_unpaid_attempt(*, user_id: str, status: str) -> str:
    suffix = uuid.uuid4().hex
    now = int(time.time())
    purchase = DbCreditPurchase(
        id=suffix[:32],
        user_id=user_id,
        provider="stripe",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        idempotency_key=f"gdpr-unpaid-{suffix}",
        checkout_session_id=f"cs_test_{suffix}",
        checkout_url=f"https://checkout.stripe.com/c/pay/{suffix}",
        payment_intent_id=None,
        integration_identifier="gsubs_credits_v1",
        status=status,
        fulfilled_at=None,
        refunded_amount_cents=0,
        dispute_active=False,
        reversed_credits=0,
        reversal_debt_credits=0,
        reversed_amount_cents=0,
        snapshot={
            "package_key": "starter",
            "credits": 100,
            "amount_eur_cents": 100,
            "currency": "eur",
        },
        payment_snapshot=None,
        customer_snapshot=None,
        tax_snapshot=None,
        financial_retention_until=now + 86_400,
        error=None,
        created_at=now,
        updated_at=now,
    )
    db = Database()
    with db.session() as session:
        session.add(purchase)
    return purchase.id


def seed_reversal_history(
    *,
    purchase_id: str,
) -> list[dict[str, object]]:
    suffix = uuid.uuid4().hex
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        event_created = int(purchase.created_at) + 1
        purchase.refunded_amount_cents = 100
        purchase.dispute_active = True
        purchase.reversed_amount_cents = 300
        purchase.reversed_credits = 350
        purchase.reversal_debt_credits = 50
        purchase.status = "disputed"
        purchase.updated_at = event_created + 1

        refund = DbCreditPurchaseReversal(
            id=uuid.uuid4().hex,
            purchase_id=purchase_id,
            provider="stripe",
            provider_reversal_id=f"re_{suffix}",
            provider_event_id=f"evt_refund_{suffix}",
            provider_event_created=event_created,
            kind="refund",
            amount_cents=100,
            currency="eur",
            status="succeeded",
            active=True,
            created_at=event_created,
            updated_at=event_created,
        )
        dispute = DbCreditPurchaseReversal(
            id=uuid.uuid4().hex,
            purchase_id=purchase_id,
            provider="stripe",
            provider_reversal_id=f"dp_{suffix}",
            provider_event_id=f"evt_dispute_{suffix}",
            provider_event_created=event_created + 1,
            kind="dispute",
            amount_cents=200,
            currency="eur",
            status="needs_response",
            active=True,
            created_at=event_created + 1,
            updated_at=event_created + 1,
        )
        session.add_all((refund, dispute))

    return [
        {
            "id": refund.id,
            "purchase_id": purchase_id,
            "provider": "stripe",
            "provider_reversal_id": refund.provider_reversal_id,
            "provider_event_id": refund.provider_event_id,
            "provider_event_created": event_created,
            "kind": "refund",
            "amount_cents": 100,
            "currency": "eur",
            "status": "succeeded",
            "active": True,
            "created_at": event_created,
            "updated_at": event_created,
        },
        {
            "id": dispute.id,
            "purchase_id": purchase_id,
            "provider": "stripe",
            "provider_reversal_id": dispute.provider_reversal_id,
            "provider_event_id": dispute.provider_event_id,
            "provider_event_created": event_created + 1,
            "kind": "dispute",
            "amount_cents": 200,
            "currency": "eur",
            "status": "needs_response",
            "active": True,
            "created_at": event_created + 1,
            "updated_at": event_created + 1,
        },
    ]
