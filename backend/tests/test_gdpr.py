from __future__ import annotations

import hashlib
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from backend.app.api.endpoints import auth as auth_endpoints
from backend.app.api.endpoints.auth import delete_account
from backend.app.core import auth as backend_auth
from backend.app.core.auth import UserStore
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.db.models import (
    DbAIModel,
    DbBillingInvoice,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbDeletedEmail,
    DbGcsUploadSession,
    DbHistoryEvent,
    DbJob,
    DbOAuthState,
    DbPointTransaction,
    DbProviderBudgetReservation,
    DbProviderBudgetWindow,
    DbSession,
    DbTokenUsage,
    DbUsageLedger,
    DbUserPoints,
)
from backend.app.services import billing_retention
from backend.app.services.financial_records import (
    financial_account_reference_hash,
    financial_retention_deadline,
)

DELETED_EMAIL_RETENTION_SECONDS = 365 * 24 * 60 * 60
FINANCIAL_RECORDS_NOTICE = (
    "Account and media are permanently deleted; legally required financial "
    "records are retained in detached form. A cryptographic hash of the "
    "normalized email is retained for 365 days only to prevent repeated "
    "signup-credit grants."
)


def _seed_financial_record(*, user_id: str) -> tuple[str, str]:
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


def _seed_unpaid_attempt(*, user_id: str, status: str) -> str:
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


