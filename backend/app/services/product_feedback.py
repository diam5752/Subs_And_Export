"""Durable product feedback, duplicate suppression, and SMTP delivery."""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import smtplib
import ssl
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal, Protocol, cast
from urllib.parse import urlsplit

from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from backend.app.core.auth import User
from backend.app.core.database import Database
from backend.app.db.models import DbProductFeedback, DbUser

logger = logging.getLogger(__name__)

FeedbackCategory = Literal["idea", "bug", "complaint", "chat"]
FEEDBACK_CATEGORIES = frozenset({"idea", "bug", "complaint", "chat"})
FEEDBACK_MIN_MESSAGE_CHARS = 10
FEEDBACK_MAX_MESSAGE_CHARS = 2_000
FEEDBACK_DUPLICATE_WINDOW_SECONDS = 24 * 60 * 60
FEEDBACK_NOTIFICATION_LEASE_SECONDS = 90
_URL_PATTERN = re.compile(r"(?:https?://|www\.)", re.IGNORECASE)
_CONTROL_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_CATEGORY_LABELS = {
    "idea": "Ιδέα",
    "bug": "Bug",
    "complaint": "Παράπονο",
    "chat": "Κουβέντα",
}


class FeedbackInputError(ValueError):
    """Raised for a public-safe feedback validation failure."""


@dataclass(frozen=True, slots=True)
class FeedbackReceipt:
    id: str
    duplicate: bool


@dataclass(frozen=True, slots=True)
class FeedbackNotification:
    id: str
    category: FeedbackCategory
    message: str
    source_path: str
    page_title: str
    created_at: int
    attempt_number: int
    submitter_user_id: str | None
    submitter_email: str | None
    submitter_name: str | None


class FeedbackNotifier(Protocol):
    def send(self, notification: FeedbackNotification) -> None:
        """Deliver one feedback notification or raise on failure."""


