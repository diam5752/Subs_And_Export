from __future__ import annotations

import time
import uuid
from typing import Any

import pytest
from sqlalchemy import update
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.app.core.database import Database
from backend.app.db.models import (
    DbBillingInvoice,
    DbCreditPurchase,
    DbCreditPurchaseReversal,
)
from backend.app.services.billing_retention import cleanup_expired_billing_records
from backend.app.services.financial_records import financial_retention_deadline
from backend.tests.billing_financial_retention_support import (
    REFERENCE_AT,
    _invoice,
    _purchase,
    _seed_user,
)


def test_billing_invoice_actor_audit_model_is_pseudonymous_and_detached() -> None:
    actor_column = DbBillingInvoice.__table__.c.recorded_by_user_id

    # REGRESSION: tying the operator audit to users with a foreign key would
    # either block account deletion or silently erase statutory audit evidence.
    assert actor_column.nullable is True
    assert not actor_column.foreign_keys
    assert actor_column.type.length == 64
    assert "never stores an email" in str(actor_column.comment)
    assert DbBillingInvoice.__table__.c.recorded_at.nullable is True


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
