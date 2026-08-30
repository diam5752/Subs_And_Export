"""Durability, abuse guards, and delivery tests for product feedback."""

from __future__ import annotations

import time
from collections.abc import Iterator
from email.message import EmailMessage
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import delete, select

from backend.app.core.auth import User
from backend.app.core.database import Database
from backend.app.db.models import DbProductFeedback, DbUser
from backend.app.services.product_feedback import (
    FeedbackInputError,
    FeedbackNotification,
    FeedbackNotificationWorker,
    FeedbackStore,
    SmtpFeedbackNotifier,
    normalize_feedback_message,
    normalize_page_title,
    normalize_source_path,
    run_feedback_worker,
)


@pytest.fixture
def feedback_db() -> Iterator[Database]:
    db = Database()
    with db.session() as session:
        session.execute(delete(DbProductFeedback))
    try:
        yield db
    finally:
        with db.session() as session:
            session.execute(delete(DbProductFeedback))
        db.dispose()


def test_feedback_input_guards_reject_noise_and_preserve_readable_text() -> None:
    assert normalize_feedback_message("  Μια πολύ χρήσιμη ιδέα!  ") == "Μια πολύ χρήσιμη ιδέα!"
    assert normalize_source_path("/account?token=secret#fragment") == "/account"

    with pytest.raises(FeedbackInputError, match="at least 10"):
        normalize_feedback_message("too short")
    with pytest.raises(FeedbackInputError, match="too many links"):
        normalize_feedback_message(
            "Δείτε https://one.example και https://two.example και https://three.example",
        )
    with pytest.raises(FeedbackInputError, match="unsupported control"):
        normalize_feedback_message("Αυτό είναι αρκετό κείμενο\x00 αλλά όχι ασφαλές")
    with pytest.raises(FeedbackInputError, match="cannot exceed 2000"):
        normalize_feedback_message("α" * 2_001)

    assert normalize_source_path("not-a-path") == "/"
    assert normalize_source_path("\x00/private") == "/"
    assert normalize_source_path("https://gsubs.gr") == "/"
    assert normalize_page_title("\x00Private title") == "GSUBS"
    assert normalize_page_title("   ") == "GSUBS"


def test_feedback_store_rejects_weak_secret_and_unknown_category(
    feedback_db: Database,
) -> None:
    with pytest.raises(RuntimeError, match="dedicated stable hash secret"):
        FeedbackStore(feedback_db, hash_secret="too-short")

    store = FeedbackStore(feedback_db, hash_secret="s" * 64)
    with pytest.raises(FeedbackInputError, match="Unsupported feedback category"):
        store.submit(
            category="unknown",  # type: ignore[arg-type]
            message="Αυτό είναι ένα αρκετά μεγάλο μήνυμα.",
            source_path="/",
            page_title="GSUBS",
            submitter=None,
            client_ip="203.0.113.11",
        )


def test_store_persists_first_and_suppresses_rolling_day_duplicates(
    feedback_db: Database,
) -> None:
    store = FeedbackStore(feedback_db, hash_secret="s" * 64)
    first = store.submit(
        category="idea",
        message="Θα βοηθούσε πολύ μια επιλογή για templates.",
        source_path="/?checkout=secret",
        page_title="GSUBS Studio",
        submitter=None,
        client_ip="203.0.113.10",
        now=1_800_000_000,
    )
    duplicate = store.submit(
        category="idea",
        message="  Θα βοηθούσε πολύ μια επιλογή για templates.  ",
        source_path="/different",
        page_title="Different title",
        submitter=None,
        client_ip="203.0.113.10",
        now=1_800_000_100,
    )

    assert duplicate.id == first.id
    assert duplicate.duplicate is True
    with feedback_db.session() as session:
        rows = session.scalars(select(DbProductFeedback)).all()
        assert len(rows) == 1
        assert rows[0].source_path == "/"
        assert rows[0].notification_status == "pending"


def test_signed_in_feedback_is_linked_without_storing_raw_network_identity(
    feedback_db: Database,
) -> None:
    submitter = User(
        id="feedback-user",
        email="feedback@example.com",
        name="Feedback User",
        provider="local",
    )
    with feedback_db.session() as session:
        from backend.app.db.models import DbUser

        session.merge(
            DbUser(
                id=submitter.id,
                email=submitter.email,
                name=submitter.name,
                provider=submitter.provider,
                password_hash=None,
                google_sub=None,
                avatar_url=None,
                created_at="2026-08-27T00:00:00Z",
                email_verified=True,
            ),
        )

    receipt = FeedbackStore(feedback_db, hash_secret="s" * 64).submit(
        category="bug",
        message="Το κουμπί export δεν απαντά στην πρώτη προσπάθεια.",
        source_path="/",
        page_title="GSUBS Studio",
        submitter=submitter,
        client_ip="198.51.100.2",
    )

    with feedback_db.session() as session:
        row = session.get(DbProductFeedback, receipt.id)
        assert row is not None
        assert row.submitter_user_id == submitter.id
        assert row.submitter_key_hash != submitter.id
        assert "198.51.100.2" not in row.submitter_key_hash


