from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import event, select

from backend.app.db.models import (
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbCreditPurchase,
    DbPointTransaction,
)
from backend.app.services.billing import (
    BillingConflictError,
)
from backend.app.services.billing_records import (
    MANUAL_CAPTURE_POLICY,
    new_pending_invoice,
)
from backend.app.services.financial_records import (
    financial_account_reference_hash,
)
from backend.app.services.points import make_idempotency_id
from backend.tests.services.billing_snapshots_test_support import (
    _create_checkout,
    _financial_record_for_event,
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


def test_paid_checkout_persists_immutable_financial_snapshots_and_pending_aade_record(
    billing_settings: None,
) -> None:
    db, user_id, points, gateway, service = _service()
    gateway.amount_total = 300
    checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="core",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    purchase = _purchase(db, checkout.purchase_id)

    assert purchase.account_reference_hash == financial_account_reference_hash(user_id)
    assert _process(service, _paid_checkout_event(purchase)) == "processed"

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        confirmation = session.scalar(
            select(DbBillingContractConfirmation)
            .where(DbBillingContractConfirmation.purchase_id == purchase.id)
            .limit(1)
        )
        assert stored is not None
        assert invoice is not None
        assert confirmation is not None

        assert stored.payment_snapshot == {
            "source": "stripe_checkout_session",
            "checkout_session_id": purchase.checkout_session_id,
            "payment_intent_id": f"pi_{purchase.id}",
            "stripe_customer_id": f"cus_{purchase.id}",
            "stripe_event_created": 1_767_225_600,
            "livemode": False,
            "amount_paid_cents": 300,
            "currency": "eur",
            "payment_status": "unpaid",
            "capture_method": "manual",
            "capture_policy": MANUAL_CAPTURE_POLICY,
            "capture_status": "succeeded",
            "payment_intent_amount_cents": 300,
            "payment_intent_amount_received_cents": 300,
        }
        assert stored.customer_snapshot == {
            "source": "stripe_checkout_session",
            "customer_type": "individual",
            "name": "Billing Person",
            "email": "billing.person@example.com",
            "country": "GR",
            "city": "Athens",
            "postal_code": "105 58",
            "line1": "Test Street 1",
            "line2": None,
            "state": "Attica",
            "missing_required_fields": [],
            "status": "ready_for_manual_issue",
        }
        assert stored.tax_snapshot == {
            "accounting_method": "manual_aade_etimologio",
            "customer_type": "individual",
            "tax_id_collection": "not_requested",
            "tax_ids": [],
            "automatic_tax_enabled": False,
            "automatic_tax_status": None,
            "stripe_amount_tax_cents": 0,
            "stripe_product_tax_code": "txcd_10103001",
            "tax_behavior": "inclusive",
            "vat_rate_percent": 24,
            "gross_amount_cents": 300,
            "net_amount_cents": 242,
            "vat_amount_cents": 58,
        }
        assert stored.financial_retention_until == 1_956_520_799

        assert invoice.provider == "aade_etimologio"
        assert invoice.document_kind == "retail_service_receipt"
        assert invoice.document_status == "pending_manual_issue"
        assert invoice.aade_document_type is None
        assert invoice.aade_series is None
        assert invoice.aade_aa is None
        assert invoice.aade_mark is None
        assert invoice.issued_at is None
        assert invoice.recorded_by_user_id is None
        assert invoice.recorded_at is None
        assert invoice.financial_retention_until == stored.financial_retention_until
        assert invoice.document_snapshot == {
            "service_code": "4",
            "service_name": "GSUBS Credits",
            "expected_document_type": "11.2",
            "expected_series": "0",
            "expected_payment_method": "domestic_professional_payment_account",
            "package_key": "core",
            "credits": 350,
            "currency": "eur",
            "gross_amount_cents": 300,
            "net_amount_cents": 242,
            "vat_rate_percent": 24,
            "vat_amount_cents": 58,
            "customer_status": "ready_for_manual_issue",
            "source_purchase_id": purchase.id,
        }
        confirmation_content = json.loads(confirmation.content_bytes)
        assert confirmation_content["purchase"]["purchase_id"] == purchase.id
        assert confirmation_content["consumer_contract_sha256"] == purchase.snapshot["consumer_contract_sha256"]
        # A delayed webhook concludes the contract at the validated provider
        # event time, but availability/creation records the later server receipt
        # time rather than claiming retroactive delivery.
        assert confirmation.contract_concluded_at == 1_767_225_600
        assert confirmation.available_at > confirmation.contract_concluded_at
        assert confirmation.created_at == confirmation.available_at
        assert confirmation_content["available_at"] == confirmation.available_at

    assert points.get_balances(user_id).paid_balance == 350


@pytest.mark.parametrize(
    ("snapshot_name", "field_name", "conflicting_value"),
    [
        ("payment_snapshot", "payment_status", "conflicting"),
        ("customer_snapshot", "name", "Conflicting Customer"),
        ("tax_snapshot", "vat_rate_percent", 0),
    ],
)
def test_fulfillment_rejects_conflicting_preexisting_financial_snapshots_before_credit(
    billing_settings: None,
    snapshot_name: str,
    field_name: str,
    conflicting_value: Any,
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
    payload = _paid_checkout_event(purchase)
    record = _financial_record_for_event(purchase, payload)
    snapshots = {
        "payment_snapshot": dict(record.payment_snapshot),
        "customer_snapshot": dict(record.customer_snapshot),
        "tax_snapshot": dict(record.tax_snapshot),
    }
    snapshots[snapshot_name][field_name] = conflicting_value

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        assert stored is not None
        stored.payment_snapshot = snapshots["payment_snapshot"]
        stored.customer_snapshot = snapshots["customer_snapshot"]
        stored.tax_snapshot = snapshots["tax_snapshot"]

    with pytest.raises(
        BillingConflictError,
        match="financial snapshots conflict with signed Checkout evidence",
    ):
        _process(service, payload)

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        confirmation = session.scalar(
            select(DbBillingContractConfirmation)
            .where(
                DbBillingContractConfirmation.purchase_id == purchase.id,
            )
            .limit(1)
        )
        assert stored is not None
        assert stored.fulfilled_at is None
        assert stored.status == "checkout_created"
        assert invoice is None
        assert confirmation is None
        assert (
            session.get(
                DbPointTransaction,
                make_idempotency_id("stripe", "purchase", purchase.id),
            )
            is None
        )
    assert points.get_balances(user_id).paid_balance == 0


@pytest.mark.parametrize(
    "conflicting_field",
    [
        "id",
        "purchase_id",
        "provider",
        "document_kind",
        "document_status",
        "aade_document_type",
        "aade_series",
        "aade_aa",
        "aade_mark",
        "issued_at",
        "recorded_by_user_id",
        "recorded_at",
        "document_snapshot",
        "financial_retention_until",
        "created_at",
        "updated_at",
    ],
)
def test_fulfillment_rejects_conflicting_preexisting_invoice_before_credit(
    billing_settings: None,
    conflicting_field: str,
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
    payload = _paid_checkout_event(purchase)
    record = _financial_record_for_event(purchase, payload)
    invoice = new_pending_invoice(
        purchase_id=purchase.id,
        record=record,
        created_at=1_767_225_600,
    )
    alternate_checkout = _create_checkout(
        service,
        user_id=user_id,
        customer_email=f"{user_id}@example.com",
        package_key="starter",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
    )
    conflicting_id = uuid.uuid4().hex
    assert conflicting_id != invoice.id
    conflicting_values: dict[str, Any] = {
        "id": conflicting_id,
        "purchase_id": alternate_checkout.purchase_id,
        "provider": "conflicting_provider",
        "document_kind": "conflicting_document",
        "document_status": "manual_review_required",
        "aade_document_type": "11.2",
        "aade_series": f"test-{uuid.uuid4().hex[:8]}",
        "aade_aa": f"test-{uuid.uuid4().hex[:8]}",
        "aade_mark": f"test-{uuid.uuid4().hex}",
        "issued_at": 1_767_225_601,
        "recorded_by_user_id": uuid.uuid4().hex,
        "recorded_at": 1_767_225_601,
        "document_snapshot": {"conflicting": True},
        "financial_retention_until": (invoice.financial_retention_until + 1),
        "created_at": invoice.created_at + 1,
        "updated_at": invoice.updated_at + 1,
    }
    conflicting_value = conflicting_values[conflicting_field]
    load_only_conflicts = {
        "aade_document_type",
        "aade_series",
        "aade_aa",
        "aade_mark",
        "issued_at",
        "recorded_by_user_id",
        "recorded_at",
    }
    if conflicting_field not in load_only_conflicts:
        setattr(invoice, conflicting_field, conflicting_value)

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        assert stored is not None
        stored.payment_snapshot = record.payment_snapshot
        stored.customer_snapshot = record.customer_snapshot
        stored.tax_snapshot = record.tax_snapshot
        session.add(invoice)

    def corrupt_loaded_invoice(
        loaded_invoice: DbBillingInvoice,
        _context: Any,
    ) -> None:
        if loaded_invoice.id == invoice.id:
            setattr(
                loaded_invoice,
                conflicting_field,
                conflicting_value,
            )

    if conflicting_field in load_only_conflicts:
        event.listen(DbBillingInvoice, "load", corrupt_loaded_invoice)
    try:
        with pytest.raises(
            BillingConflictError,
            match="invoice conflicts with signed Checkout evidence",
        ):
            _process(service, payload)
    finally:
        if conflicting_field in load_only_conflicts:
            event.remove(
                DbBillingInvoice,
                "load",
                corrupt_loaded_invoice,
            )

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        confirmation = session.scalar(
            select(DbBillingContractConfirmation)
            .where(
                DbBillingContractConfirmation.purchase_id == purchase.id,
            )
            .limit(1)
        )
        assert stored is not None
        assert stored.fulfilled_at is None
        assert stored.status == "checkout_created"
        assert confirmation is None
        assert (
            session.get(
                DbPointTransaction,
                make_idempotency_id("stripe", "purchase", purchase.id),
            )
            is None
        )
    assert points.get_balances(user_id).paid_balance == 0


def test_fulfillment_accepts_exact_preexisting_financial_record(
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
    payload = _paid_checkout_event(purchase)
    record = _financial_record_for_event(purchase, payload)

    with db.session() as session:
        stored = session.get(DbCreditPurchase, purchase.id)
        assert stored is not None
        stored.payment_snapshot = record.payment_snapshot
        stored.customer_snapshot = record.customer_snapshot
        stored.tax_snapshot = record.tax_snapshot
        session.add(
            new_pending_invoice(
                purchase_id=purchase.id,
                record=record,
                created_at=1_767_225_600,
            )
        )

    assert _process(service, payload) == "processed"
    fulfilled = _purchase(db, purchase.id)
    assert fulfilled.fulfilled_at is not None
    assert fulfilled.status == "paid"
    assert points.get_balances(user_id).paid_balance == 100


def test_fulfillment_financial_wallet_and_status_state_rolls_back_and_retries_atomically(
    billing_settings: None,
    monkeypatch: pytest.MonkeyPatch,
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
    payload = _paid_checkout_event(purchase)
    transaction_id = make_idempotency_id(
        "stripe",
        "purchase",
        purchase.id,
    )
    original_apply = points.apply_paid_purchase_once_in_session

    def crash_after_wallet_mutation(
        session: Any,
        user_id_arg: str,
        amount: int,
        *,
        purchase_id: str,
        transaction_id: str,
    ) -> Any:
        original_apply(
            session,
            user_id_arg,
            amount,
            purchase_id=purchase_id,
            transaction_id=transaction_id,
        )
        raise RuntimeError("forced fulfillment transaction rollback")

    monkeypatch.setattr(
        points,
        "apply_paid_purchase_once_in_session",
        crash_after_wallet_mutation,
    )
    with pytest.raises(
        RuntimeError,
        match="forced fulfillment transaction rollback",
    ):
        _process(service, payload)

    with db.session() as session:
        rolled_back = session.get(DbCreditPurchase, purchase.id)
        invoice = session.scalar(select(DbBillingInvoice).where(DbBillingInvoice.purchase_id == purchase.id).limit(1))
        assert rolled_back is not None
        assert rolled_back.status == "checkout_created"
        assert rolled_back.fulfilled_at is None
        assert rolled_back.payment_intent_id is None
        assert rolled_back.payment_snapshot is None
        assert rolled_back.customer_snapshot is None
        assert rolled_back.tax_snapshot is None
        assert invoice is None
        assert (
            session.scalar(
                select(DbBillingContractConfirmation)
                .where(
                    DbBillingContractConfirmation.purchase_id == purchase.id,
                )
                .limit(1)
            )
            is None
        )
        assert session.get(DbPointTransaction, transaction_id) is None
    assert points.get_balances(user_id).paid_balance == 0

    monkeypatch.setattr(
        points,
        "apply_paid_purchase_once_in_session",
        original_apply,
    )
    assert _process(service, payload) == "processed"
    assert _process(service, payload) == "duplicate"

    with db.session() as session:
        fulfilled = session.get(DbCreditPurchase, purchase.id)
        invoices = list(
            session.scalars(
                select(DbBillingInvoice).where(
                    DbBillingInvoice.purchase_id == purchase.id,
                )
            )
        )
        transactions = list(
            session.scalars(
                select(DbPointTransaction).where(
                    DbPointTransaction.id == transaction_id,
                )
            )
        )
        confirmations = list(
            session.scalars(
                select(DbBillingContractConfirmation).where(
                    DbBillingContractConfirmation.purchase_id == purchase.id,
                )
            )
        )
        assert fulfilled is not None
        assert fulfilled.status == "paid"
        assert fulfilled.fulfilled_at is not None
        assert fulfilled.payment_snapshot is not None
        assert len(invoices) == 1
        assert len(transactions) == 1
        assert len(confirmations) == 1
    assert points.get_balances(user_id).paid_balance == 100
