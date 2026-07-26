from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingContractConfirmation,
    DbBillingInvoice,
    DbBillingWithdrawalRequest,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
    DbJob,
    DbUser,
)
from backend.app.services.billing_consumer_records import (
    BillingConsumerRecordStore,
    new_contract_confirmation,
)
from backend.app.services.billing_retention import cleanup_expired_billing_records
from backend.app.services.consumer_contracts import (
    ConsumerContractAcceptance,
    build_consumer_contract_snapshot,
    consumer_contract_snapshot_sha256,
    public_consumer_contract,
)
from backend.app.services.financial_records import financial_retention_deadline

REFERENCE_AT = 1_577_836_800


def _purchase(
    *,
    user_id: str,
    suffix: str | None = None,
) -> DbCreditPurchase:
    resolved_suffix = suffix or uuid.uuid4().hex
    return DbCreditPurchase(
        id=resolved_suffix[:32],
        user_id=user_id,
        provider="stripe",
        package_key="starter",
        credits=100,
        amount_eur_cents=100,
        currency="eur",
        idempotency_key=f"billing-{resolved_suffix}"[:64],
        checkout_session_id=f"cs_test_{resolved_suffix}",
        checkout_url=None,
        payment_intent_id=f"pi_{resolved_suffix}",
        integration_identifier=f"gsubs_credits_{resolved_suffix[:8]}",
        status="paid",
        fulfilled_at=REFERENCE_AT,
        refunded_amount_cents=0,
        dispute_active=False,
        reversed_credits=0,
        reversal_debt_credits=0,
        reversed_amount_cents=0,
        snapshot={
            "catalog_version": "test",
            "package_key": "starter",
            "credits": 100,
            "amount_eur_cents": 100,
            "currency": "eur",
        },
        payment_snapshot={
            "checkout_session_id": f"cs_test_{resolved_suffix}",
            "payment_intent_id": f"pi_{resolved_suffix}",
            "paid_amount_cents": 100,
            "currency": "eur",
            "livemode": False,
        },
        customer_snapshot={
            "name": "Accounting Customer",
            "email": f"{resolved_suffix}@example.com",
            "country": "GR",
        },
        tax_snapshot={
            "tax_behavior": "inclusive",
            "tax_rate_basis_points": 2400,
            "automatic_tax": False,
        },
        error=None,
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )


def _invoice(
    *,
    purchase_id: str,
    suffix: str | None = None,
    document_status: str = "issued",
    recorded_by_user_id: str | None = None,
) -> DbBillingInvoice:
    resolved_suffix = suffix or uuid.uuid4().hex
    has_aade_identity = document_status in {"issued", "cancelled"}
    resolved_recorder = recorded_by_user_id or resolved_suffix
    return DbBillingInvoice(
        id=resolved_suffix[:32],
        purchase_id=purchase_id,
        provider="aade_etimologio",
        document_kind="retail_service_receipt",
        document_status=document_status,
        aade_document_type="11.2" if has_aade_identity else None,
        aade_series="0" if has_aade_identity else None,
        aade_aa=resolved_suffix[:12] if has_aade_identity else None,
        aade_mark=f"4{resolved_suffix[:15]}" if has_aade_identity else None,
        issued_at=REFERENCE_AT if has_aade_identity else None,
        recorded_by_user_id=resolved_recorder if has_aade_identity else None,
        recorded_at=REFERENCE_AT if has_aade_identity else None,
        document_snapshot={
            "description": "GSUBS Credits",
            "gross_amount_cents": 100,
            "currency": "eur",
            "tax_behavior": "inclusive",
        },
        financial_retention_until=financial_retention_deadline(REFERENCE_AT),
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )


def _seed_user(db: Database) -> str:
    suffix = uuid.uuid4().hex
    user_id = suffix[:32]
    with db.session() as session:
        session.add(
            DbUser(
                id=user_id,
                email=f"{suffix}@example.com",
                name="Financial Records",
                provider="local",
                password_hash="x",
                google_sub=None,
                avatar_url=None,
                created_at="now",
                email_verified=True,
            )
        )
    return user_id


