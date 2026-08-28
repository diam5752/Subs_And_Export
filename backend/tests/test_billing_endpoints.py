from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.requests import Request

from backend.app.api.endpoints.billing import stripe_webhook
from backend.app.core.auth import SessionStore, User
from backend.app.db.models import (
    DbBillingWithdrawalRequest,
    DbCreditPurchase,
)
from backend.app.services import (
    billing_consumer_records as billing_consumer_records_module,
)
from backend.app.services.billing import (
    CATALOG_VERSION,
    BillingConflictError,
    BillingDisabledError,
    BillingProviderError,
    BillingValidationError,
    WebhookResult,
)
from backend.app.services.billing_consumer_records import new_contract_confirmation
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    build_consumer_contract_snapshot,
    consumer_contract_snapshot_sha256,
    public_consumer_contract,
)
from backend.app.services.financial_records import (
    financial_account_reference_hash,
    financial_retention_deadline,
)


class _RecordingBillingService:
    def __init__(self) -> None:
        self.calls = 0
        self.payload: bytes | None = None
        self.signature: str | None = None

    def verify_and_process_webhook(
        self,
        *,
        payload: bytes,
        signature: str,
    ) -> WebhookResult:
        self.calls += 1
        self.payload = payload
        self.signature = signature
        return WebhookResult(
            event_id="evt_streamed",
            event_type="customer.updated",
            status="ignored",
        )


def _streaming_request(
    chunks: list[bytes],
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[Request, dict[str, int]]:
    state = {"receive_calls": 0}
    pending = list(chunks)

    async def receive() -> dict[str, Any]:
        state["receive_calls"] += 1
        if not pending:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }
        body = pending.pop(0)
        return {
            "type": "http.request",
            "body": body,
            "more_body": bool(pending),
        }

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "https",
        "path": "/billing/webhook",
        "raw_path": b"/billing/webhook",
        "query_string": b"",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("testserver", 443),
    }
    return Request(scope, receive), state


def _checkout_payload(
    client: TestClient,
    *,
    package_key: str = "starter",
    locale: str = "el",
) -> dict[str, Any]:
    catalog_response = client.get(
        "/billing/catalog",
        params={"locale": locale},
    )
    assert catalog_response.status_code == 200
    catalog = catalog_response.json()
    disclosure = catalog["consumer_contract"] or public_consumer_contract(locale)
    return {
        "package_key": package_key,
        "catalog_version": catalog["catalog_version"],
        "billing_country": "GR",
        "consumer_contract": {
            "disclosure_id": disclosure["disclosure_id"],
            "disclosure_sha256": disclosure["disclosure_sha256"],
            "locale": disclosure["locale"],
            "policy_version": disclosure["policy_version"],
            "terms_version": disclosure["terms_version"],
            "withdrawal_notice_version": disclosure["withdrawal_notice_version"],
            "terms_accepted": True,
            "immediate_performance_requested": True,
            "withdrawal_consequences_acknowledged": True,
        },
    }


def test_checkout_rejects_non_greek_or_missing_billing_country(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    payload = _checkout_payload(client)
    non_greek = client.post(
        "/billing/checkout",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"checkout-{uuid.uuid4().hex}",
        },
        json={**payload, "billing_country": "CY"},
    )
    assert non_greek.status_code == 422

    missing = dict(payload)
    missing.pop("billing_country")
    no_country = client.post(
        "/billing/checkout",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"checkout-{uuid.uuid4().hex}",
        },
        json=missing,
    )
    assert no_country.status_code == 422


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


