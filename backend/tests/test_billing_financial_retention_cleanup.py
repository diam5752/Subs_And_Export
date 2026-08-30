from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingAdjustmentRecord,
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbBillingWithdrawalResolution,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbJob,
    DbUser,
)
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordStore,
    new_contract_confirmation,
)
from backend.app.services.billing_manual_records import (
    new_billing_adjustment_record,
    new_withdrawal_resolution,
)
from backend.app.services.billing_retention import cleanup_expired_billing_records
from backend.app.services.financial_records import financial_retention_deadline
from backend.tests.billing_financial_retention_support import (
    REFERENCE_AT,
    _add_consumer_contract_snapshot,
    _invoice,
    _purchase,
    _seed_user,
)


def test_account_deletion_anonymizes_but_preserves_financial_records(
    client: Any,
) -> None:
    suffix = uuid.uuid4().hex
    test_user_data = {
        "email": f"financial-retention-{suffix}@example.com",
        "password": "testpassword123",
        "name": "Financial Retention",
    }
    register = client.post("/auth/register", json=test_user_data)
    assert register.status_code == 200
    user_id = str(register.json()["id"])
    login = client.post(
        "/auth/token",
        data={
            "username": test_user_data["email"],
            "password": test_user_data["password"],
        },
    )
    token = login.json()["access_token"]

    db = Database()
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        recorded_by_user_id=user_id,
    )
    reversal = DbCreditPurchaseReversal(
        id=uuid.uuid4().hex,
        purchase_id=purchase.id,
        provider="stripe",
        provider_reversal_id=f"re_{uuid.uuid4().hex}",
        provider_event_id=f"evt_{uuid.uuid4().hex}",
        provider_event_created=REFERENCE_AT,
        kind="refund",
        amount_cents=100,
        currency="eur",
        status="succeeded",
        active=True,
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )
    job_id = f"job-{uuid.uuid4().hex}"
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add_all(
            (
                invoice,
                reversal,
                DbJob(
                    id=job_id,
                    user_id=user_id,
                    status="completed",
                    created_at=REFERENCE_AT,
                    updated_at=REFERENCE_AT,
                    progress=100,
                    message=None,
                    result_data=None,
                ),
            )
        )

    response = client.delete(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200

    # REGRESSION: the old CASCADE foreign key erased the only Stripe-to-AADE
    # audit trail when a customer deleted their account.
    with db.session() as session:
        retained_purchase = session.get(DbCreditPurchase, purchase.id)
        retained_invoice = session.get(DbBillingInvoice, invoice.id)
        retained_reversal = session.get(DbCreditPurchaseReversal, reversal.id)
        assert session.get(DbUser, user_id) is None
        assert session.get(DbJob, job_id) is None
        assert retained_purchase is not None
        assert retained_purchase.user_id is None
        assert retained_purchase.account_reference_hash
        assert retained_purchase.payment_snapshot == purchase.payment_snapshot
        assert retained_purchase.customer_snapshot == purchase.customer_snapshot
        assert retained_purchase.tax_snapshot == purchase.tax_snapshot
        assert retained_purchase.financial_retention_until == financial_retention_deadline(REFERENCE_AT)
        assert retained_invoice is not None
        assert retained_invoice.aade_mark == invoice.aade_mark
        # The ID is intentionally detached from users: it is pseudonymous
        # financial-audit evidence, not an email or active account relation.
        assert retained_invoice.recorded_by_user_id == user_id
        assert retained_invoice.recorded_at == REFERENCE_AT
        assert retained_reversal is not None


def test_cleanup_deletes_only_explicitly_terminal_unpaid_attempts() -> None:
    db = Database()
    user_id = _seed_user(db)
    expired = _purchase(user_id=user_id)
    expired.status = "expired"
    expired.fulfilled_at = None
    expired.payment_intent_id = None
    expired.payment_snapshot = None
    expired.customer_snapshot = None
    expired.tax_snapshot = None
    expired.financial_retention_until = REFERENCE_AT + 86_400

    failed = _purchase(user_id=user_id)
    failed.status = "failed"
    open_attempts = [_purchase(user_id=user_id) for _ in range(3)]
    for purchase, status in zip(
        open_attempts,
        ("creating", "checkout_created", "awaiting_payment"),
        strict=True,
    ):
        purchase.status = status
    for purchase in (failed, *open_attempts):
        purchase.fulfilled_at = None
        purchase.payment_intent_id = None
        purchase.payment_snapshot = None
        purchase.customer_snapshot = None
        purchase.tax_snapshot = None
        purchase.financial_retention_until = REFERENCE_AT + 86_400
    with db.session() as session:
        session.add_all((expired, failed, *open_attempts))

    report = cleanup_expired_billing_records(
        db,
        now=REFERENCE_AT + 86_401,
    )

    assert report.deleted_unpaid_attempts >= 2
    with db.session() as session:
        assert session.get(DbCreditPurchase, expired.id) is None
        assert session.get(DbCreditPurchase, failed.id) is None
        assert all(session.get(DbCreditPurchase, purchase.id) is not None for purchase in open_attempts)


@pytest.mark.parametrize(
    "financial_evidence",
    (
        "payment_intent",
        "payment_snapshot",
        "invoice",
        "reversal",
    ),
)
def test_cleanup_never_deletes_terminal_attempt_with_financial_evidence(
    financial_evidence: str,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    purchase.status = "expired"
    purchase.fulfilled_at = None
    purchase.payment_intent_id = None
    purchase.payment_snapshot = None
    purchase.customer_snapshot = None
    purchase.tax_snapshot = None
    purchase.financial_retention_until = REFERENCE_AT + 100
    if financial_evidence == "payment_intent":
        purchase.payment_intent_id = f"pi_{uuid.uuid4().hex}"
    elif financial_evidence == "payment_snapshot":
        purchase.payment_snapshot = {
            "checkout_session_id": purchase.checkout_session_id,
            "payment_intent_id": f"pi_{uuid.uuid4().hex}",
            "paid_amount_cents": 100,
            "currency": "eur",
            "livemode": False,
        }

    with db.session() as session:
        session.add(purchase)
    if financial_evidence == "invoice":
        with db.session() as session:
            session.add(_invoice(purchase_id=purchase.id))
    elif financial_evidence == "reversal":
        with db.session() as session:
            session.add(
                DbCreditPurchaseReversal(
                    id=uuid.uuid4().hex,
                    purchase_id=purchase.id,
                    provider="stripe",
                    provider_reversal_id=f"re_{uuid.uuid4().hex}",
                    provider_event_id=f"evt_{uuid.uuid4().hex}",
                    provider_event_created=REFERENCE_AT,
                    kind="refund",
                    amount_cents=40,
                    currency="eur",
                    status="succeeded",
                    active=True,
                    created_at=REFERENCE_AT,
                    updated_at=REFERENCE_AT,
                )
            )

    with db.session() as session:
        persisted = session.get(DbCreditPurchase, purchase.id)
        assert persisted is not None
        cleanup_at = persisted.financial_retention_until + 1
        invoice = session.scalar(
            select(DbBillingInvoice).where(
                DbBillingInvoice.purchase_id == purchase.id,
            )
        )
        if invoice is not None:
            cleanup_at = max(
                cleanup_at,
                invoice.financial_retention_until + 1,
            )

    cleanup_expired_billing_records(db, now=cleanup_at)

    # The suite intentionally leaves other uniquely identified expired rows
    # for later cleanup, so global report counts are not evidence about this
    # purchase. Assert the exact protected target instead.
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is not None


def test_cleanup_deletes_issued_financial_record_after_retention_deadline() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    deadline = REFERENCE_AT + 100
    purchase.financial_retention_until = deadline
    invoice.financial_retention_until = deadline
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)
    with db.session() as session:
        persisted_purchase = session.get(DbCreditPurchase, purchase.id)
        persisted_invoice = session.get(DbBillingInvoice, invoice.id)
        assert persisted_purchase is not None
        assert persisted_invoice is not None
        persisted_deadline = max(
            persisted_purchase.financial_retention_until,
            persisted_invoice.financial_retention_until,
        )

    # PostgreSQL enforces the statutory minimum even when a caller attempts to
    # insert an artificially short deadline. Exercise cleanup only after the
    # deadline that was actually persisted.
    report = cleanup_expired_billing_records(db, now=persisted_deadline + 1)

    assert report.deleted_unpaid_attempts == 0
    assert report.deleted_financial_records >= 1
    with db.session() as session:
        assert session.get(DbBillingInvoice, invoice.id) is None
        assert session.get(DbCreditPurchase, purchase.id) is None


def test_cleanup_deletes_expired_contract_confirmation_before_purchase() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    _add_consumer_contract_snapshot(purchase)
    invoice = _invoice(purchase_id=purchase.id)
    with db.session() as session:
        session.add(purchase)
        session.flush()
        confirmation = new_contract_confirmation(
            purchase=purchase,
            contract_concluded_at=REFERENCE_AT,
            generated_at=REFERENCE_AT + 1,
        )
        session.add(confirmation)
    with db.session() as session:
        session.add(invoice)
    with db.session() as session:
        stored_purchase = session.get(DbCreditPurchase, purchase.id)
        stored_invoice = session.get(DbBillingInvoice, invoice.id)
        stored_confirmation = session.get(
            DbBillingContractConfirmation,
            confirmation.id,
        )
        assert stored_purchase is not None
        assert stored_invoice is not None
        assert stored_confirmation is not None
        cleanup_at = (
            max(
                stored_purchase.financial_retention_until,
                stored_invoice.financial_retention_until,
                stored_confirmation.financial_retention_until,
            )
            + 1
        )

    report = cleanup_expired_billing_records(db, now=cleanup_at)

    assert report.deleted_financial_records >= 1
    with db.session() as session:
        assert (
            session.get(
                DbBillingContractConfirmation,
                confirmation.id,
            )
            is None
        )
        assert session.get(DbBillingInvoice, invoice.id) is None
        assert session.get(DbCreditPurchase, purchase.id) is None


def test_cleanup_preserves_pending_withdrawal_and_account_vault_evidence() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    _add_consumer_contract_snapshot(purchase)
    invoice = _invoice(purchase_id=purchase.id)
    with db.session() as session:
        session.add(purchase)
        session.flush()
        confirmation = new_contract_confirmation(
            purchase=purchase,
            contract_concluded_at=REFERENCE_AT,
            generated_at=REFERENCE_AT + 1,
        )
        session.add(confirmation)
    with db.session() as session:
        session.add(invoice)
    BillingConsumerRecordStore(db=db).submit_withdrawal(
        user_id=user_id,
        purchase_id=purchase.id,
        idempotency_key=f"withdrawal-{uuid.uuid4().hex}",
        locale="el",
        withdrawal_requested=True,
        confirmed_name="Financial Records",
        confirmation_email=f"{user_id}@example.com",
        submitted_at=REFERENCE_AT + 2,
    )
    with db.session() as session:
        withdrawal = session.scalar(
            select(DbBillingWithdrawalRequest).where(
                DbBillingWithdrawalRequest.purchase_id == purchase.id,
            )
        )
        stored_purchase = session.get(DbCreditPurchase, purchase.id)
        stored_invoice = session.get(DbBillingInvoice, invoice.id)
        stored_confirmation = session.get(
            DbBillingContractConfirmation,
            confirmation.id,
        )
        assert withdrawal is not None
        assert stored_purchase is not None
        assert stored_invoice is not None
        assert stored_confirmation is not None
        cleanup_at = (
            max(
                stored_purchase.financial_retention_until,
                stored_invoice.financial_retention_until,
                stored_confirmation.financial_retention_until,
                withdrawal.financial_retention_until,
            )
            + 1
        )

    report = cleanup_expired_billing_records(db, now=cleanup_at)

    assert report.deleted_financial_records == 0
    with db.session() as session:
        assert session.get(DbCreditPurchase, purchase.id) is not None
        assert session.get(DbBillingInvoice, invoice.id) is not None
        assert (
            session.get(
                DbBillingContractConfirmation,
                confirmation.id,
            )
            is not None
        )
        assert (
            session.get(
                DbBillingWithdrawalRequest,
                withdrawal.id,
            )
            is not None
        )


def test_cleanup_removes_only_a_fully_resolved_expired_withdrawal_graph() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    _add_consumer_contract_snapshot(purchase)
    invoice = _invoice(
        purchase_id=purchase.id,
        recorded_by_user_id=user_id,
    )
    with db.session() as session:
        session.add(purchase)
        session.flush()
        confirmation = new_contract_confirmation(
            purchase=purchase,
            contract_concluded_at=REFERENCE_AT,
            generated_at=REFERENCE_AT + 1,
        )
        session.add(confirmation)
    with db.session() as session:
        session.add(invoice)

    BillingConsumerRecordStore(db=db).submit_withdrawal(
        user_id=user_id,
        purchase_id=purchase.id,
        idempotency_key=f"withdrawal-{uuid.uuid4().hex}",
        locale="el",
        withdrawal_requested=True,
        confirmed_name="Financial Records",
        confirmation_email=f"{user_id}@example.com",
        submitted_at=REFERENCE_AT + 2,
    )
    reversal = DbCreditPurchaseReversal(
        id=uuid.uuid4().hex,
        purchase_id=purchase.id,
        provider="stripe",
        provider_reversal_id=f"re_{uuid.uuid4().hex}",
        provider_event_id=f"evt_{uuid.uuid4().hex}",
        provider_event_created=REFERENCE_AT + 3,
        kind="refund",
        amount_cents=100,
        currency="eur",
        status="succeeded",
        active=True,
        created_at=REFERENCE_AT + 3,
        updated_at=REFERENCE_AT + 3,
    )
    with db.session() as session:
        session.add(reversal)
    adjustment = new_billing_adjustment_record(
        purchase=purchase,
        reversal=reversal,
        document_type="11.4",
        series="RET-1",
        aa="1",
        mark=f"5{uuid.uuid4().int % 10**15:015d}",
        issued_at=REFERENCE_AT + 4,
        actor_user_id=user_id,
        recorded_at=REFERENCE_AT + 5,
    )
    with db.session() as session:
        session.add(adjustment)
    with db.session() as session:
        withdrawal = session.scalar(
            select(DbBillingWithdrawalRequest).where(
                DbBillingWithdrawalRequest.purchase_id == purchase.id,
            )
        )
        stored_adjustment = session.get(
            DbBillingAdjustmentRecord,
            adjustment.id,
        )
        assert withdrawal is not None
        assert stored_adjustment is not None
        resolution = new_withdrawal_resolution(
            withdrawal=withdrawal,
            purchase=purchase,
            decision="accepted_refunded",
            customer_explanation=("The completed refund and AADE adjustment were reviewed."),
            actor_user_id=user_id,
            resolved_at=REFERENCE_AT + 6,
            adjustment=stored_adjustment,
            reversal=reversal,
        )
        session.add(resolution)
    with db.session() as session:
        stored_purchase = session.get(DbCreditPurchase, purchase.id)
        stored_invoice = session.get(DbBillingInvoice, invoice.id)
        stored_confirmation = session.get(
            DbBillingContractConfirmation,
            confirmation.id,
        )
        stored_withdrawal = session.get(
            DbBillingWithdrawalRequest,
            withdrawal.id,
        )
        stored_adjustment = session.get(
            DbBillingAdjustmentRecord,
            adjustment.id,
        )
        stored_resolution = session.get(
            DbBillingWithdrawalResolution,
            resolution.id,
        )
        assert stored_purchase is not None
        assert stored_invoice is not None
        assert stored_confirmation is not None
        assert stored_withdrawal is not None
        assert stored_adjustment is not None
        assert stored_resolution is not None
        cleanup_at = (
            max(
                stored_purchase.financial_retention_until,
                stored_invoice.financial_retention_until,
                stored_confirmation.financial_retention_until,
                stored_withdrawal.financial_retention_until,
                stored_adjustment.financial_retention_until,
                stored_resolution.financial_retention_until,
                financial_retention_deadline(reversal.updated_at),
            )
            + 1
        )

    report = cleanup_expired_billing_records(db, now=cleanup_at)

    assert report.deleted_financial_records >= 1
    with db.session() as session:
        assert session.get(DbBillingWithdrawalResolution, resolution.id) is None
        assert session.get(DbBillingWithdrawalRequest, withdrawal.id) is None
        assert session.get(DbBillingAdjustmentRecord, adjustment.id) is None
        assert session.get(DbBillingContractConfirmation, confirmation.id) is None
        assert session.get(DbCreditPurchaseReversal, reversal.id) is None
        assert session.get(DbBillingInvoice, invoice.id) is None
        assert session.get(DbCreditPurchase, purchase.id) is None