def test_notification_worker_retries_without_losing_feedback_or_error_details(
    feedback_db: Database,
) -> None:
    now = 1_800_100_000
    store = FeedbackStore(feedback_db, hash_secret="s" * 64)
    receipt = store.submit(
        category="complaint",
        message="Η διαδικασία χρειάζεται πιο καθαρή ενημέρωση προόδου.",
        source_path="/",
        page_title="GSUBS Studio",
        submitter=None,
        client_ip="203.0.113.20",
        now=now,
    )
    notifier = Mock()
    notifier.send.side_effect = RuntimeError("smtp secret should never persist")
    worker = FeedbackNotificationWorker(
        store=store,
        notifier=notifier,
        retention_days=180,
        now=lambda: now,
    )

    assert worker.process_once() == 0
    with feedback_db.session() as session:
        row = session.get(DbProductFeedback, receipt.id)
        assert row is not None
        assert row.notification_status == "pending"
        assert row.notification_attempts == 1
        assert row.notification_next_attempt_at > now
        assert row.notification_last_error_code == "RuntimeError"
        assert "secret" not in row.notification_last_error_code

    retry_at = now + 120
    worker = FeedbackNotificationWorker(
        store=store,
        notifier=Mock(),
        retention_days=180,
        now=lambda: retry_at,
    )
    assert worker.process_once() == 1
    with feedback_db.session() as session:
        row = session.get(DbProductFeedback, receipt.id)
        assert row is not None
        assert row.notification_status == "sent"
        assert row.notification_sent_at == retry_at
        assert row.notification_last_error_code is None


def test_stale_worker_receipts_cannot_overwrite_a_newer_notification_lease(
    feedback_db: Database,
) -> None:
    now = 1_800_200_000
    store = FeedbackStore(feedback_db, hash_secret="s" * 64)
    receipt = store.submit(
        category="chat",
        message="Θέλω να συζητήσουμε αυτή τη συγκεκριμένη λειτουργία.",
        source_path="/",
        page_title="GSUBS",
        submitter=None,
        client_ip="203.0.113.30",
        now=now,
    )
    notification = store.claim_due_notifications(
        now=now,
        batch_size=1,
        not_older_than=0,
    )[0]

    store.mark_notification_sent(
        receipt.id,
        attempt_number=notification.attempt_number + 1,
        now=now + 1,
    )
    store.mark_notification_failed(
        receipt.id,
        attempt_number=notification.attempt_number + 1,
        now=now + 1,
        error_code="StaleWorker",
    )

    with feedback_db.session() as session:
        row = session.get(DbProductFeedback, receipt.id)
        assert row is not None
        assert row.notification_status == "sending"
        assert row.notification_attempts == notification.attempt_number
        assert row.notification_last_error_code is None


def test_worker_purges_expired_queue_before_delivery_and_preserves_active_lease(
    feedback_db: Database,
) -> None:
    now = 1_800_300_000
    store = FeedbackStore(feedback_db, hash_secret="s" * 64)
    old_pending = store.submit(
        category="idea",
        message="Παλαιό feedback που μπορεί πλέον να διαγραφεί με ασφάλεια.",
        source_path="/",
        page_title="GSUBS",
        submitter=None,
        client_ip="203.0.113.40",
        now=now - (3 * 86_400),
    )
    stale_lease = store.submit(
        category="bug",
        message="Παλαιό feedback με ληγμένη δέσμευση από worker.",
        source_path="/",
        page_title="GSUBS",
        submitter=None,
        client_ip="203.0.113.41",
        now=now - (3 * 86_400) + 1,
    )
    active_lease = store.submit(
        category="complaint",
        message="Παλαιό feedback με ενεργή δέσμευση που δεν πρέπει να χαθεί.",
        source_path="/",
        page_title="GSUBS",
        submitter=None,
        client_ip="203.0.113.42",
        now=now - (3 * 86_400) + 2,
    )
    with feedback_db.session() as session:
        stale_row = session.get(DbProductFeedback, stale_lease.id)
        active_row = session.get(DbProductFeedback, active_lease.id)
        assert stale_row is not None
        assert active_row is not None
        stale_row.notification_status = "sending"
        stale_row.notification_attempts = 1
        stale_row.notification_next_attempt_at = now - 1
        active_row.notification_status = "sending"
        active_row.notification_attempts = 1
        active_row.notification_next_attempt_at = now + 60

    notifier = Mock()
    worker = FeedbackNotificationWorker(
        store=store,
        notifier=notifier,
        retention_days=1,
        now=lambda: now,
    )
    store.assert_queue_available()
    assert worker.process_once() == 0
    notifier.send.assert_not_called()
    with feedback_db.session() as session:
        assert session.get(DbProductFeedback, old_pending.id) is None
        assert session.get(DbProductFeedback, stale_lease.id) is None
        assert session.get(DbProductFeedback, active_lease.id) is not None