def test_billing_invoice_actor_audit_model_is_pseudonymous_and_detached() -> None:
    actor_column = DbBillingInvoice.__table__.c.recorded_by_user_id

    # REGRESSION: tying the operator audit to users with a foreign key would
    # either block account deletion or silently erase statutory audit evidence.
    assert actor_column.nullable is True
    assert not actor_column.foreign_keys
    assert actor_column.type.length == 64
    assert "never stores an email" in str(actor_column.comment)
    assert DbBillingInvoice.__table__.c.recorded_at.nullable is True


def _add_consumer_contract_snapshot(
    purchase: DbCreditPurchase,
) -> None:
    disclosure = public_consumer_contract("el")
    consumer_contract = build_consumer_contract_snapshot(
        ConsumerContractAcceptance(
            catalog_version="test",
            disclosure_id=str(disclosure["disclosure_id"]),
            disclosure_sha256=str(disclosure["disclosure_sha256"]),
            locale="el",
            policy_version=str(disclosure["policy_version"]),
            terms_version=str(disclosure["terms_version"]),
            withdrawal_notice_version=str(
                disclosure["withdrawal_notice_version"],
            ),
            terms_accepted=True,
            immediate_performance_requested=True,
            withdrawal_consequences_acknowledged=True,
        ),
        expected_catalog_version="test",
        accepted_at=REFERENCE_AT,
    )
    purchase.snapshot = {
        **purchase.snapshot,
        "consumer_contract": consumer_contract,
        "consumer_contract_sha256": (consumer_contract_snapshot_sha256(consumer_contract)),
    }


@pytest.mark.parametrize("invalid_now", (True, 0, -1))
def test_cleanup_rejects_invalid_retention_cutoff(
    invalid_now: int,
) -> None:
    with pytest.raises(ValueError, match="retention cutoff"):
        cleanup_expired_billing_records(
            Database(),
            now=invalid_now,
        )


def test_cleanup_rejects_future_retention_cutoff() -> None:
    with pytest.raises(ValueError, match="future"):
        cleanup_expired_billing_records(
            Database(),
            now=int(time.time()) + 60,
        )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("snapshot", {"package_key": "changed"}),
        ("payment_snapshot", {"paid_amount_cents": 999}),
        ("customer_snapshot", {"email": "changed@example.com"}),
        ("tax_snapshot", {"tax_rate_basis_points": 0}),
        ("account_reference_hash", "changed"),
    ),
)
def test_purchase_snapshots_are_write_once(
    field: str,
    replacement: Any,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    with db.session() as session:
        session.add(purchase)

    # REGRESSION: accounting snapshots must not silently change when catalog,
    # customer, or tax defaults change after a completed purchase.
    with pytest.raises(DBAPIError, match="immutable"):
        with db.session() as session:
            session.execute(
                update(DbCreditPurchase).where(DbCreditPurchase.id == purchase.id).values({field: replacement})
            )


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("aade_document_type", "1.1"),
        ("aade_series", "NEW"),
        ("aade_aa", "999"),
        ("aade_mark", "499999999999999"),
        ("issued_at", REFERENCE_AT + 1),
        ("recorded_by_user_id", uuid.uuid4().hex),
        ("recorded_at", REFERENCE_AT + 1),
        ("document_snapshot", {"gross_amount_cents": 999}),
        ("provider", "different_provider"),
        ("document_kind", "different_document_kind"),
    ),
)
def test_issued_aade_identifiers_are_write_once(
    field: str,
    replacement: Any,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)

    # REGRESSION: a manual AADE link may be filled once, but an issued
    # series/AA/MARK/timestamp must never be overwritten later.
    with pytest.raises(DBAPIError, match="immutable"):
        with db.session() as session:
            session.execute(
                update(DbBillingInvoice).where(DbBillingInvoice.id == invoice.id).values({field: replacement})
            )