def normalize_feedback_message(value: str) -> str:
    """Normalize readable text and reject common abuse payloads."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    if len(normalized) < FEEDBACK_MIN_MESSAGE_CHARS:
        raise FeedbackInputError(
            f"Feedback must contain at least {FEEDBACK_MIN_MESSAGE_CHARS} characters.",
        )
    if len(normalized) > FEEDBACK_MAX_MESSAGE_CHARS:
        raise FeedbackInputError(
            f"Feedback cannot exceed {FEEDBACK_MAX_MESSAGE_CHARS} characters.",
        )
    if _CONTROL_PATTERN.search(normalized):
        raise FeedbackInputError("Feedback contains an unsupported control character.")
    if len(_URL_PATTERN.findall(normalized)) > 2:
        raise FeedbackInputError("Feedback contains too many links.")
    return normalized


def normalize_source_path(value: str) -> str:
    """Keep only a same-site path; queries and fragments can contain secrets."""
    normalized = unicodedata.normalize("NFKC", value).strip()
    if _CONTROL_PATTERN.search(normalized):
        return "/"
    parsed = urlsplit(normalized)
    path = parsed.path if parsed.path.startswith("/") else "/"
    return path[:512]


def normalize_page_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if _CONTROL_PATTERN.search(normalized):
        return "GSUBS"
    return normalized[:255] or "GSUBS"


def _digest(secret: str, purpose: str, value: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{purpose}:{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _advisory_lock_key(actor_hash: str, message_hash: str) -> int:
    raw = hashlib.sha256(f"{actor_hash}:{message_hash}".encode("ascii")).digest()[:8]
    return int.from_bytes(raw, byteorder="big", signed=True)


def _account_delivery_lock_key(user_id: str) -> int:
    raw = hashlib.sha256(
        f"feedback-account-delivery-v1:{user_id}".encode("utf-8"),
    ).digest()[:8]
    return int.from_bytes(raw, byteorder="big", signed=True)


def acquire_feedback_account_delivery_lock(session: Session, user_id: str) -> None:
    """Serialize signed-in feedback creation/delivery with account erasure."""
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": _account_delivery_lock_key(user_id)},
    )


class FeedbackStore:
    """Persist messages before delivery and coordinate retry workers."""

    def __init__(self, db: Database, *, hash_secret: str | None = None) -> None:
        if hash_secret is not None and len(hash_secret.strip()) < 32:
            raise RuntimeError("FeedbackStore requires a dedicated stable hash secret")
        self.db = db
        self.hash_secret = hash_secret.strip() if hash_secret is not None else None

    def submit(
        self,
        *,
        category: FeedbackCategory,
        message: str,
        source_path: str,
        page_title: str,
        submitter: User | None,
        client_ip: str,
        now: int | None = None,
    ) -> FeedbackReceipt:
        """Create one inbox row, or return the rolling-day duplicate."""
        if self.hash_secret is None:
            raise RuntimeError("Feedback submission requires a dedicated stable hash secret")
        if category not in FEEDBACK_CATEGORIES:
            raise FeedbackInputError("Unsupported feedback category.")
        normalized_message = normalize_feedback_message(message)
        normalized_path = normalize_source_path(source_path)
        normalized_title = normalize_page_title(page_title)
        created_at = int(time.time()) if now is None else int(now)
        actor_identity = f"user:{submitter.id}" if submitter is not None else f"ip:{client_ip.strip() or 'unknown'}"
        actor_hash = _digest(self.hash_secret, "actor", actor_identity)
        message_hash = _digest(self.hash_secret, "message", normalized_message.casefold())

        with self.db.session() as session:
            if submitter is not None:
                acquire_feedback_account_delivery_lock(session, submitter.id)
                if session.get(DbUser, submitter.id) is None:
                    raise FeedbackInputError("Your account is no longer available.")
            # Every identical actor/message pair takes one transaction lock, so
            # concurrent API workers cannot race the rolling-window check.
            session.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"),
                {"lock_key": _advisory_lock_key(actor_hash, message_hash)},
            )
            existing = session.scalar(
                select(DbProductFeedback)
                .where(
                    DbProductFeedback.submitter_key_hash == actor_hash,
                    DbProductFeedback.message_hash == message_hash,
                    DbProductFeedback.created_at >= created_at - FEEDBACK_DUPLICATE_WINDOW_SECONDS,
                )
                .order_by(DbProductFeedback.created_at.desc())
                .limit(1),
            )
            if existing is not None:
                return FeedbackReceipt(id=existing.id, duplicate=True)

            feedback_id = secrets.token_hex(16)
            session.add(
                DbProductFeedback(
                    id=feedback_id,
                    category=category,
                    status="new",
                    message=normalized_message,
                    source_path=normalized_path,
                    page_title=normalized_title,
                    submitter_user_id=submitter.id if submitter is not None else None,
                    submitter_key_hash=actor_hash,
                    message_hash=message_hash,
                    dedupe_day=created_at // 86_400,
                    created_at=created_at,
                    notification_status="pending",
                    notification_attempts=0,
                    notification_next_attempt_at=created_at,
                    notification_sent_at=None,
                    notification_last_error_code=None,
                ),
            )
            session.flush()
            return FeedbackReceipt(id=feedback_id, duplicate=False)

    def claim_due_notifications(
        self,
        *,
        now: int,
        batch_size: int,
        not_older_than: int,
    ) -> list[FeedbackNotification]:
        """Lease due outbox rows without holding a DB lock during SMTP I/O."""
        with self.db.session() as session:
            rows = session.scalars(
                select(DbProductFeedback)
                .where(
                    DbProductFeedback.notification_status.in_(("pending", "sending")),
                    DbProductFeedback.notification_next_attempt_at <= now,
                    DbProductFeedback.created_at >= not_older_than,
                )
                .order_by(
                    DbProductFeedback.notification_next_attempt_at.asc(),
                    DbProductFeedback.created_at.asc(),
                    DbProductFeedback.id.asc(),
                )
                .with_for_update(skip_locked=True)
                .limit(batch_size),
            ).all()
            notifications: list[FeedbackNotification] = []
            for row in rows:
                row.notification_status = "sending"
                row.notification_attempts += 1
                row.notification_next_attempt_at = now + FEEDBACK_NOTIFICATION_LEASE_SECONDS
                notifications.append(
                    FeedbackNotification(
                        id=row.id,
                        category=cast(FeedbackCategory, row.category),
                        message=row.message,
                        source_path=row.source_path,
                        page_title=row.page_title,
                        created_at=row.created_at,
                        attempt_number=row.notification_attempts,
                        submitter_user_id=row.submitter_user_id,
                        submitter_email=None,
                        submitter_name=None,
                    ),
                )
            return notifications

    def deliver_notification(
        self,
        notification: FeedbackNotification,
        *,
        notifier: FeedbackNotifier,
        now: int,
    ) -> bool:
        """Send and acknowledge one current lease behind its privacy barriers."""
        with self.db.session() as session:
            if notification.submitter_user_id is not None:
                acquire_feedback_account_delivery_lock(
                    session,
                    notification.submitter_user_id,
                )
            row = session.scalar(
                select(DbProductFeedback).where(DbProductFeedback.id == notification.id).with_for_update(),
            )
            if (
                row is None
                or row.notification_status != "sending"
                or row.notification_attempts != notification.attempt_number
            ):
                return False
            user = session.get(DbUser, row.submitter_user_id) if row.submitter_user_id is not None else None
            if row.submitter_user_id is not None and user is None:
                return False

            notifier.send(
                FeedbackNotification(
                    id=row.id,
                    category=cast(FeedbackCategory, row.category),
                    message=row.message,
                    source_path=row.source_path,
                    page_title=row.page_title,
                    created_at=row.created_at,
                    attempt_number=row.notification_attempts,
                    submitter_user_id=row.submitter_user_id,
                    submitter_email=user.email if user is not None else None,
                    submitter_name=user.name if user is not None else None,
                ),
            )
            row.notification_status = "sent"
            row.notification_sent_at = now
            row.notification_next_attempt_at = now
            row.notification_last_error_code = None
            return True

    def mark_notification_sent(
        self,
        feedback_id: str,
        *,
        attempt_number: int,
        now: int,
    ) -> None:
        with self.db.session() as session:
            row = session.get(DbProductFeedback, feedback_id)
            if row is None or row.notification_status != "sending" or row.notification_attempts != attempt_number:
                return
            row.notification_status = "sent"
            row.notification_sent_at = now
            row.notification_next_attempt_at = now
            row.notification_last_error_code = None

    def mark_notification_failed(
        self,
        feedback_id: str,
        *,
        attempt_number: int,
        now: int,
        error_code: str,
    ) -> None:
        with self.db.session() as session:
            row = session.get(DbProductFeedback, feedback_id)
            if row is None or row.notification_status != "sending" or row.notification_attempts != attempt_number:
                return
            retry_delay = min(6 * 60 * 60, 30 * (2 ** min(attempt_number - 1, 9)))
            row.notification_status = "pending"
            row.notification_next_attempt_at = now + retry_delay
            row.notification_last_error_code = error_code[:64]

    def purge_expired(self, *, older_than: int, now: int) -> int:
        """Delete expired rows, preserving only a currently active send lease."""
        with self.db.session() as session:
            result = session.execute(
                delete(DbProductFeedback).where(
                    DbProductFeedback.created_at < older_than,
                    or_(
                        DbProductFeedback.notification_status != "sending",
                        DbProductFeedback.notification_next_attempt_at <= now,
                    ),
                ),
            )
            return int(getattr(result, "rowcount", 0) or 0)

    def assert_queue_available(self) -> None:
        """Cheap schema/DB health probe for the isolated worker container."""
        with self.db.session() as session:
            session.execute(select(DbProductFeedback.id).limit(1)).all()


class SmtpFeedbackNotifier:
    """STARTTLS-only feedback delivery with fixed, injection-safe headers."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        mail_from: str,
        recipient: str,
        timeout_seconds: int,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.mail_from = mail_from
        self.recipient = recipient
        self.timeout_seconds = timeout_seconds

    def send(self, notification: FeedbackNotification) -> None:
        message = self._build_message(notification)
        with smtplib.SMTP(
            self.host,
            self.port,
            timeout=float(self.timeout_seconds),
        ) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(self.username, self.password)
            smtp.send_message(message)

    def _build_message(self, notification: FeedbackNotification) -> EmailMessage:
        category_label = _CATEGORY_LABELS[notification.category]
        sender = (
            f"{notification.submitter_name} <{notification.submitter_email}>"
            if notification.submitter_email is not None
            else "Ανώνυμος επισκέπτης"
        )
        created_at = time.strftime(
            "%Y-%m-%d %H:%M:%S UTC",
            time.gmtime(notification.created_at),
        )
        body = (
            "Νέο feedback στο GSUBS\n\n"
            f"Κατηγορία: {category_label}\n"
            f"Feedback ID: {notification.id}\n"
            f"Σελίδα: {notification.source_path}\n"
            f"Τίτλος σελίδας: {notification.page_title}\n"
            f"Αποστολέας: {sender}\n"
            f"Χρόνος: {created_at}\n\n"
            "Μήνυμα:\n"
            f"{notification.message}\n"
        )
        message = EmailMessage()
        message["Subject"] = f"[GSUBS Feedback] {category_label} · {notification.id[:8]}"
        message["From"] = self.mail_from
        message["To"] = self.recipient
        message["X-GSUBS-Feedback-ID"] = notification.id
        message.set_content(body)
        return message


