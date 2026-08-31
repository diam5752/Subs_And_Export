from __future__ import annotations

import time
import uuid
from pathlib import Path

from backend.app.api.endpoints.auth import delete_account
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.erasure_journal import ErasureJournalError
from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
    DbJob,
    DbProviderBudgetReservation,
    DbProviderBudgetWindow,
    DbUsageLedger,
)
from backend.app.services import billing_retention
from backend.app.services.financial_records import (
    financial_account_reference_hash,
)
from backend.tests.gdpr_test_support import (
    FINANCIAL_RECORDS_NOTICE,
)
from backend.tests.gdpr_test_support import (
    seed_financial_record as _seed_financial_record,
)
from backend.tests.gdpr_test_support import (
    seed_unpaid_attempt as _seed_unpaid_attempt,
)
from backend.tests.process_stream import post_process_stream


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


def test_account_deletion_fails_closed_when_erasure_journal_is_unavailable(
    client,
    user_auth_headers,
    monkeypatch,
) -> None:
    from backend.app.api.endpoints import auth as auth_endpoints

    class BrokenJournal:
        def read_all(self) -> list[object]:
            raise ErasureJournalError("journal unavailable")

        def append(self, **_kwargs: object) -> None:
            raise ErasureJournalError("journal unavailable")

    monkeypatch.setattr(
        auth_endpoints,
        "configured_erasure_journal",
        lambda: BrokenJournal(),
    )

    response = client.delete("/auth/me", headers=user_auth_headers)

    # REGRESSION: an account cannot be reported erased unless its intent can
    # first survive a future database/app-data restore.
    assert response.status_code == 503
    assert response.json() == {"detail": "Privacy protection is temporarily unavailable. Please try again."}
    assert client.get("/auth/me", headers=user_auth_headers).status_code == 200


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


def test_account_deletion_cleans_files(client, funded_user_auth_headers):
    """Ensure account deletion removes all files (GDPR Right to Erasure)."""
    # Get email before deletion
    me_resp = client.get("/auth/me", headers=funded_user_auth_headers)
    email = me_resp.json()["email"]

    # 1. Create Job
    resp = post_process_stream(
        client,
        funded_user_auth_headers,
        filename="gdpr_delete.mp4",
        content=b"content",
    )
    assert resp.status_code == 200
    job_id = resp.json()["id"]

    # 2. Delete Account
    del_resp = client.delete("/auth/me", headers=funded_user_auth_headers)
    assert del_resp.status_code == 200

    # 3. Verify Login Fails
    # We need to try to get a new token because the old token might still seem valid if stateless JWT (unless blacklist checked)
    # But /auth/me should fail if user is gone from DB.
    login_resp = client.get("/auth/me", headers=funded_user_auth_headers)
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


def test_account_deletion_removes_every_local_media_workspace(
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
    upload_paths: list[Path] = []
    artifact_paths: list[Path] = []
    db = Database()
    with db.session() as session:
        for sequence, job_id in enumerate(job_ids):
            extension = (".mp4", ".mov", ".mkv")[sequence % 3]
            video_path = f"artifacts/{job_id}/processed.mp4"
            transcription_path = f"artifacts/{job_id}/transcription.json"
            session.add(
                DbJob(
                    id=job_id,
                    user_id=user_id,
                    status=("completed", "failed", "cancelled")[sequence % 3],
                    created_at=1_800_000_000 + sequence,
                    updated_at=1_800_000_100 + sequence,
                    progress=100,
                    message=None,
                    result_data={
                        "video_path": video_path,
                        "transcription_url": f"/static/{transcription_path}",
                    },
                )
            )
            upload_path = uploads_dir / f"{job_id}_input{extension}"
            upload_path.write_bytes(b"upload")
            job_artifacts = artifacts_dir / job_id
            job_artifacts.mkdir()
            (job_artifacts / "processed.mp4").write_bytes(b"result")
            (job_artifacts / "transcription.json").write_text(
                '[{"start": 0, "end": 1, "text": "private"}]',
                encoding="utf-8",
            )
            upload_paths.append(upload_path)
            artifact_paths.append(job_artifacts)

    unrelated_upload = uploads_dir / "unrelated-job_input.mp4"
    unrelated_artifacts = artifacts_dir / "unrelated-job"
    unrelated_upload.write_bytes(b"keep")
    unrelated_artifacts.mkdir()
    (unrelated_artifacts / "transcription.json").write_text("[]", encoding="utf-8")

    response = client.delete("/auth/me", headers=user_auth_headers)

    assert response.status_code == 200
    # REGRESSION: erasure must enumerate every account job, not the UI's
    # ten-project page, and must remove the complete local workspace including
    # the transcript for completed, failed, and cancelled jobs.
    assert all(not path.exists() for path in upload_paths)
    assert all(not path.exists() for path in artifact_paths)
    with db.session() as session:
        assert all(session.get(DbJob, job_id) is None for job_id in job_ids)
    assert unrelated_upload.is_file()
    assert unrelated_artifacts.is_dir()


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