def _seed_reversal_history(
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


def test_data_export(client, user_auth_headers):
    """Ensure user can export their data (GDPR Right to Access)."""
    # 1. Create some data
    files = {"file": ("gdpr_test.mp4", b"data", "video/mp4")}
    client.post("/videos/process", headers=user_auth_headers, files=files)

    # 2. Request Export
    response = client.get("/auth/export", headers=user_auth_headers)

    # 3. Verify
    assert response.status_code == 200
    data = response.json()
    assert "profile" in data
    assert "jobs" in data
    assert len(data["jobs"]) >= 1

    # Get current user email to verify
    me_resp = client.get("/auth/me", headers=user_auth_headers)
    assert me_resp.status_code == 200
    email = me_resp.json()["email"]
    assert data["profile"]["email"] == email


def test_data_export_has_no_one_thousand_event_history_cap(
    client,
    user_auth_headers,
) -> None:
    me_response = client.get("/auth/me", headers=user_auth_headers)
    assert me_response.status_code == 200
    user = me_response.json()
    other_user_response = client.post(
        "/auth/register",
        json={
            "email": f"gdpr-history-other-{uuid.uuid4().hex}@example.com",
            "password": "testpassword123",
            "name": "Other History User",
        },
    )
    assert other_user_response.status_code == 200
    other_user = other_user_response.json()
    event_count = 1_001
    db = Database()
    with db.session() as session:
        session.add_all(
            [
                DbHistoryEvent(
                    ts=f"2026-07-26T00:00:{sequence:04d}Z",
                    user_id=user["id"],
                    email=user["email"],
                    kind="gdpr_bulk_export",
                    summary=f"GDPR history event {sequence}",
                    data={"sequence": sequence},
                )
                for sequence in range(event_count)
            ]
        )
        session.add(
            DbHistoryEvent(
                ts="2026-07-26T00:01:0000Z",
                user_id=other_user["id"],
                email=other_user["email"],
                kind="gdpr_bulk_export",
                summary="Another user's event",
                data={"sequence": "other-user"},
            )
        )

    response = client.get("/auth/export", headers=user_auth_headers)

    assert response.status_code == 200
    exported = [item for item in response.json()["history"] if item["kind"] == "gdpr_bulk_export"]
    # REGRESSION: the GDPR endpoint previously reused the UI's recent-history
    # query with limit=1000 and silently omitted older personal data.
    assert len(exported) == event_count
    assert {item["data"]["sequence"] for item in exported} == set(range(event_count))


def test_data_export_has_no_ten_job_cap_and_is_deterministic(
    client,
    user_auth_headers,
) -> None:
    me_response = client.get("/auth/me", headers=user_auth_headers)
    assert me_response.status_code == 200
    user_id = me_response.json()["id"]
    prefix = f"gdpr-all-jobs-{uuid.uuid4().hex[:8]}"
    job_ids = [f"{prefix}-{sequence:02d}" for sequence in range(11)]
    db = Database()
    with db.session() as session:
        session.add_all(
            [
                DbJob(
                    id=job_id,
                    user_id=user_id,
                    status="completed",
                    created_at=1_800_000_000 + sequence,
                    updated_at=1_800_000_100 + sequence,
                    progress=100,
                    message=None,
                    result_data={"sequence": sequence},
                )
                for sequence, job_id in enumerate(job_ids)
            ]
        )

    response = client.get("/auth/export", headers=user_auth_headers)

    assert response.status_code == 200
    exported_ids = [item["id"] for item in response.json()["jobs"] if item["id"].startswith(prefix)]
    # REGRESSION: the export reused the UI helper's default limit=10.
    assert exported_ids == list(reversed(job_ids))


def test_data_export_includes_user_linked_audit_data_without_auth_secrets(
    client,
    user_auth_headers,
) -> None:
    me_response = client.get("/auth/me", headers=user_auth_headers)
    assert me_response.status_code == 200
    user = me_response.json()
    now = int(time.time())
    suffix = uuid.uuid4().hex
    job_id = f"gdpr-audit-{suffix}"
    point_transaction_id = uuid.uuid4().hex
    ledger_id = uuid.uuid4().hex
    ledger_idempotency_key = f"gdpr-ledger-{suffix}"
    model_id = f"gdpr-model-{suffix[:16]}"
    daily_window_key = f"gdpr-day-{suffix}"
    monthly_window_key = f"gdpr-month-{suffix}"
    session_secret = f"session-secret-{suffix}"
    expired_session_secret = f"expired-session-secret-{suffix}"
    oauth_secret = f"oauth-secret-{suffix}"
    expired_oauth_secret = f"expired-oauth-secret-{suffix}"
    upload_secret = f"upload-secret-{suffix}"
    marker_hash = hashlib.sha256(user["email"].lower().encode()).hexdigest()

    db = Database()
    with db.session() as session:
        wallet = session.get(DbUserPoints, user["id"])
        assert wallet is not None
        wallet.balance = 321
        wallet.paid_balance = 123
        wallet.reversal_debt = 7
        wallet.updated_at = now
        session.add_all(
            (
                DbJob(
                    id=job_id,
                    user_id=user["id"],
                    status="completed",
                    created_at=now,
                    updated_at=now,
                    progress=100,
                    message=None,
                    result_data={"original_filename": "personal-name.mp4"},
                ),
                DbPointTransaction(
                    id=point_transaction_id,
                    user_id=user["id"],
                    delta=-10,
                    paid_delta=-10,
                    reversal_debt_delta=0,
                    reason="gdpr_audit",
                    meta={"job_id": job_id},
                    created_at=now,
                ),
                DbUsageLedger(
                    id=ledger_id,
                    user_id=user["id"],
                    job_id=job_id,
                    action="transcription",
                    provider="test-provider",
                    endpoint="/v1/test",
                    model=model_id,
                    tier="standard",
                    units={"seconds": 5},
                    cost_usd=0.01,
                    credits_reserved=10,
                    paid_credits_reserved=10,
                    credits_charged=10,
                    min_credits=10,
                    currency="USD",
                    status="finalized",
                    error=None,
                    idempotency_key=ledger_idempotency_key,
                    created_at=now,
                    updated_at=now,
                ),
                DbAIModel(
                    id=model_id,
                    input_price_per_1m=1.0,
                    output_price_per_1m=2.0,
                    currency="USD",
                    active=True,
                    updated_at=now,
                ),
                DbSession(
                    token_hash=session_secret,
                    user_id=user["id"],
                    created_at=now,
                    expires_at=now + 3_600,
                    user_agent="GDPR Browser",
                ),
                DbSession(
                    token_hash=expired_session_secret,
                    user_id=user["id"],
                    created_at=now - 7_200,
                    expires_at=now - 3_600,
                    user_agent="Expired GDPR Browser",
                ),
                DbOAuthState(
                    state=oauth_secret,
                    provider="test-provider",
                    user_id=user["id"],
                    created_at=now,
                    expires_at=now + 600,
                    user_agent="GDPR OAuth Browser",
                    ip="192.0.2.25",
                ),
                DbOAuthState(
                    state=expired_oauth_secret,
                    provider="expired-test-provider",
                    user_id=user["id"],
                    created_at=now - 7_200,
                    expires_at=now - 3_600,
                    user_agent="Expired GDPR OAuth Browser",
                    ip="192.0.2.26",
                ),
                DbGcsUploadSession(
                    id=upload_secret,
                    user_id=user["id"],
                    object_name=f"uploads/{user['id']}/{suffix}.mp4",
                    content_type="video/mp4",
                    original_filename="personal-name.mp4",
                    created_at=now,
                    expires_at=now + 3_600,
                    used_at=None,
                ),
                DbProviderBudgetWindow(
                    key=daily_window_key,
                    scope="day",
                    period_start=now,
                    reserved_usd=0.0,
                    spent_usd=0.01,
                    updated_at=now,
                ),
                DbProviderBudgetWindow(
                    key=monthly_window_key,
                    scope="month",
                    period_start=now,
                    reserved_usd=0.0,
                    spent_usd=0.01,
                    updated_at=now,
                ),
                DbDeletedEmail(
                    email_hash=marker_hash,
                    deleted_at=now - 60,
                ),
            )
        )
    with db.session() as session:
        session.add(
            DbTokenUsage(
                job_id=job_id,
                model_id=model_id,
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cost=0.01,
                timestamp=now,
            )
        )
        session.add(
            DbProviderBudgetReservation(
                idempotency_key=ledger_idempotency_key,
                daily_window_key=daily_window_key,
                monthly_window_key=monthly_window_key,
                estimated_usd=0.02,
                actual_usd=0.01,
                status="finalized",
                created_at=now,
                updated_at=now,
            )
        )

    response = client.get("/auth/export", headers=user_auth_headers)

    assert response.status_code == 200
    exported = response.json()
    assert exported["wallet"] == {
        "balance": 321,
        "paid_balance": 123,
        "promotional_balance": 198,
        "reversal_debt": 7,
        "updated_at": now,
    }
    assert any(item["id"] == point_transaction_id for item in exported["point_transactions"])
    assert [item["id"] for item in exported["usage_ledger"]] == [ledger_id]
    assert exported["token_usage"][0]["job_id"] == job_id
    assert exported["provider_budget_reservations"][0]["idempotency_key"] == ledger_idempotency_key
    assert exported["gcs_uploads"][0]["object_name"].endswith(f"/{suffix}.mp4")
    assert upload_secret not in str(exported["gcs_uploads"])
    assert any(item["user_agent"] == "GDPR Browser" and item["active"] is True for item in exported["sessions"])
    assert any(
        item["user_agent"] == "Expired GDPR Browser" and item["active"] is False for item in exported["sessions"]
    )
    assert session_secret not in str(exported["sessions"])
    assert expired_session_secret not in str(exported["sessions"])
    assert exported["oauth_states"] == [
        {
            "provider": "expired-test-provider",
            "created_at": now - 7_200,
            "expires_at": now - 3_600,
            "user_agent": "Expired GDPR OAuth Browser",
            "ip": "192.0.2.26",
            "active": False,
        },
        {
            "provider": "test-provider",
            "created_at": now,
            "expires_at": now + 600,
            "user_agent": "GDPR OAuth Browser",
            "ip": "192.0.2.25",
            "active": True,
        },
    ]
    assert oauth_secret not in str(exported["oauth_states"])
    assert expired_oauth_secret not in str(exported["oauth_states"])
    assert exported["deleted_email_marker"] == {
        "fingerprint": marker_hash,
        "fingerprint_algorithm": "sha256_normalized_email",
        "deleted_at": now - 60,
        "expires_at": now - 60 + DELETED_EMAIL_RETENTION_SECONDS,
        "purpose": "prevent_repeat_signup_credit_grants",
    }
    assert exported["deleted_email_marker_policy"] == {
        "created_on_account_deletion": True,
        "retention_days": 365,
        "purpose": "prevent_repeat_signup_credit_grants",
    }


def test_data_export_includes_current_users_financial_snapshots(
    client,
    user_auth_headers,
) -> None:
    me_response = client.get("/auth/me", headers=user_auth_headers)
    assert me_response.status_code == 200
    user_id = me_response.json()["id"]
    purchase_id, invoice_id = _seed_financial_record(user_id=user_id)
    expected_reversals = _seed_reversal_history(purchase_id=purchase_id)
    other_user = client.post(
        "/auth/register",
        json={
            "email": f"gdpr-other-{uuid.uuid4().hex}@example.com",
            "password": "testpassword123",
            "name": "Other GDPR User",
        },
    )
    assert other_user.status_code == 200
    other_purchase_id, _ = _seed_financial_record(
        user_id=other_user.json()["id"],
    )

    response = client.get("/auth/export", headers=user_auth_headers)

    assert response.status_code == 200
    purchases = response.json()["billing_purchases"]
    assert other_purchase_id not in {item["id"] for item in purchases}
    exported = next(item for item in purchases if item["id"] == purchase_id)
    assert exported["package_snapshot"] == {
        "catalog_version": "test",
        "package_key": "creator",
        "credits": 350,
        "amount_eur_cents": 300,
        "currency": "eur",
    }
    assert exported["payment_snapshot"]["payment_intent_id"].startswith("pi_")
    assert exported["customer_snapshot"]["email"] == "gdpr-customer@example.com"
    assert exported["tax_snapshot"]["vat_rate_percent"] == 24
    assert exported["refunded_amount_cents"] == 100
    assert exported["dispute_active"] is True
    assert exported["reversed_amount_cents"] == 300
    assert exported["reversed_credits"] == 350
    assert exported["reversal_debt_credits"] == 50
    # REGRESSION: aggregate purchase status alone omitted the provider objects
    # and event chronology needed to understand a refund or dispute.
    assert exported["reversals"] == expected_reversals
    assert exported["invoice"] == {
        "id": invoice_id,
        "provider": "aade_etimologio",
        "document_kind": "retail_service_receipt",
        "document_status": "issued",
        "aade_document_type": "11.2",
        "aade_series": "0",
        "aade_aa": exported["invoice"]["aade_aa"],
        "aade_mark": exported["invoice"]["aade_mark"],
        "issued_at": exported["invoice"]["issued_at"],
        "document_snapshot": {
            "service_code": "4",
            "service_name": "GSUBS Credits",
            "gross_amount_cents": 300,
        },
        "financial_retention_until": exported["invoice"]["financial_retention_until"],
    }
    # The operator pseudonym belongs to the internal financial audit, not the
    # purchasing customer's portability payload.
    assert "recorded_by_user_id" not in exported["invoice"]
    assert "recorded_at" not in exported["invoice"]


def test_delete_account_discloses_detached_financial_retention(
    client,
    user_auth_headers,
) -> None:
    assert delete_account.__doc__ == FINANCIAL_RECORDS_NOTICE

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 200
    assert response.json() == {
        "status": "deleted",
        "message": FINANCIAL_RECORDS_NOTICE,
    }


def test_account_deletion_preserves_detached_pseudonymous_invoice_actor_audit(
    client,
    user_auth_headers,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    purchase_id, invoice_id = _seed_financial_record(user_id=user_id)

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 200
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        invoice = session.get(DbBillingInvoice, invoice_id)
        assert purchase is not None
        assert invoice is not None
        assert purchase.user_id is None
        # No user FK is intentional: only the non-email internal identifier is
        # retained with the financial record for accountability.
        assert invoice.recorded_by_user_id == user_id
        assert invoice.recorded_at == invoice.issued_at


def test_account_deletion_is_blocked_while_checkout_is_open(
    client,
    user_auth_headers,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    purchase_id = _seed_unpaid_attempt(
        user_id=user_id,
        status="checkout_created",
    )

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 409
    assert "payment is still open" in response.json()["detail"]
    assert client.get("/auth/me", headers=user_auth_headers).status_code == 200
    db = Database()
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase_id) is not None


def test_account_deletion_is_blocked_while_media_jobs_are_active(
    client,
    user_auth_headers,
    monkeypatch,
    tmp_path: Path,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    suffix = uuid.uuid4().hex
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()
    pending_job_id = f"pending-{suffix}"
    processing_job_id = f"processing-{suffix}"
    db = Database()
    with db.session() as session:
        session.add_all(
            (
                DbJob(
                    id=pending_job_id,
                    user_id=user_id,
                    status="pending",
                    created_at=1_800_000_000,
                    updated_at=1_800_000_000,
                    progress=0,
                    message=None,
                    result_data=None,
                ),
                DbJob(
                    id=processing_job_id,
                    user_id=user_id,
                    status="processing",
                    created_at=1_800_000_001,
                    updated_at=1_800_000_001,
                    progress=25,
                    message="Processing",
                    result_data=None,
                ),
            )
        )
    for job_id in (pending_job_id, processing_job_id):
        (uploads_dir / f"{job_id}_input.mp4").write_bytes(b"keep")
        job_artifacts = artifacts_dir / job_id
        job_artifacts.mkdir()
        (job_artifacts / "processed.mp4").write_bytes(b"keep")

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 409
    assert "processing" in response.json()["detail"].lower()
    assert (
        client.get(
            "/auth/me",
            headers=user_auth_headers,
        ).status_code
        == 200
    )
    with db.session() as session:
        assert session.get(DbJob, pending_job_id) is not None
        assert session.get(DbJob, processing_job_id) is not None
    for job_id in (pending_job_id, processing_job_id):
        assert (uploads_dir / f"{job_id}_input.mp4").exists()
        assert (artifacts_dir / job_id / "processed.mp4").exists()


def test_account_deletion_detaches_recent_terminal_unpaid_attempt(
    client,
    user_auth_headers,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    purchase_id = _seed_unpaid_attempt(
        user_id=user_id,
        status="failed",
    )

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 200
    db = Database()
    with db.session() as session:
        purchase = session.get(DbCreditPurchase, purchase_id)
        assert purchase is not None
        assert purchase.user_id is None
        assert purchase.account_reference_hash == financial_account_reference_hash(
            user_id,
        )
        assert user_id not in purchase.account_reference_hash
        assert purchase.checkout_url is None
        assert purchase.customer_snapshot is None
        assert purchase.payment_snapshot is None
        assert purchase.tax_snapshot is None
        assert purchase.status == "failed"
        assert purchase.financial_retention_until > int(time.time())
        retained_until = purchase.financial_retention_until

    # The database deliberately rejects a future cleanup clock, so model the
    # same detached post-deletion shape after its 24-hour deadline instead of
    # weakening the production clock guard for this regression.
    expired_suffix = uuid.uuid4().hex
    expired_created_at = int(time.time()) - 86_401
    expired_purchase = DbCreditPurchase(
        id=expired_suffix[:32],
        user_id=None,
        account_reference_hash=financial_account_reference_hash(user_id),
        provider="stripe",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        idempotency_key=f"gdpr-expired-detached-{expired_suffix}"[:64],
        checkout_session_id=f"cs_test_{expired_suffix}",
        checkout_url=None,
        payment_intent_id=None,
        integration_identifier="gsubs_credits_v1",
        status="failed",
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
        financial_retention_until=expired_created_at + 86_400,
        error=None,
        created_at=expired_created_at,
        updated_at=expired_created_at,
    )
    with db.session() as session:
        session.add(expired_purchase)

    report = billing_retention.cleanup_expired_billing_records(
        db,
        now=int(time.time()),
    )

    assert report.deleted_unpaid_attempts >= 1
    with db.session() as session:
        retained = session.get(DbCreditPurchase, purchase_id)
        assert retained is not None
        assert retained.financial_retention_until == retained_until
        assert (
            session.get(
                DbCreditPurchase,
                expired_purchase.id,
            )
            is None
        )


def test_account_deletion_cleans_files(client, user_auth_headers):
    """Ensure account deletion removes all files (GDPR Right to Erasure)."""
    # Get email before deletion
    me_resp = client.get("/auth/me", headers=user_auth_headers)
    email = me_resp.json()["email"]

    # 1. Create Job
    files = {"file": ("gdpr_delete.mp4", b"content", "video/mp4")}
    resp = client.post("/videos/process", headers=user_auth_headers, files=files)
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    # 2. Delete Account
    del_resp = client.delete("/auth/me", headers=user_auth_headers)
    assert del_resp.status_code == 200

    # 3. Verify Login Fails
    # We need to try to get a new token because the old token might still seem valid if stateless JWT (unless blacklist checked)
    # But /auth/me should fail if user is gone from DB.
    login_resp = client.get("/auth/me", headers=user_auth_headers)
    assert login_resp.status_code == 401

    # 4. Re-register and check empty
    client.post("/auth/register", json={"email": email, "password": "testpassword123", "name": "Test User"})
    # Login
    token_resp = client.post("/auth/token", data={"username": email, "password": "testpassword123"})
    new_token = token_resp.json()["access_token"]
    new_headers = {"Authorization": f"Bearer {new_token}"}

    # Check jobs
    jobs_resp = client.get("/videos/jobs", headers=new_headers)
    assert jobs_resp.status_code == 200
    jobs = jobs_resp.json()
    assert len(jobs) == 0, "Jobs should be wiped after account deletion"

    # 5. Verify Files Gone (Harder without access to server FS in blackbox test)
    # But checking jobs list is decent proxy for DB cleanup.
    # For file cleanup, we rely on implementation logic verification or integration testing.


def test_account_deletion_removes_all_local_and_known_gcs_media(
    client,
    user_auth_headers,
    monkeypatch,
    tmp_path: Path,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    uploads_dir = tmp_path / "uploads"
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir.mkdir()
    artifacts_dir.mkdir()

    suffix = uuid.uuid4().hex[:8]
    job_ids = [f"gdpr-delete-{suffix}-{sequence:02d}" for sequence in range(11)]
    expected_gcs_objects: set[str] = set()
    db = Database()
    with db.session() as session:
        for sequence, job_id in enumerate(job_ids):
            source_object = f"uploads/{user_id}/{job_id}.mp4"
            video_path = f"artifacts/{job_id}/processed.mp4"
            transcription_path = f"artifacts/{job_id}/transcription.json"
            variant_path = f"artifacts/{job_id}/processed-720p.mp4"
            expected_gcs_objects.update(
                {
                    source_object,
                    f"static/{video_path}",
                    f"static/{transcription_path}",
                    f"static/{variant_path}",
                }
            )
            session.add(
                DbJob(
                    id=job_id,
                    user_id=user_id,
                    status="completed",
                    created_at=1_800_000_000 + sequence,
                    updated_at=1_800_000_100 + sequence,
                    progress=100,
                    message=None,
                    result_data={
                        "source_gcs_object": source_object,
                        "video_path": video_path,
                        "transcription_url": f"/static/{transcription_path}",
                        "variants": {"720p": variant_path},
                    },
                )
            )
            session.add(
                DbGcsUploadSession(
                    id=f"upload-{uuid.uuid4().hex}",
                    user_id=user_id,
                    object_name=source_object,
                    content_type="video/mp4",
                    original_filename=f"{job_id}.mp4",
                    created_at=1_800_000_000 + sequence,
                    expires_at=2_000_000_000,
                    used_at=1_800_000_010 + sequence,
                )
            )
            (uploads_dir / f"{job_id}_input.mp4").write_bytes(b"upload")
            job_artifacts = artifacts_dir / job_id
            job_artifacts.mkdir()
            (job_artifacts / "processed.mp4").write_bytes(b"result")

        pending_object = f"uploads/{user_id}/pending-{suffix}.mp4"
        expected_gcs_objects.add(pending_object)
        session.add(
            DbGcsUploadSession(
                id=f"upload-{uuid.uuid4().hex}",
                user_id=user_id,
                object_name=pending_object,
                content_type="video/mp4",
                original_filename="pending.mp4",
                created_at=1_800_000_100,
                expires_at=2_000_000_000,
                used_at=None,
            )
        )

    deleted_gcs_objects: list[str] = []
    monkeypatch.setattr(
        auth_endpoints,
        "get_gcs_settings",
        lambda: SimpleNamespace(
            uploads_prefix="uploads",
            static_prefix="static",
        ),
        raising=False,
    )
    monkeypatch.setattr(
        auth_endpoints,
        "delete_object",
        lambda *, settings, object_name: deleted_gcs_objects.append(object_name),
        raising=False,
    )

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 200
    assert set(deleted_gcs_objects) == expected_gcs_objects
    for job_id in job_ids:
        assert not (uploads_dir / f"{job_id}_input.mp4").exists()
        assert not (artifacts_dir / job_id).exists()


def test_account_deletion_is_fail_closed_without_cloud_cleanup_configuration(
    client,
    user_auth_headers,
    monkeypatch,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    upload_id = f"upload-{uuid.uuid4().hex}"
    db = Database()
    with db.session() as session:
        session.add(
            DbGcsUploadSession(
                id=upload_id,
                user_id=user_id,
                object_name=f"uploads/{user_id}/{uuid.uuid4().hex}.mp4",
                content_type="video/mp4",
                original_filename="cloud-only.mp4",
                created_at=int(time.time()),
                expires_at=int(time.time()) + 3_600,
                used_at=None,
            )
        )
    monkeypatch.setattr(auth_endpoints, "get_gcs_settings", lambda: None)

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 500
    # REGRESSION: an account must not be reported erased while known remote
    # media cannot be reached and deleted.
    assert client.get("/auth/me", headers=user_auth_headers).status_code == 200
    with db.session() as session:
        assert session.get(DbGcsUploadSession, upload_id) is not None


def test_account_deletion_is_fail_closed_when_cloud_delete_fails(
    client,
    user_auth_headers,
    monkeypatch,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    upload_id = f"upload-{uuid.uuid4().hex}"
    object_name = f"uploads/{user_id}/{uuid.uuid4().hex}.mp4"
    db = Database()
    with db.session() as session:
        session.add(
            DbGcsUploadSession(
                id=upload_id,
                user_id=user_id,
                object_name=object_name,
                content_type="video/mp4",
                original_filename="cloud-failure.mp4",
                created_at=int(time.time()),
                expires_at=int(time.time()) + 3_600,
                used_at=None,
            )
        )
    monkeypatch.setattr(
        auth_endpoints,
        "get_gcs_settings",
        lambda: SimpleNamespace(
            uploads_prefix="uploads",
            static_prefix="static",
        ),
    )

    def fail_delete(*, settings: object, object_name: str) -> None:
        del settings, object_name
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(auth_endpoints, "delete_object", fail_delete)

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 500
    assert client.get("/auth/me", headers=user_auth_headers).status_code == 200
    with db.session() as session:
        assert session.get(DbGcsUploadSession, upload_id) is not None


def test_account_deletion_removes_only_owned_provider_reservations(
    client,
    user_auth_headers,
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    other_response = client.post(
        "/auth/register",
        json={
            "email": f"gdpr-reservation-other-{uuid.uuid4().hex}@example.com",
            "password": "testpassword123",
            "name": "Other Reservation User",
        },
    )
    assert other_response.status_code == 200
    other_user_id = other_response.json()["id"]
    suffix = uuid.uuid4().hex
    current_key = f"current-{suffix}"
    other_key = f"other-{suffix}"
    daily_window_key = f"day-{suffix}"
    monthly_window_key = f"month-{suffix}"
    now = int(time.time())
    db = Database()
    with db.session() as session:
        session.add_all(
            (
                DbProviderBudgetWindow(
                    key=daily_window_key,
                    scope="day",
                    period_start=now,
                    reserved_usd=0.0,
                    spent_usd=0.02,
                    updated_at=now,
                ),
                DbProviderBudgetWindow(
                    key=monthly_window_key,
                    scope="month",
                    period_start=now,
                    reserved_usd=0.0,
                    spent_usd=0.02,
                    updated_at=now,
                ),
                DbUsageLedger(
                    id=uuid.uuid4().hex,
                    user_id=user_id,
                    job_id=None,
                    action="privacy_test",
                    provider="test",
                    endpoint=None,
                    model=None,
                    tier=None,
                    units=None,
                    cost_usd=0.01,
                    credits_reserved=0,
                    paid_credits_reserved=0,
                    credits_charged=0,
                    min_credits=0,
                    currency="USD",
                    status="finalized",
                    error=None,
                    idempotency_key=current_key,
                    created_at=now,
                    updated_at=now,
                ),
                DbUsageLedger(
                    id=uuid.uuid4().hex,
                    user_id=other_user_id,
                    job_id=None,
                    action="privacy_test",
                    provider="test",
                    endpoint=None,
                    model=None,
                    tier=None,
                    units=None,
                    cost_usd=0.01,
                    credits_reserved=0,
                    paid_credits_reserved=0,
                    credits_charged=0,
                    min_credits=0,
                    currency="USD",
                    status="finalized",
                    error=None,
                    idempotency_key=other_key,
                    created_at=now,
                    updated_at=now,
                ),
            )
        )
    with db.session() as session:
        session.add_all(
            (
                DbProviderBudgetReservation(
                    idempotency_key=current_key,
                    daily_window_key=daily_window_key,
                    monthly_window_key=monthly_window_key,
                    estimated_usd=0.01,
                    actual_usd=0.01,
                    status="finalized",
                    created_at=now,
                    updated_at=now,
                ),
                DbProviderBudgetReservation(
                    idempotency_key=other_key,
                    daily_window_key=daily_window_key,
                    monthly_window_key=monthly_window_key,
                    estimated_usd=0.01,
                    actual_usd=0.01,
                    status="finalized",
                    created_at=now,
                    updated_at=now,
                ),
            )
        )

    deleted = client.delete("/auth/me", headers=user_auth_headers)

    assert deleted.status_code == 200
    with db.session() as session:
        assert session.get(DbProviderBudgetReservation, current_key) is None
        assert session.get(DbProviderBudgetReservation, other_key) is not None
        assert session.get(DbProviderBudgetWindow, daily_window_key) is not None
        assert session.get(DbProviderBudgetWindow, monthly_window_key) is not None


def test_deleted_email_marker_is_bounded_exportable_and_blocks_repeat_credit(
    client,
) -> None:
    email = f"gdpr-marker-{uuid.uuid4().hex}@example.com"
    password = "testpassword123"
    register = client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Marker User"},
    )
    assert register.status_code == 200
    token = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    deleted = client.delete("/auth/me", headers=headers)
    assert deleted.status_code == 200
    recreated = client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Marker User"},
    )
    assert recreated.status_code == 200
    recreated_token = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    ).json()["access_token"]
    recreated_headers = {"Authorization": f"Bearer {recreated_token}"}

    exported = client.get(
        "/auth/export",
        headers=recreated_headers,
    ).json()
    marker = exported["deleted_email_marker"]
    assert marker["fingerprint"] == hashlib.sha256(email.encode()).hexdigest()
    assert marker["expires_at"] == (marker["deleted_at"] + DELETED_EMAIL_RETENTION_SECONDS)
    assert (
        client.get(
            "/auth/points",
            headers=recreated_headers,
        ).json()["balance"]
        == 0
    )


def test_expired_deleted_email_marker_is_removed_and_no_longer_blocks_credit(
    client,
) -> None:
    email = f"gdpr-expired-marker-{uuid.uuid4().hex}@example.com"
    email_hash = hashlib.sha256(email.encode()).hexdigest()
    now = int(time.time())
    db = Database()
    with db.session() as session:
        session.add(
            DbDeletedEmail(
                email_hash=email_hash,
                deleted_at=now - DELETED_EMAIL_RETENTION_SECONDS,
            )
        )

    assert UserStore(db).cleanup_expired_deleted_email_markers(now=now) == 1
    registered = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "testpassword123",
            "name": "Expired Marker User",
        },
    )
    assert registered.status_code == 200
    token = client.post(
        "/auth/token",
        data={"username": email, "password": "testpassword123"},
    ).json()["access_token"]

    assert (
        client.get(
            "/auth/points",
            headers={"Authorization": f"Bearer {token}"},
        ).json()["balance"]
        == 100
    )


def test_deleted_email_marker_expires_at_exact_boundary_without_scheduled_cleanup(
    monkeypatch,
) -> None:
    now = 2_000_000_000
    email = f"gdpr-expiry-boundary-{uuid.uuid4().hex}@example.com"
    email_hash = hashlib.sha256(email.encode()).hexdigest()
    db = Database()
    with db.session() as session:
        session.add(
            DbDeletedEmail(
                email_hash=email_hash,
                deleted_at=now - DELETED_EMAIL_RETENTION_SECONDS,
            )
        )
    monkeypatch.setattr(backend_auth.time, "time", lambda: now)

    marker = UserStore(db).deleted_email_marker_for_email(email)

    # REGRESSION: expiry must be enforced during lookup even if the periodic
    # cleanup process has not run.
    assert marker is None
    with db.session() as session:
        assert session.get(DbDeletedEmail, email_hash) is None


def test_deleted_email_cleanup_preserves_marker_until_full_retention_elapsed(
    monkeypatch,
) -> None:
    now = 2_000_000_000
    expired_email = f"gdpr-cleanup-expired-{uuid.uuid4().hex}@example.com"
    retained_email = f"gdpr-cleanup-retained-{uuid.uuid4().hex}@example.com"
    expired_hash = hashlib.sha256(expired_email.encode()).hexdigest()
    retained_hash = hashlib.sha256(retained_email.encode()).hexdigest()
    db = Database()
    with db.session() as session:
        session.add_all(
            (
                DbDeletedEmail(
                    email_hash=expired_hash,
                    deleted_at=now - DELETED_EMAIL_RETENTION_SECONDS,
                ),
                DbDeletedEmail(
                    email_hash=retained_hash,
                    deleted_at=now - DELETED_EMAIL_RETENTION_SECONDS + 1,
                ),
            )
        )
    monkeypatch.setattr(backend_auth.time, "time", lambda: now)
    cutoff = now - DELETED_EMAIL_RETENTION_SECONDS
    with db.session() as session:
        assert UserStore(db)._email_was_deleted(
            retained_email,
            session=session,
        )
        expired_count = int(
            session.scalar(select(func.count()).select_from(DbDeletedEmail).where(DbDeletedEmail.deleted_at <= cutoff))
            or 0
        )

    assert expired_count >= 1
    assert UserStore(db).cleanup_expired_deleted_email_markers() == expired_count
    with db.session() as session:
        assert session.get(DbDeletedEmail, expired_hash) is None
        retained = session.get(DbDeletedEmail, retained_hash)
        assert retained is not None
        session.delete(retained)


def test_delete_missing_user_does_not_create_deleted_email_marker() -> None:
    db = Database()
    missing_user_id = f"missing-{uuid.uuid4().hex}"
    store = UserStore(db)
    with db.session() as session:
        marker_count_before = int(session.scalar(select(func.count()).select_from(DbDeletedEmail)) or 0)

    store.delete_user(missing_user_id)

    with db.session() as session:
        marker_count_after = int(session.scalar(select(func.count()).select_from(DbDeletedEmail)) or 0)
    assert marker_count_after == marker_count_before


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        123,
        "/uploads/user/object.mp4",
        "uploads/other-user/object.mp4",
        "uploads/user\\object.mp4",
        "uploads/user/../other/object.mp4",
        "uploads/user/folder//object.mp4",
    ],
)
def test_exact_owned_upload_validation_rejects_ambiguous_or_foreign_names(
    value: object,
) -> None:
    assert (
        auth_endpoints._validated_exact_object(
            value,
            required_prefix="uploads/user/",
        )
        is None
    )


def test_exact_owned_upload_validation_accepts_only_normalized_owned_name() -> None:
    object_name = "uploads/user/folder/object.mp4"

    assert (
        auth_endpoints._validated_exact_object(
            object_name,
            required_prefix="uploads/user/",
        )
        == object_name
    )


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        123,
        "artifacts/job-1\\object.mp4",
        "/artifacts/job-1/object.mp4",
        "artifacts/job-2/object.mp4",
        "artifacts/job-1/../job-2/object.mp4",
        "artifacts/job-1",
    ],
)
def test_static_artifact_validation_rejects_nonexact_job_paths(
    value: object,
) -> None:
    assert (
        auth_endpoints._static_object_for_job(
            value,
            job_id="job-1",
            static_prefix="static",
        )
        is None
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            "artifacts/job-1/processed.mp4",
            "static/artifacts/job-1/processed.mp4",
        ),
        (
            "/static/artifacts/job-1/transcription.json",
            "static/artifacts/job-1/transcription.json",
        ),
    ],
)
def test_static_artifact_validation_maps_exact_persisted_paths(
    value: str,
    expected: str,
) -> None:
    assert (
        auth_endpoints._static_object_for_job(
            value,
            job_id="job-1",
            static_prefix="static",
        )
        == expected
    )