def test_pending_invoice_accepts_exactly_one_complete_aade_link() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status="pending_manual_issue",
    )
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)

    retained_until = financial_retention_deadline(REFERENCE_AT)
    aade_aa = uuid.uuid4().hex[:12]
    aade_mark = f"4{uuid.uuid4().hex[:15]}"
    with db.session() as session:
        session.execute(
            update(DbBillingInvoice)
            .where(DbBillingInvoice.id == invoice.id)
            .values(
                document_status="issued",
                aade_document_type="11.2",
                aade_series="0",
                aade_aa=aade_aa,
                aade_mark=aade_mark,
                issued_at=REFERENCE_AT,
                recorded_by_user_id=user_id,
                recorded_at=REFERENCE_AT,
                financial_retention_until=retained_until,
                updated_at=REFERENCE_AT,
            )
        )

    with db.session() as session:
        linked = session.get(DbBillingInvoice, invoice.id)
        assert linked is not None
        assert linked.document_status == "issued"
        assert linked.aade_document_type == "11.2"
        assert linked.aade_series == "0"
        assert linked.aade_aa == aade_aa
        assert linked.aade_mark == aade_mark
        assert linked.issued_at == REFERENCE_AT
        assert linked.recorded_by_user_id == user_id
        assert linked.recorded_at == REFERENCE_AT


def test_invoice_retention_clamps_deliberately_short_non_null_value() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    invoice.financial_retention_until = 1
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)

    with db.session() as session:
        stored = session.get(DbBillingInvoice, invoice.id)
        assert stored is not None
        assert stored.financial_retention_until == financial_retention_deadline(
            REFERENCE_AT,
        )


def test_invoice_retention_includes_later_actor_recording_timestamp() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    later_recorded_at = REFERENCE_AT + 366 * 24 * 60 * 60
    invoice.recorded_at = later_recorded_at
    invoice.financial_retention_until = 1
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)

    with db.session() as session:
        stored = session.get(DbBillingInvoice, invoice.id)
        assert stored is not None
        # The audit itself cannot expire earlier than the financial record
        # derived from the server-side time at which it was attached.
        assert stored.financial_retention_until == financial_retention_deadline(
            later_recorded_at,
        )


@pytest.mark.parametrize(
    ("initial_status", "replacement_status"),
    (
        ("pending_manual_issue", "manual_review_required"),
        ("manual_review_required", "pending_manual_issue"),
        ("issued", "pending_manual_issue"),
        ("issued", "cancelled"),
        ("cancelled", "issued"),
    ),
)
def test_invoice_rejects_non_monotonic_status_transition(
    initial_status: str,
    replacement_status: str,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status=initial_status,
    )
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)

    with pytest.raises(DBAPIError, match="transition is invalid"):
        with db.session() as session:
            session.execute(
                update(DbBillingInvoice)
                .where(DbBillingInvoice.id == invoice.id)
                .values(document_status=replacement_status)
            )


def test_invoice_rejects_unknown_document_status() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status="unexpected",
    )
    with db.session() as session:
        session.add(purchase)
    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(invoice)


@pytest.mark.parametrize(
    "blank_field",
    (
        "aade_document_type",
        "aade_series",
        "aade_aa",
        "aade_mark",
        "recorded_by_user_id",
    ),
)
def test_invoice_rejects_blank_terminal_aade_identity(
    blank_field: str,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status="pending_manual_issue",
    )
    terminal_identity: dict[str, Any] = {
        "document_status": "issued",
        "aade_document_type": "11.2",
        "aade_series": "0",
        "aade_aa": uuid.uuid4().hex[:12],
        "aade_mark": f"4{uuid.uuid4().hex[:15]}",
        "issued_at": REFERENCE_AT,
        "recorded_by_user_id": user_id,
        "recorded_at": REFERENCE_AT,
    }
    terminal_identity[blank_field] = "   "
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(invoice)

    with pytest.raises(DBAPIError):
        with db.session() as session:
            session.execute(
                update(DbBillingInvoice).where(DbBillingInvoice.id == invoice.id).values(**terminal_identity)
            )


