from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
)
from backend.app.services.billing import (
    BillingValidationError,
)
from backend.app.services.billing_records import (
    build_paid_financial_record,
)
from backend.tests.services.billing_snapshots_test_support import (
    _create_checkout,
    _detached_purchase_for_record_tests,
    _paid_checkout_event,
)
from backend.tests.services.billing_snapshots_test_support import (
    billing_settings as billing_settings,
)
from backend.tests.services.billing_test_support import (
    _process,
    _purchase,
    _service,
)


def test_incomplete_billing_details_grant_paid_credits_but_flag_manual_review(
    billing_settings: None,
) -> None:
    db, user_id, points, _, service = _service()
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    incomplete = {
        "name": None,
        "email": f"{user_id}@example.com",
        "address": {
            "country": "GR",
            "city": None,
            "postal_code": None,
            "line1": None,
            "line2": None,
            "state": None,
        },
        "tax_ids": [],
    }

    assert (
        _process(
            service,
            _paid_checkout_event(purchase, customer_details=incomplete),
        )
        == "processed"
    )

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        assert stored is not None
        assert invoice is not None
        assert stored.customer_snapshot is not None
        assert stored.customer_snapshot["status"] == "manual_review_required"
        assert stored.customer_snapshot["missing_required_fields"] == [
            "name",
            "line1",
            "city",
            "postal_code",
        ]
        assert invoice.document_status == "manual_review_required"

    assert points.get_balances(user_id).paid_balance == 100


def test_non_greek_signed_billing_country_fails_closed_without_credits(
    billing_settings: None,
) -> None:
    # REGRESSION: a client-side Greece acknowledgement alone cannot prove the
    # signed Stripe billing address used for the actual payment.
    db, user_id, points, gateway, service = _service()
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)
    non_greek_details = {
        "name": "Billing Person",
        "email": f"{user_id}@example.com",
        "address": {
            "country": "CY",
            "city": "Nicosia",
            "postal_code": "1010",
            "line1": "Test Street 1",
            "line2": None,
            "state": None,
        },
        "tax_ids": [],
    }

    payload = _paid_checkout_event(
        purchase,
        customer_details=non_greek_details,
    )
    assert (
        _process(
            service,
            payload,
        )
        == "processed"
    )
    assert _process(service, payload) == "duplicate"
    assert gateway.capture_calls == []
    assert gateway.cancel_calls == [
        (
            f"pi_{purchase.id}",
            f"gsubs-cancel-{purchase.id}",
        )
    ]

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        assert stored is not None
        assert stored.fulfilled_at is None
        assert stored.status == "failed"
        assert stored.payment_intent_id is None
        assert stored.payment_snapshot is None
        assert (
            session.scalar(
                select(DbBillingInvoice).where(
                    DbBillingInvoice.purchase_id == purchase.id,
                )
            )
            is None
        )
    assert points.get_balances(user_id).paid_balance == 0


def test_manual_tax_workflow_rejects_unexpected_automatic_tax_checkout(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service = _service()
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)

    assert (
        _process(
            service,
            _paid_checkout_event(
                purchase,
                automatic_tax={"enabled": True, "status": "complete"},
                stripe_amount_tax_cents=19,
            ),
        )
        == "processed"
    )
    assert gateway.capture_calls == []
    assert gateway.cancel_calls == [
        (
            f"pi_{purchase.id}",
            f"gsubs-cancel-{purchase.id}",
        )
    ]

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        assert stored is not None
        assert stored.fulfilled_at is None
        assert stored.payment_snapshot is None
        assert invoice is None
    assert points.get_balances(user_id).paid_balance == 0


def test_manual_tax_workflow_rejects_nonzero_stripe_tax_total(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service = _service()
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)

    assert (
        _process(
            service,
            _paid_checkout_event(
                purchase,
                automatic_tax={"enabled": False, "status": None},
                stripe_amount_tax_cents=1,
            ),
        )
        == "processed"
    )

    assert gateway.capture_calls == []
    assert gateway.cancel_calls == [
        (
            f"pi_{purchase.id}",
            f"gsubs-cancel-{purchase.id}",
        )
    ]
    assert points.get_balances(user_id).paid_balance == 0


@pytest.mark.parametrize("invalid_tax_total", [True, -1, "0", "not-a-number"])
def test_financial_record_rejects_malformed_stripe_tax_total(
    invalid_tax_total: Any,
) -> None:
    purchase = _detached_purchase_for_record_tests()
    checkout = json.loads(
        _paid_checkout_event(
            purchase,
            stripe_amount_tax_cents=invalid_tax_total,
        )
    )["data"]["object"]

    with pytest.raises(ValueError, match="Stripe tax total is invalid"):
        build_paid_financial_record(
            purchase=purchase,
            checkout=checkout,
            stripe_event_created=1_767_225_600,
            livemode=False,
        )


@pytest.mark.parametrize("invalid_tax_total", [True, -1, "0", "not-a-number"])
def test_manual_tax_workflow_rejects_malformed_stripe_tax_total(
    billing_settings: None,
    invalid_tax_total: Any,
) -> None:
    # REGRESSION: malformed and negative Stripe tax totals were normalized to
    # None, allowing fulfillment to continue with incomplete tax evidence.
    db, user_id, points, _, service = _service()
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)

    with pytest.raises(BillingValidationError, match="Stripe tax total is invalid"):
        _process(
            service,
            _paid_checkout_event(
                purchase,
                stripe_amount_tax_cents=invalid_tax_total,
            ),
        )

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        assert stored is not None
        assert stored.fulfilled_at is None
        assert stored.tax_snapshot is None
        assert invoice is None
    assert points.get_balances(user_id).paid_balance == 0
