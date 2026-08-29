from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import event, select

from backend.app.core import config
from backend.app.db.models import (
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbCreditPurchase,
    DbPointTransaction,
    DbUser,
    DbUserPoints,
)
from backend.app.services import billing as billing_module
from backend.app.services.billing import (
    CATALOG_VERSION,
    BillingConflictError,
    BillingService,
    BillingValidationError,
    CheckoutResult,
)
from backend.app.services.billing_records import (
    MANUAL_CAPTURE_POLICY,
    PaidFinancialRecord,
    PaymentCaptureEvidence,
    build_paid_financial_record,
    new_pending_invoice,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    public_consumer_contract,
)
from backend.app.services.financial_records import (
    financial_account_reference_hash,
    financial_retention_deadline,
)
from backend.app.services.points import make_idempotency_id
from backend.tests.services.test_billing import (
    _process,
    _purchase,
    _refund_event,
    _service,
)


@pytest.fixture
def billing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config.settings, "app_env", config.AppEnv.DEV)
    monkeypatch.setattr(config.settings, "paid_credits_enabled", True)
    monkeypatch.setattr(config.settings, "consumer_policy_approved", True)
    monkeypatch.setattr(config.settings, "durable_confirmation_channel_ready", True)
    monkeypatch.setattr(config.settings, "adjustment_workflow_ready", True)
    monkeypatch.setattr(config.settings, "stripe_price_starter", "price_test_starter")
    monkeypatch.setattr(config.settings, "stripe_price_core", "price_test_core")
    monkeypatch.setattr(config.settings, "stripe_price_pro", "price_test_pro")
    monkeypatch.setattr(
        billing_module,
        "consumer_contract_registry_is_approved",
        lambda: True,
    )


def _canonical_consumer_acceptance(
    locale: str = "el",
) -> ConsumerContractAcceptance:
    disclosure = public_consumer_contract(locale)
    return ConsumerContractAcceptance(
        catalog_version=CATALOG_VERSION,
        disclosure_id=str(disclosure["disclosure_id"]),
        disclosure_sha256=str(disclosure["disclosure_sha256"]),
        locale=locale,  # type: ignore[arg-type]
        policy_version=str(disclosure["policy_version"]),
        terms_version=str(disclosure["terms_version"]),
        withdrawal_notice_version=str(
            disclosure["withdrawal_notice_version"],
        ),
        terms_accepted=True,
        immediate_performance_requested=True,
        withdrawal_consequences_acknowledged=True,
    )


def _create_checkout(
    service: BillingService,
    *,
    user_id: str,
    customer_email: str,
    package_key: str,
    idempotency_key: str,
) -> CheckoutResult:
    return service.create_checkout(
        user_id=user_id,
        customer_email=customer_email,
        package_key=package_key,
        idempotency_key=idempotency_key,
        consumer_contract=_canonical_consumer_acceptance(),
    )


def _paid_checkout_event(
    purchase: DbCreditPurchase,
    *,
    created: int = 1_767_225_600,
    customer_details: dict[str, Any] | None = None,
    automatic_tax: dict[str, Any] | None = None,
    stripe_amount_tax_cents: Any = 0,
    account_user_id: str | None = None,
) -> bytes:
    checkout_user_id = account_user_id or purchase.user_id
    consumer_contract = purchase.snapshot.get("consumer_contract") if isinstance(purchase.snapshot, dict) else None
    consumer_metadata = (
        {
            "consumer_disclosure_id": str(
                consumer_contract.get("disclosure_id") or "",
            ),
            "consumer_disclosure_sha256": str(
                consumer_contract.get("disclosure_sha256") or "",
            ),
            "consumer_contract_sha256": str(
                purchase.snapshot.get("consumer_contract_sha256") or "",
            ),
            "consumer_locale": str(consumer_contract.get("locale") or ""),
        }
        if isinstance(consumer_contract, dict)
        else {"consumer_contract_sha256": ""}
    )
    details = customer_details or {
        "name": "Billing Person",
        "email": "billing.person@example.com",
        "address": {
            "country": "GR",
            "city": "Athens",
            "postal_code": "105 58",
            "line1": "Test Street 1",
            "line2": None,
            "state": "Attica",
        },
        "tax_ids": [],
    }
    payload = {
        "id": f"evt_{uuid.uuid4().hex}",
        "created": created,
        "livemode": False,
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": purchase.checkout_session_id,
                "payment_status": "unpaid",
                "status": "complete",
                "amount_total": purchase.amount_eur_cents,
                "currency": purchase.currency,
                "client_reference_id": checkout_user_id,
                "customer": f"cus_{purchase.id}",
                "customer_details": details,
                "automatic_tax": automatic_tax or {"enabled": False, "status": None},
                "total_details": {"amount_tax": stripe_amount_tax_cents},
                "payment_intent": f"pi_{purchase.id}",
                "metadata": {
                    "purchase_id": purchase.id,
                    "user_id": checkout_user_id,
                    "package_key": purchase.package_key,
                    "credits": str(purchase.credits),
                    "integration_identifier": purchase.integration_identifier,
                    "catalog_version": purchase.snapshot["catalog_version"],
                    "billing_country": purchase.snapshot["billing_country"],
                    "capture_policy": purchase.snapshot["capture_policy"],
                    **consumer_metadata,
                },
            }
        },
    }
    return json.dumps(payload, sort_keys=True).encode()


def _financial_record_for_event(
    purchase: DbCreditPurchase,
    payload: bytes,
) -> PaidFinancialRecord:
    event = json.loads(payload)
    payment_intent_id = f"pi_{purchase.id}"
    return build_paid_financial_record(
        purchase=purchase,
        checkout=event["data"]["object"],
        stripe_event_created=event["created"],
        livemode=event["livemode"],
        capture_evidence=PaymentCaptureEvidence(
            payment_intent_id=payment_intent_id,
            status="succeeded",
            amount_cents=purchase.amount_eur_cents,
            amount_received_cents=purchase.amount_eur_cents,
            currency=purchase.currency,
            capture_method="manual",
            capture_policy=MANUAL_CAPTURE_POLICY,
        ),
    )


def _detached_purchase_for_record_tests() -> DbCreditPurchase:
    purchase_id = uuid.uuid4().hex
    return DbCreditPurchase(
        id=purchase_id,
        user_id="record-test-user",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        checkout_session_id=f"cs_test_{purchase_id}",
        integration_identifier="gsubs_credits_snapshot",
        snapshot={
            "catalog_version": "2026-07-23-v1",
            "billing_country": "GR",
            "capture_policy": MANUAL_CAPTURE_POLICY,
        },
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