def test_financial_retention_deadline_can_extend_but_never_shorten() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    with db.session() as session:
        session.add(purchase)

    original_deadline = financial_retention_deadline(REFERENCE_AT)
    extended_deadline = financial_retention_deadline(REFERENCE_AT + 366 * 24 * 3600)
    with db.session() as session:
        session.execute(
            update(DbCreditPurchase)
            .where(DbCreditPurchase.id == purchase.id)
            .values(financial_retention_until=extended_deadline)
        )

    with pytest.raises(DBAPIError, match="cannot be shortened"):
        with db.session() as session:
            session.execute(
                update(DbCreditPurchase)
                .where(DbCreditPurchase.id == purchase.id)
                .values(financial_retention_until=original_deadline)
            )


def test_invoice_cannot_be_marked_issued_without_complete_aade_identity() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status="pending_manual_issue",
    )
    invoice.document_status = "issued"
    with db.session() as session:
        session.add(purchase)
    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(invoice)


@pytest.mark.parametrize(
    "missing_audit_field",
    ("recorded_by_user_id", "recorded_at"),
)
@pytest.mark.parametrize("document_status", ("issued", "cancelled"))
def test_invoice_terminal_state_requires_complete_actor_audit(
    missing_audit_field: str,
    document_status: str,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status=document_status,
    )
    setattr(invoice, missing_audit_field, None)
    with db.session() as session:
        session.add(purchase)

    # REGRESSION: a terminal AADE link without who recorded it and when cannot
    # provide a durable manual-reconciliation audit trail.
    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(invoice)


def test_pending_invoice_rejects_premature_actor_audit() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(
        purchase_id=purchase.id,
        document_status="pending_manual_issue",
    )
    invoice.recorded_by_user_id = user_id
    invoice.recorded_at = REFERENCE_AT
    with db.session() as session:
        session.add(purchase)

    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(invoice)


def test_invoice_actor_audit_rejects_email_or_non_internal_identifier() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    invoice = _invoice(purchase_id=purchase.id)
    invoice.recorded_by_user_id = "operator@example.com"
    with db.session() as session:
        session.add(purchase)

    # The durable actor key is pseudonymous by contract; direct contact data
    # such as an email must never enter this financial-audit field.
    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(invoice)


def test_reversal_provider_identity_is_unique_per_purchase_provider() -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
    reversal_id = f"dp_{uuid.uuid4().hex}"
    first = DbCreditPurchaseReversal(
        id=uuid.uuid4().hex,
        purchase_id=purchase.id,
        provider="stripe",
        provider_reversal_id=reversal_id,
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
        session.add(first)

    duplicate = DbCreditPurchaseReversal(
        id=uuid.uuid4().hex,
        purchase_id=purchase.id,
        provider="stripe",
        provider_reversal_id=reversal_id,
        provider_event_id=f"evt_{uuid.uuid4().hex}",
        provider_event_created=REFERENCE_AT + 1,
        kind="dispute",
        amount_cents=100,
        currency="eur",
        status="won",
        active=False,
        created_at=REFERENCE_AT + 1,
        updated_at=REFERENCE_AT + 1,
    )
    with pytest.raises(IntegrityError):
        with db.session() as session:
            session.add(duplicate)


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    (
        (
            "created_at",
            REFERENCE_AT + 1,
            "created_at is immutable",
        ),
        (
            "provider_event_created",
            REFERENCE_AT - 1,
            "provider_event_created cannot move backwards",
        ),
        (
            "updated_at",
            REFERENCE_AT - 1,
            "updated_at cannot move backwards",
        ),
    ),
)
def test_reversal_retention_timestamps_cannot_move_backwards(
    field: str,
    replacement: int,
    message: str,
) -> None:
    db = Database()
    user_id = _seed_user(db)
    purchase = _purchase(user_id=user_id)
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
        status="succeeded",
        active=True,
        created_at=REFERENCE_AT,
        updated_at=REFERENCE_AT,
    )
    with db.session() as session:
        session.add(purchase)
    with db.session() as session:
        session.add(reversal)

    # REGRESSION: reversal retention is derived from these timestamps. If a
    # later writer can backdate them, cleanup can erase evidence early.
    with pytest.raises(DBAPIError, match=message):
        with db.session() as session:
            session.execute(
                update(DbCreditPurchaseReversal)
                .where(DbCreditPurchaseReversal.id == reversal.id)
                .values({field: replacement})
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
