from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from backend.app.core import config
from backend.app.db.models import (
    DbCreditPurchase,
)
from backend.app.services import billing as billing_module
from backend.app.services.billing import (
    CATALOG_VERSION,
    BillingService,
    CheckoutResult,
)
from backend.app.services.billing_records import (
    MANUAL_CAPTURE_POLICY,
    PaidFinancialRecord,
    PaymentCaptureEvidence,
    build_paid_financial_record,
)
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    public_consumer_contract,
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
