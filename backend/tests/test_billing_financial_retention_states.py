from __future__ import annotations

import time
import uuid

import pytest

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_retention import cleanup_expired_billing_records
from backend.tests.billing_financial_retention_support import (
    REFERENCE_AT,
    _invoice,
    _purchase,
    _seed_user,
)


@pytest.mark.parametrize(
    ("invoice_status", "dispute_active"),
    (
        ("pending_manual_issue", False),
        ("cancelled", False),
        ("issued", True),
    ),
)
def test_cleanup_keeps_expired_financial_record_with_compliance_hold(
    invoice_status: str,
    dispute_active: bool,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    purchase.dispute_active = dispute_active
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status=invoice_status,
    )
    deadline = REFERENCE_AT + 100
    purchase.financial_retention_until = deadline
    invoice.financial_retention_until = deadline
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)

    report = cleanup_expired_billing_records(db, now=deadline + 1)

    assert report.deleted_financial_records == 0
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is not None
        assert session.get(DbBillingInvoice, invoice.id) is not None


def test_cleanup_keeps_active_dispute_when_purchase_aggregate_is_stale() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    purchase.dispute_active = False
    invoice = _invoice(purchase_id=purchase.id)
    reversal = DbCreditPurchaseReversal(
        id=uuid.uuid4().hex,
        purchase_id=purchase.id,
        provider="stripe",
        provider_reversal_id=f"dp_{uuid.uuid4().hex}",
        provider_event_id=f"evt_{uuid.uuid4().hex}",
        provider_event_created=REFERENCE_AT,
        kind="dispute",
        amount_cents=100,
        currency="eur",
        status="needs_response",
        active=True,
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add_all((invoice, reversal))
    with db.session() as session:
        persisted_purchase = session.get(DbCreditPurchase, purchase.id)
        persisted_invoice = session.get(DbBillingInvoice, invoice.id)
        assert persisted_purchase is not None
        assert persisted_invoice is not None
        cleanup_at = (
            max(
                persisted_purchase.financial_retention_until,
                persisted_invoice.financial_retention_until,
            )
            + 1
        )

    report = cleanup_expired_billing_records(db, now=cleanup_at)

    assert report.deleted_financial_records == 0
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is not None
        assert session.get(DbBillingInvoice, invoice.id) is not None
        assert session.get(DbCreditPurchaseReversal, reversal.id) is not None


@pytest.mark.parametrize(
    "extended_record",
    ("purchase", "invoice"),
)
def test_cleanup_requires_both_financial_retention_deadlines_to_expire(
    extended_record: str,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)
    with db.session() as session:
        persisted_purchase = session.get(DbCreditPurchase, purchase.id)
        persisted_invoice = session.get(DbBillingInvoice, invoice.id)
        assert persisted_purchase is not None
        assert persisted_invoice is not None
        first_deadline = max(
            persisted_purchase.financial_retention_until,
            persisted_invoice.financial_retention_until,
        )
        extended_deadline = first_deadline + 100
        if extended_record == "purchase":
            persisted_purchase.financial_retention_until = extended_deadline
        else:
            persisted_invoice.financial_retention_until = extended_deadline

    first_report = cleanup_expired_billing_records(
        db,
        now=first_deadline + 1,
    )
    assert first_report.deleted_financial_records == 0
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is not None
        assert session.get(DbBillingInvoice, invoice.id) is not None

    second_report = cleanup_expired_billing_records(
        db,
        now=extended_deadline + 1,
    )
    assert second_report.deleted_financial_records >= 1
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is None
        assert session.get(DbBillingInvoice, invoice.id) is None


@pytest.mark.parametrize(
    ("refund_status", "active", "should_keep"),
    (
        ("pending", True, True),
        ("requires_action", True, True),
        ("succeeded", True, False),
        ("pending", False, False),
        ("requires_action", False, False),
        ("failed", False, False),
        ("canceled", False, False),
    ),
)
def test_cleanup_preserves_active_refunds_and_removes_only_inactive_states(
    refund_status: str,
    active: bool,
    should_keep: bool,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    reversal = DbCreditPurchaseReversal(
        id=uuid.uuid4().hex,
        purchase_id=purchase.id,
        provider="stripe",
        provider_reversal_id=f"re_{uuid.uuid4().hex}",
        provider_event_id=f"evt_{uuid.uuid4().hex}",
        provider_event_created=REFERENCE_AT,
        kind="refund",
        amount_cents=40,
        currency="eur",
        status=refund_status,
        active=active,
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)
        session.add(reversal)
    with db.session() as session:
        persisted_purchase = session.get(DbCreditPurchase, purchase.id)
        persisted_invoice = session.get(DbBillingInvoice, invoice.id)
        assert persisted_purchase is not None
        assert persisted_invoice is not None
        persisted_deadline = max(
            persisted_purchase.financial_retention_until,
            persisted_invoice.financial_retention_until,
        )

    report = cleanup_expired_billing_records(
        db,
        now=persisted_deadline + 1,
    )

    with db.session() as session:
        retained_purchase = session.get(DbCreditPurchase, purchase.id)
        retained_invoice = session.get(DbBillingInvoice, invoice.id)
        retained_reversal = session.get(
            DbCreditPurchaseReversal,
            reversal.id,
        )
    assert (retained_purchase is not None) is should_keep
    assert (retained_invoice is not None) is should_keep
    assert (retained_reversal is not None) is should_keep
    if not should_keep:
        assert report.deleted_financial_records >= 1


def test_cleanup_preserves_reversal_until_its_own_statutory_deadline() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    late_reversal_at = int(time.time())
    reversal = DbCreditPurchaseReversal(
        id=uuid.uuid4().hex,
        purchase_id=purchase.id,
        provider="stripe",
        provider_reversal_id=f"re_{uuid.uuid4().hex}",
        provider_event_id=f"evt_{uuid.uuid4().hex}",
        provider_event_created=late_reversal_at,
        kind="refund",
        amount_cents=40,
        currency="eur",
        status="failed",
        active=False,
        created_at=late_reversal_at,
        updated_at=late_reversal_at,
    )
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add_all((invoice, reversal))
    with db.session() as session:
        persisted_purchase = session.get(DbCreditPurchase, purchase.id)
        persisted_invoice = session.get(DbBillingInvoice, invoice.id)
        assert persisted_purchase is not None
        assert persisted_invoice is not None
        expired_parent_cutoff = (
            max(
                persisted_purchase.financial_retention_until,
                persisted_invoice.financial_retention_until,
            )
            + 1
        )

    # REGRESSION: a direct/buggy reversal insert may carry a later provider
    # timestamp than its parent records. Cleanup must skip the whole graph
    # instead of reaching the DELETE trigger and rolling the transaction back.
    report = cleanup_expired_billing_records(
        db,
        now=expired_parent_cutoff,
    )

    assert report.deleted_financial_records == 0
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is not None
        assert session.get(DbBillingInvoice, invoice.id) is not None
        assert session.get(DbCreditPurchaseReversal, reversal.id) is not None