class FeedbackNotificationWorker:
    """Drain the durable outbox with bounded retries and retention."""

    def __init__(
        self,
        *,
        store: FeedbackStore,
        notifier: FeedbackNotifier,
        retention_days: int,
        batch_size: int = 10,
        now: Callable[[], int] | None = None,
    ) -> None:
        self.store = store
        self.notifier = notifier
        self.retention_days = retention_days
        self.batch_size = batch_size
        self._now = now or (lambda: int(time.time()))

    def process_once(self) -> int:
        now = self._now()
        retention_cutoff = now - (self.retention_days * 86_400)
        self.store.purge_expired(
            older_than=retention_cutoff,
            now=now,
        )
        notifications = self.store.claim_due_notifications(
            now=now,
            batch_size=self.batch_size,
            not_older_than=retention_cutoff,
        )
        sent = 0
        for notification in notifications:
            try:
                delivered = self.store.deliver_notification(
                    notification,
                    notifier=self.notifier,
                    now=now,
                )
            except Exception as exc:
                error_code = type(exc).__name__
                logger.warning(
                    "Feedback notification delivery will retry",
                    extra={
                        "feedback_id": notification.id,
                        "attempt": notification.attempt_number,
                        "error_code": error_code,
                    },
                )
                self.store.mark_notification_failed(
                    notification.id,
                    attempt_number=notification.attempt_number,
                    now=now,
                    error_code=error_code,
                )
                continue
            if delivered:
                sent += 1
        return sent


def run_feedback_worker(
    *,
    worker: FeedbackNotificationWorker,
    poll_seconds: int,
) -> None:
    """Run forever; Docker restarts the process on non-delivery infrastructure faults."""
    while True:
        try:
            worker.process_once()
        except Exception as exc:
            logger.error(
                "Feedback worker iteration failed",
                extra={"error_code": type(exc).__name__},
            )
        time.sleep(poll_seconds)
