"""HTTP contracts for anonymous and signed-in feedback submission."""

from __future__ import annotations

import time

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, select

from backend.app.core.config import settings
from backend.app.core.ratelimit import limiter_feedback_hour, limiter_feedback_minute
from backend.app.db.models import DbProductFeedback


@pytest.fixture(autouse=True)
def enabled_feedback(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "feedback_enabled", True)
    monkeypatch.setattr(settings, "feedback_hash_secret", SecretStr("s" * 64))
    with client.app.state.db.session() as session:
        session.execute(delete(DbProductFeedback))
    yield
    with client.app.state.db.session() as session:
        session.execute(delete(DbProductFeedback))


def _payload(**overrides: object) -> dict[str, object]:
    return {
        "category": "idea",
        "message": "Θα ήθελα να μπορώ να αποθηκεύω δικά μου templates.",
        "source_path": "/",
        "page_title": "GSUBS Studio",
        "form_started_at": int(time.time()) - 3,
        "website": "",
        **overrides,
    }


def test_anonymous_feedback_is_accepted_and_queued(client) -> None:
    response = client.post(
        "/feedback",
        json=_payload(),
        headers={"x-forwarded-for": "198.51.100.10"},
    )

    assert response.status_code == 202
    assert response.json()["status"] == "received"
    with client.app.state.db.session() as session:
        row = session.get(DbProductFeedback, response.json()["id"])
        assert row is not None
        assert row.submitter_user_id is None
        assert row.notification_status == "pending"


def test_signed_in_feedback_is_attached_to_the_account(client, user_auth_headers) -> None:
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    response = client.post(
        "/feedback",
        json=_payload(category="chat"),
        headers=user_auth_headers,
    )

    assert response.status_code == 202
    with client.app.state.db.session() as session:
        row = session.get(DbProductFeedback, response.json()["id"])
        assert row is not None
        assert row.submitter_user_id == user_id

    exported = client.get("/auth/export", headers=user_auth_headers)
    assert exported.status_code == 200
    assert exported.json()["product_feedback"] == [
        {
            "id": response.json()["id"],
            "category": "chat",
            "status": "new",
            "message": _payload()["message"],
            "source_path": "/",
            "page_title": "GSUBS Studio",
            "submitter_key_hash": exported.json()["product_feedback"][0][
                "submitter_key_hash"
            ],
            "message_hash": exported.json()["product_feedback"][0]["message_hash"],
            "created_at": exported.json()["product_feedback"][0]["created_at"],
            "notification_status": "pending",
            "notification_attempts": 0,
            "notification_sent_at": None,
        },
    ]


def test_feedback_rejects_a_present_but_invalid_bearer(client) -> None:
    response = client.post(
        "/feedback",
        json=_payload(),
        headers={"Authorization": "Bearer invalid-feedback-session"},
    )

    assert response.status_code == 401
    with client.app.state.db.session() as session:
        assert session.scalars(select(DbProductFeedback)).all() == []


def test_account_deletion_cascades_linked_feedback(client, user_auth_headers) -> None:
    response = client.post(
        "/feedback",
        json=_payload(category="bug"),
        headers=user_auth_headers,
    )
    assert response.status_code == 202
    feedback_id = response.json()["id"]

    deleted = client.delete("/auth/me", headers=user_auth_headers)
    assert deleted.status_code == 200
    with client.app.state.db.session() as session:
        assert session.get(DbProductFeedback, feedback_id) is None


def test_honeypot_is_silently_accepted_without_persistence(client) -> None:
    response = client.post(
        "/feedback",
        json=_payload(website="https://spam.example"),
    )

    assert response.status_code == 202
    assert response.json() == {"status": "received", "id": None}
    with client.app.state.db.session() as session:
        assert session.scalars(select(DbProductFeedback)).all() == []


def test_feedback_rejects_impossibly_fast_and_extra_field_submissions(client) -> None:
    too_fast = client.post(
        "/feedback",
        json=_payload(form_started_at=int(time.time())),
    )
    extra = client.post(
        "/feedback",
        json=_payload(untrusted="value"),
    )

    assert too_fast.status_code == 422
    assert extra.status_code == 422


def test_feedback_returns_public_safe_validation_errors(client) -> None:
    response = client.post(
        "/feedback",
        json=_payload(message="short"),
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Feedback must contain at least 10 characters."


def test_feedback_rate_limit_blocks_the_fourth_submission_per_minute(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)
    limiter_feedback_minute.reset()
    limiter_feedback_hour.reset()
    try:
        responses = [
            client.post(
                "/feedback",
                json=_payload(message=f"Μοναδικό μήνυμα δοκιμής feedback αριθμός {index}."),
            )
            for index in range(4)
        ]
    finally:
        limiter_feedback_minute.reset()
        limiter_feedback_hour.reset()

    assert [response.status_code for response in responses] == [202, 202, 202, 429]


def test_feedback_endpoint_fails_closed_when_feature_is_disabled(
    client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "feedback_enabled", False)

    response = client.post("/feedback", json=_payload())

    assert response.status_code == 503