@pytest.mark.parametrize(
    ("upload_objects", "result_data", "expected_error"),
    [
        (
            ["uploads/other-user/input.mp4"],
            {},
            "Invalid stored cloud-upload reference",
        ),
        (
            [],
            {"source_gcs_object": "uploads/other-user/input.mp4"},
            "Invalid stored cloud-upload reference",
        ),
        (
            [],
            {"variants": ["artifacts/job-1/output.mp4"]},
            "Invalid stored cloud-artifact references",
        ),
        (
            [],
            {"video_path": "artifacts/other-job/output.mp4"},
            "Invalid stored cloud-artifact reference",
        ),
    ],
)
def test_known_gcs_erasure_manifest_fails_closed_on_invalid_persisted_reference(
    upload_objects: list[str],
    result_data: dict[str, object],
    expected_error: str,
) -> None:
    job = SimpleNamespace(id="job-1", result_data=result_data)

    with pytest.raises(ValueError, match=expected_error):
        auth_endpoints._known_gcs_objects_for_erasure(
            user_id="user",
            jobs=[job],
            upload_session_objects=upload_objects,
            uploads_prefix="uploads",
            static_prefix="static",
        )


def test_known_gcs_erasure_manifest_is_sorted_exact_and_deduplicated() -> None:
    source = "uploads/user/source.mp4"
    job = SimpleNamespace(
        id="job-1",
        result_data={
            "source_gcs_object": source,
            "video_path": "artifacts/job-1/processed.mp4",
            "public_url": "/static/artifacts/job-1/processed.mp4",
            "transcription_url": ("/static/artifacts/job-1/transcription.json"),
            "variants": {
                "preview": "artifacts/job-1/preview.mp4",
            },
        },
    )

    objects = auth_endpoints._known_gcs_objects_for_erasure(
        user_id="user",
        jobs=[job],
        upload_session_objects=[source],
        uploads_prefix="uploads",
        static_prefix="static",
    )

    assert objects == sorted(
        {
            source,
            "static/artifacts/job-1/processed.mp4",
            "static/artifacts/job-1/transcription.json",
            "static/artifacts/job-1/preview.mp4",
        }
    )
