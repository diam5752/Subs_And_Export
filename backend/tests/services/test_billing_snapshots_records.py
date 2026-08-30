from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import select

from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
    DbUser,
    DbUserPoints,
)
from backend.app.services.billing_records import (
    build_paid_financial_record,
)
from backend.app.services.financial_records import (
    financial_retention_deadline,
)
from backend.tests.services.billing_snapshots_test_support import (
    _create_checkout,
    _paid_checkout_event,
)
from backend.tests.services.billing_snapshots_test_support import (
    billing_settings as billing_settings,
)
from backend.tests.services.billing_test_support import (
    _process,
    _purchase,
    _refund_event,
    _service,
)


@pytest.mark.parametrize("invalid_timestamp", [True, 0, -1])
def test_financial_record_rejects_invalid_stripe_event_timestamp(
    billing_settings: None,
    invalid_timestamp: int,
) -> None:
    db, user_id, _, _, service = _service()
    checkout_result = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout_result.purchase_id)
    checkout = json.loads(_paid_checkout_event(purchase))["data"]["object"]

    with pytest.raises(ValueError, match="Stripe event timestamp is invalid"):
        build_paid_financial_record(
            purchase=purchase,
            checkout=checkout,
            stripe_event_created=invalid_timestamp,
            livemode=False,
        )


def test_financial_record_normalizes_expanded_stripe_ids_and_tax_ids(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    checkout_result = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout_result.purchase_id)
    checkout = json.loads(_paid_checkout_event(purchase))["data"]["object"]
    checkout["payment_intent"] = {"id": f"pi_{purchase.id}"}
    checkout["customer"] = {"id": f"cus_{purchase.id}"}
    checkout["customer_details"]["tax_ids"] = [
        None,
        {},
        {"type": " eu_vat ", "value": " EL123456789 "},
        {"type": " ", "value": "ignored"},
    ]

    record = build_paid_financial_record(
        purchase=purchase,
        checkout=checkout,
        stripe_event_created=1_767_225_600,
        livemode=False,
    )

    assert record.payment_snapshot["payment_intent_id"] == f"pi_{purchase.id}"
    assert record.payment_snapshot["stripe_customer_id"] == f"cus_{purchase.id}"
    assert record.tax_snapshot["tax_ids"] == [
        {"type": "eu_vat", "value": "EL123456789"},
    ]


def test_financial_record_handles_optional_absent_stripe_fields(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    checkout_result = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout_result.purchase_id)
    checkout = json.loads(_paid_checkout_event(purchase))["data"]["object"]
    checkout["payment_intent"] = 123
    checkout["customer"] = None
    checkout.pop("total_details")
    checkout["customer_details"]["tax_ids"] = {"unexpected": "mapping"}

    record = build_paid_financial_record(
        purchase=purchase,
        checkout=checkout,
        stripe_event_created=1_767_225_600,
        livemode=False,
    )

    assert record.payment_snapshot["payment_intent_id"] == ""
    assert record.payment_snapshot["stripe_customer_id"] == ""
    assert record.tax_snapshot["stripe_amount_tax_cents"] is None
    assert record.tax_snapshot["tax_ids"] == []


def test_financial_record_rejects_nonpositive_purchase_amount(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    checkout_result = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout_result.purchase_id)
    checkout = json.loads(_paid_checkout_event(purchase))["data"]["object"]
    purchase.amount_eur_cents = 0

    with pytest.raises(ValueError, match="Gross amount and VAT rate must be positive"):
        build_paid_financial_record(
            purchase=purchase,
            checkout=checkout,
            stripe_event_created=1_767_225_600,
            livemode=False,
        )


def test_paid_checkout_after_account_deletion_is_retained_without_credit_grant(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    with db.session() as session:
        user = session.get(DbUser, user_id)
        assert user is not None
        session.delete(user)

    detached = _purchase(db, purchase.id)
    assert detached.user_id is None
    assert (
        _process(
            service,
            _paid_checkout_event(
                detached,
                account_user_id=user_id,
            ),
        )
        == "processed"
    )

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        assert stored is not None
        assert stored.user_id is None
        assert stored.fulfilled_at is not None
        assert stored.status == "manual_review_account_deleted"
        assert stored.payment_snapshot is not None
        assert stored.payment_snapshot["amount_paid_cents"] == 100
        assert invoice is not None
        assert invoice.aade_mark is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None
        assert session.get(DbUserPoints, user_id) is None


def test_later_refund_extends_purchase_and_invoice_retention(
    billing_settings: None,
) -> None:
    db, user_id, _, _, service = _service()
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    paid_at = 1_767_225_600
    assert (
        _process(
            service,
            _paid_checkout_event(purchase, created=paid_at),
        )
        == "processed"
    )
    stored = _purchase(db, purchase.id)
    refund_at = 1_798_761_600

    assert (
        _process(
            service,
            _refund_event(stored, created=refund_at),
        )
        == "processed"
    )

    with db.session() as session:
        retained = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        expected = financial_retention_deadline(refund_at)
        assert retained is not None
        assert invoice is not None
        assert retained.financial_retention_until == expected
        assert invoice.financial_retention_until == expected