def _authenticated_user(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> tuple[Any, User]:
    database = client.app.state.db  # type: ignore[union-attr]
    token = user_auth_headers["Authorization"].removeprefix("Bearer ")
    user = SessionStore(database).authenticate(token)
    assert user is not None
    return database, user


def _seed_paid_contract_purchase(
    client: TestClient,
    user_auth_headers: dict[str, str],
    *,
    corrupt_record: str | None = None,
    concluded_at: int | None = None,
) -> tuple[str, User]:
    database, user = _authenticated_user(client, user_auth_headers)
    concluded_at = int(time.time()) if concluded_at is None else concluded_at
    purchase_id = uuid.uuid4().hex
    consumer_snapshot = build_consumer_contract_snapshot(
        _canonical_consumer_acceptance(),
        expected_catalog_version=CATALOG_VERSION,
        accepted_at=concluded_at,
    )
    purchase_snapshot = {
        "catalog_version": CATALOG_VERSION,
        "package_key": "starter",
        "credits": 100,
        "amount_eur_cents": 100,
        "currency": "eur",
        "stripe_price_id": "price_test_starter",
        "billing_country": "GR",
        "consumer_contract": consumer_snapshot,
        "consumer_contract_sha256": consumer_contract_snapshot_sha256(
            consumer_snapshot,
        ),
    }
    purchase = DbCreditPurchase(
        id=purchase_id,
        user_id=user.id,
        account_reference_hash=financial_account_reference_hash(user.id),
        provider="stripe",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        idempotency_key=f"checkout-{uuid.uuid4().hex}",
        checkout_session_id=f"cs_test_{purchase_id}",
        checkout_url=None,
        payment_intent_id=f"pi_{purchase_id}",
        integration_identifier="gsubs_credits_api",
        status="paid",
        fulfilled_at=concluded_at,
        refunded_amount_cents=0,
        dispute_active=False,
        reversed_credits=0,
        reversal_debt_credits=0,
        reversed_amount_cents=0,
        snapshot=purchase_snapshot,
        payment_snapshot={"payment_status": "paid"},
        customer_snapshot={"email": user.email},
        tax_snapshot={"accounting_method": "manual_aade_etimologio"},
        financial_retention_until=financial_retention_deadline(
            concluded_at,
        ),
        error=None,
        created_at=concluded_at,
        updated_at=concluded_at,
    )
    with database.session() as session:
        session.add(purchase)
        session.flush()
        confirmation = new_contract_confirmation(
            purchase=purchase,
            contract_concluded_at=concluded_at,
            generated_at=concluded_at,
        )
        if corrupt_record == "confirmation":
            confirmation_document = json.loads(
                confirmation.content_bytes,
            )
            confirmation_document["purchase"]["package_key"] = "pro"
            confirmation.content_bytes = (
                json.dumps(
                    confirmation_document,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n"
            ).encode()
            confirmation.content_sha256 = hashlib.sha256(
                confirmation.content_bytes,
            ).hexdigest()
        session.add(confirmation)
        if corrupt_record == "withdrawal":
            request_snapshot = {"purchase_id": purchase_id}
            request_bytes = (
                json.dumps(
                    request_snapshot,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            ).encode()
            acknowledgement_bytes = b'{"tampered":true}\n'
            session.add(
                DbBillingWithdrawalRequest(
                    id=uuid.uuid4().hex,
                    purchase_id=purchase_id,
                    idempotency_key=f"withdrawal-{uuid.uuid4().hex}",
                    schema_version=1,
                    locale="el",
                    status="pending_manual_review",
                    request_snapshot=request_snapshot,
                    request_bytes=request_bytes,
                    request_sha256=hashlib.sha256(
                        request_bytes,
                    ).hexdigest(),
                    submitted_at=concluded_at,
                    acknowledgement_mime_type=("application/json; charset=utf-8"),
                    acknowledgement_filename=(f"gsubs-withdrawal-{purchase_id}.json"),
                    acknowledgement_bytes=acknowledgement_bytes,
                    acknowledgement_sha256=hashlib.sha256(
                        acknowledgement_bytes,
                    ).hexdigest(),
                    available_at=concluded_at,
                    financial_retention_until=(financial_retention_deadline(concluded_at)),
                    created_at=concluded_at,
                )
            )
    return purchase_id, user


def test_withdrawal_action_stays_available_pending_manual_timeliness_review(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    purchase_id, user = _seed_paid_contract_purchase(
        client,
        user_auth_headers,
        concluded_at=int(time.time()) - (90 * 24 * 60 * 60),
    )

    purchases = client.get(
        "/billing/purchases",
        headers=user_auth_headers,
    )
    purchase = next(item for item in purchases.json() if item["purchase_id"] == purchase_id)
    assert purchase["withdrawal_action_available"] is True
    assert "withdrawal_standard_window_ends_at" not in purchase

    response = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"withdrawal-{uuid.uuid4().hex}",
        },
        json={
            "locale": "el",
            "withdrawal_requested": True,
            "confirmed_name": user.name,
            "confirmation_email": user.email,
        },
    )

    assert response.status_code == 200
    assert response.json()["timeliness_assessment_status"] == ("pending_manual_review")
    assert "within_standard_14_day_window" not in response.json()


def test_credit_catalog_is_public_and_checkout_requires_login(client: TestClient) -> None:
    catalog = client.get("/billing/catalog")
    assert catalog.status_code == 200
    assert [item["credits"] for item in catalog.json()["video_pricing"]] == [25, 60, 100]
    assert catalog.json()["consumer_contract_status"] == "approved"
    assert catalog.json()["consumer_contract"]["status"] == "approved"
    assert catalog.json()["consumer_contract"]["content"]["withdrawal_notice"]
    assert set(catalog.json()["consumer_contract"]["required_acceptances"]) == {
        "terms",
        "immediate_performance",
        "withdrawal_consequences",
    }

    checkout = client.post(
        "/billing/checkout",
        headers={"Idempotency-Key": f"checkout-{uuid.uuid4().hex}"},
        json=_checkout_payload(client),
    )
    assert checkout.status_code == 401


def test_checkout_fails_closed_until_owner_enables_stripe(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    checkout_payload = _checkout_payload(client)
    rejected_payload = {
        **checkout_payload,
        "consumer_contract": {
            **checkout_payload["consumer_contract"],
            "terms_accepted": False,
        },
    }
    rejected = client.post(
        "/billing/checkout",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"checkout-{uuid.uuid4().hex}",
        },
        json=rejected_payload,
    )
    assert rejected.status_code == 422

    checkout = client.post(
        "/billing/checkout",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"checkout-{uuid.uuid4().hex}",
        },
        json=checkout_payload,
    )
    assert checkout.status_code == 503
    assert checkout.json()["detail"] == "Credit purchases are not enabled yet"


def test_consumer_contract_vault_and_withdrawal_api_are_authenticated_and_durable(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    purchase_id, user = _seed_paid_contract_purchase(
        client,
        user_auth_headers,
    )

    unauthenticated = client.get("/billing/purchases")
    assert unauthenticated.status_code == 401

    purchases = client.get(
        "/billing/purchases",
        headers=user_auth_headers,
    )
    assert purchases.status_code == 200
    purchase = next(item for item in purchases.json() if item["purchase_id"] == purchase_id)
    assert purchase["status"] == "paid"
    assert purchase["contract_confirmation_available"] is True
    assert purchase["contract_confirmation_url"] == (f"/billing/purchases/{purchase_id}/contract-confirmation")
    assert purchase["withdrawal_action_available"] is True
    assert purchase["withdrawal_status"] is None

    confirmation = client.get(
        purchase["contract_confirmation_url"],
        headers=user_auth_headers,
    )
    assert confirmation.status_code == 200
    assert confirmation.headers["cache-control"] == "private, no-store"
    assert confirmation.headers["content-disposition"] == (f'attachment; filename="gsubs-contract-{purchase_id}.json"')
    assert confirmation.headers["x-content-type-options"] == "nosniff"
    assert confirmation.headers["etag"].startswith('"')
    confirmation_document = confirmation.json()
    assert confirmation_document["document_type"] == "gsubs_consumer_contract_confirmation"
    assert confirmation_document["purchase"]["purchase_id"] == purchase_id
    assert confirmation_document["delivery_channel"] == "account_vault"
    assert confirmation_document["delivery_status"] == "available_approved"

    withdrawal_key = f"withdrawal-{uuid.uuid4().hex}"
    withdrawal_payload = {
        "locale": "el",
        "withdrawal_requested": True,
        "confirmed_name": user.name,
        "confirmation_email": user.email,
    }
    withdrawal = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": withdrawal_key,
        },
        json=withdrawal_payload,
    )
    assert withdrawal.status_code == 200
    assert withdrawal.json()["status"] == "pending_manual_review"
    assert withdrawal.json()["timeliness_assessment_status"] == "pending_manual_review"
    assert withdrawal.json()["acknowledgement_url"] == (f"/billing/purchases/{purchase_id}/withdrawal-acknowledgement")

    monkeypatch.setattr(
        billing_consumer_records_module,
        "WITHDRAWAL_SCHEMA_VERSION",
        2,
    )
    replay = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": withdrawal_key,
        },
        json=withdrawal_payload,
    )
    assert replay.status_code == 200
    assert replay.json() == withdrawal.json()

    equivalent_cross_key_replay = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"withdrawal-{uuid.uuid4().hex}",
        },
        json=withdrawal_payload,
    )
    assert equivalent_cross_key_replay.status_code == 200
    assert equivalent_cross_key_replay.json() == withdrawal.json()

    acknowledgement = client.get(
        withdrawal.json()["acknowledgement_url"],
        headers=user_auth_headers,
    )
    assert acknowledgement.status_code == 200
    assert acknowledgement.headers["cache-control"] == "private, no-store"
    acknowledgement_document = acknowledgement.json()
    assert acknowledgement_document["document_type"] == "gsubs_withdrawal_acknowledgement"
    assert acknowledgement_document["automatic_stripe_refund_executed"] is False
    assert acknowledgement_document["automatic_aade_adjustment_executed"] is False
    assert acknowledgement_document["timeliness_assessment_status"] == "pending_manual_review"
    assert acknowledgement_document["confirmation_electronic_means"] == {
        "type": "email",
        "address": user.email,
        "delivery_status": "not_sent_transactional_channel_not_ready",
    }

    updated_purchases = client.get(
        "/billing/purchases",
        headers=user_auth_headers,
    )
    updated = next(item for item in updated_purchases.json() if item["purchase_id"] == purchase_id)
    assert updated["withdrawal_action_available"] is False
    assert updated["withdrawal_status"] == "pending_manual_review"
    assert updated["withdrawal_acknowledgement_available"] is True

    exported_response = client.get(
        "/auth/export",
        headers=user_auth_headers,
    )
    assert exported_response.status_code == 200
    exported_purchase = next(
        item for item in exported_response.json()["billing_purchases"] if item["id"] == purchase_id
    )
    assert exported_purchase["contract_confirmation"]["content_sha256"] == confirmation.headers["etag"].strip('"')
    assert exported_purchase["withdrawal_request"]["request_snapshot"]["confirmed_name"] == user.name
    assert (
        exported_purchase["withdrawal_request"]["request_snapshot"]["confirmation_electronic_means"]["address"]
        == user.email
    )

    blocked_deletion = client.delete(
        "/auth/me",
        headers=user_auth_headers,
    )
    assert blocked_deletion.status_code == 409
    assert "withdrawal request is pending manual review" in (blocked_deletion.json()["detail"])
    # The guard preserves the authenticated account-vault access until a
    # reviewed resolution and durable-delivery workflow exists.
    assert (
        client.get(
            withdrawal.json()["acknowledgement_url"],
            headers=user_auth_headers,
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("locale", "en"),
        ("confirmed_name", "Different Consumer"),
        ("confirmation_email", "different-consumer@example.com"),
    ],
)
def test_cross_key_withdrawal_replay_requires_equivalent_request_details(
    client: TestClient,
    user_auth_headers: dict[str, str],
    changed_field: str,
    changed_value: str,
) -> None:
    purchase_id, user = _seed_paid_contract_purchase(
        client,
        user_auth_headers,
    )
    original_key = f"withdrawal-{uuid.uuid4().hex}"
    original_payload = {
        "locale": "el",
        "withdrawal_requested": True,
        "confirmed_name": user.name,
        "confirmation_email": user.email,
    }
    original = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": original_key,
        },
        json=original_payload,
    )
    assert original.status_code == 200

    conflicting_payload = {
        **original_payload,
        changed_field: changed_value,
    }
    conflict = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": f"withdrawal-{uuid.uuid4().hex}",
        },
        json=conflicting_payload,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "A withdrawal request already exists for this purchase "
        "with different details"
    )

    database, _ = _authenticated_user(client, user_auth_headers)
    with database.session() as session:
        requests = tuple(
            session.scalars(
                select(DbBillingWithdrawalRequest).where(
                    DbBillingWithdrawalRequest.purchase_id == purchase_id,
                )
            )
        )
        assert len(requests) == 1
        assert requests[0].idempotency_key == original_key


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("locale", "en"),
        ("confirmed_name", "Different Consumer"),
        ("confirmation_email", "different-consumer@example.com"),
    ],
)
def test_same_key_withdrawal_replay_rejects_changed_request_details(
    client: TestClient,
    user_auth_headers: dict[str, str],
    changed_field: str,
    changed_value: str,
) -> None:
    purchase_id, user = _seed_paid_contract_purchase(
        client,
        user_auth_headers,
    )
    idempotency_key = f"withdrawal-{uuid.uuid4().hex}"
    original_payload = {
        "locale": "el",
        "withdrawal_requested": True,
        "confirmed_name": user.name,
        "confirmation_email": user.email,
    }
    original = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": idempotency_key,
        },
        json=original_payload,
    )
    assert original.status_code == 200

    conflict = client.post(
        f"/billing/purchases/{purchase_id}/withdrawals",
        headers={
            **user_auth_headers,
            "Idempotency-Key": idempotency_key,
        },
        json={
            **original_payload,
            changed_field: changed_value,
        },
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == (
        "Idempotency key was used for another withdrawal request"
    )

    database, _ = _authenticated_user(client, user_auth_headers)
    with database.session() as session:
        requests = tuple(
            session.scalars(
                select(DbBillingWithdrawalRequest).where(
                    DbBillingWithdrawalRequest.purchase_id == purchase_id,
                )
            )
        )
        assert len(requests) == 1
        assert requests[0].idempotency_key == idempotency_key


def test_contract_artifacts_do_not_disclose_unknown_purchase(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    unknown_purchase_id = uuid.uuid4().hex

    confirmation = client.get(
        f"/billing/purchases/{unknown_purchase_id}/contract-confirmation",
        headers=user_auth_headers,
    )
    acknowledgement = client.get(
        f"/billing/purchases/{unknown_purchase_id}/withdrawal-acknowledgement",
        headers=user_auth_headers,
    )

    assert confirmation.status_code == 404
    assert confirmation.json()["detail"] == "Contract confirmation not found"
    assert acknowledgement.status_code == 404
    assert acknowledgement.json()["detail"] == "Withdrawal acknowledgement not found"


@pytest.mark.parametrize(
    "corrupt_record",
    ("confirmation", "withdrawal"),
)
def test_gdpr_export_fails_closed_on_tampered_consumer_evidence(
    client: TestClient,
    user_auth_headers: dict[str, str],
    corrupt_record: str,
) -> None:
    _seed_paid_contract_purchase(
        client,
        user_auth_headers,
        corrupt_record=corrupt_record,
    )

    response = client.get(
        "/auth/export",
        headers=user_auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Billing export is unavailable because durable billing record integrity validation failed."
    )


def test_webhook_stream_rejects_chunked_payload_immediately_before_service() -> None:
    request, stream_state = _streaming_request(
        [
            b"a" * 600_000,
            b"b" * 400_000,
            b"c",
            b"must-not-be-read",
        ],
    )
    service = _RecordingBillingService()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=service,  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == 413
    assert stream_state["receive_calls"] == 3
    assert service.calls == 0


@pytest.mark.parametrize(
    ("content_length", "expected_status", "expected_detail"),
    [
        (b"1000001", 413, "Webhook payload is too large"),
        (b"not-an-integer", 400, "Invalid Content-Length"),
        (b"", 400, "Invalid Content-Length"),
        (b"-1", 400, "Invalid Content-Length"),
        (b"+1", 400, "Invalid Content-Length"),
        (b" 1", 400, "Invalid Content-Length"),
    ],
)
def test_webhook_rejects_unsafe_content_length_before_reading_stream(
    content_length: bytes,
    expected_status: int,
    expected_detail: str,
) -> None:
    request, stream_state = _streaming_request(
        [b"must-not-be-read"],
        headers=[(b"content-length", content_length)],
    )
    service = _RecordingBillingService()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=service,  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail
    assert stream_state["receive_calls"] == 0
    assert service.calls == 0


def test_webhook_stream_preserves_empty_body_rejection() -> None:
    request, _ = _streaming_request([b""])
    service = _RecordingBillingService()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=service,  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == 400
    assert service.calls == 0


def test_webhook_stream_passes_valid_payload_once() -> None:
    request, _ = _streaming_request(
        [b"", b'{"id":', b'"evt_streamed"}'],
        headers=[(b"content-length", b"21")],
    )
    service = _RecordingBillingService()

    response = asyncio.run(
        stripe_webhook(
            request,
            stripe_signature="test-signature",
            billing_service=service,  # type: ignore[arg-type]
        ),
    )

    assert response == {
        "event_id": "evt_streamed",
        "event_type": "customer.updated",
        "status": "ignored",
    }
    assert service.calls == 1
    assert service.payload == b'{"id":"evt_streamed"}'
    assert service.signature == "test-signature"


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (BillingDisabledError("disabled"), 503),
        (BillingConflictError("conflict"), 409),
        (BillingValidationError("invalid"), 400),
        (BillingProviderError("provider"), 502),
        (RuntimeError("secret internal detail"), 500),
    ],
)
def test_webhook_maps_billing_failures_without_leaking_unknown_errors(
    error: Exception,
    expected_status: int,
) -> None:
    class _FailingBillingService(_RecordingBillingService):
        def verify_and_process_webhook(
            self,
            *,
            payload: bytes,
            signature: str,
        ) -> WebhookResult:
            raise error

    request, _ = _streaming_request([b"{}"])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            stripe_webhook(
                request,
                stripe_signature="test-signature",
                billing_service=_FailingBillingService(),  # type: ignore[arg-type]
            ),
        )

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == ("Billing operation failed" if expected_status == 500 else str(error))
    assert "secret internal detail" not in str(exc_info.value.detail)


def test_points_endpoint_exposes_zeroed_balance_breakdown_for_new_account(
    client: TestClient,
    user_auth_headers: dict[str, str],
) -> None:
    response = client.get("/auth/points", headers=user_auth_headers)
    assert response.status_code == 200
    assert response.json() == {
        "balance": 0,
        "paid_balance": 0,
        "promotional_balance": 0,
        "reversal_debt": 0,
        "ai_spendable_balance": 0,
    }
