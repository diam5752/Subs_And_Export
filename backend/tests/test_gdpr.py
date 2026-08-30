from __future__ import annotations

import time
import uuid

from backend.app.core.database import Database
from backend.app.db.models import (
    DbAIModel,
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
from backend.tests.gdpr_test_support import (
    seed_financial_record as _seed_financial_record,
)
from backend.tests.gdpr_test_support import (
    seed_reversal_history as _seed_reversal_history,
)
from backend.tests.process_stream import post_process_stream


def test_data_export(client, funded_user_auth_headers):
    """Ensure user can export their data (GDPR Right to Access)."""
    # 1. Create some data
    post_process_stream(
        client,
        funded_user_auth_headers,
        filename="gdpr_test.mp4",
        content=b"data",
    )

    # 2. Request Export
    response = client.get("/auth/export", headers=funded_user_auth_headers)

    # 3. Verify
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    data = response.json()
    assert "profile" in data
    assert "jobs" in data
    assert len(data["jobs"]) >= 1

    # Get current user email to verify
    me_resp = client.get("/auth/me", headers=funded_user_auth_headers)
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
    # REGRESSION: the local-only product must not expose a dead cloud-storage
    # contract in a GDPR access export.
    assert "gcs_uploads" not in exported
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
    assert "deleted_email_marker" not in exported
    assert "deleted_email_marker_policy" not in exported


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