def test_claimed_signed_in_feedback_is_not_delivered_after_account_deletion(
    feedback_db: Database,
) -> None:
    now = 1_800_400_000
    submitter = User(
        id="deleted-feedback-user",
        email="deleted-feedback@example.com",
        name="Deleted Feedback User",
        provider="local",
    )
    with feedback_db.session() as session:
        session.add(
            DbUser(
                id=submitter.id,
                email=submitter.email,
                name=submitter.name,
                provider=submitter.provider,
                password_hash=None,
                google_sub=None,
                avatar_url=None,
                created_at="2026-08-27T00:00:00Z",
                email_verified=True,
            ),
        )
    store = FeedbackStore(feedback_db, hash_secret="s" * 64)
    receipt = store.submit(
        category="chat",
        message="Αυτό το μήνυμα δεν πρέπει να σταλεί μετά τη διαγραφή.",
        source_path="/",
        page_title="GSUBS",
        submitter=submitter,
        client_ip="203.0.113.50",
        now=now,
    )
    notification = store.claim_due_notifications(
        now=now,
        batch_size=1,
        not_older_than=0,
    )[0]
    with feedback_db.session() as session:
        user = session.get(DbUser, submitter.id)
        assert user is not None
        session.delete(user)

    notifier = Mock()
    assert (
        store.deliver_notification(
            notification,
            notifier=notifier,
            now=now + 1,
        )
        is False
    )
    notifier.send.assert_not_called()
    with feedback_db.session() as session:
        assert session.get(DbProductFeedback, receipt.id) is None


def test_smtp_notifier_uses_starttls_and_keeps_feedback_out_of_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[EmailMessage] = []

    class FakeSmtp:
        def __init__(self, host: str, port: int, timeout: float) -> None:
            assert (host, port, timeout) == ("smtp.example.com", 587, 15.0)

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def ehlo(self) -> None:
            return None

        def starttls(self, *, context: object) -> None:
            assert context is not None

        def login(self, username: str, password: str) -> None:
            assert (username, password) == ("mailer", "smtp-password")

        def send_message(self, message: EmailMessage) -> None:
            sent_messages.append(message)

    monkeypatch.setattr("backend.app.services.product_feedback.smtplib.SMTP", FakeSmtp)
    notifier = SmtpFeedbackNotifier(
        host="smtp.example.com",
        port=587,
        username="mailer",
        password="smtp-password",
        mail_from="GSUBS <support@example.com>",
        recipient="owner@example.com",
        timeout_seconds=15,
    )
    notifier.send(
        FeedbackNotification(
            id="feedback-id",
            category="bug",
            message="Subject: injected\nBcc: attacker@example.com\nΤο export κόλλησε.",
            source_path="/",
            page_title="GSUBS",
            created_at=int(time.time()),
            attempt_number=1,
            submitter_user_id=None,
            submitter_email=None,
            submitter_name=None,
        ),
    )

    assert len(sent_messages) == 1
    message = sent_messages[0]
    assert message["To"] == "owner@example.com"
    assert "injected" not in str(message["Subject"])
    assert message["Bcc"] is None
    assert "Bcc: attacker@example.com" in message.get_content()


def test_feedback_worker_loop_redacts_errors_and_keeps_polling(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class StopLoop(Exception):
        pass

    worker = SimpleNamespace(process_once=Mock(side_effect=RuntimeError("smtp-password")))
    monkeypatch.setattr(
        "backend.app.services.product_feedback.time.sleep",
        Mock(side_effect=StopLoop),
    )

    with pytest.raises(StopLoop):
        run_feedback_worker(worker=worker, poll_seconds=5)  # type: ignore[arg-type]

    assert worker.process_once.call_count == 1
    assert "Feedback worker iteration failed" in caplog.text
    assert "smtp-password" not in caplog.text
