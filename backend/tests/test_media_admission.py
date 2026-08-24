from __future__ import annotations

import errno
import uuid
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps as api_deps
from backend.app.api.endpoints import videos as videos_endpoints
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.services.jobs import JobStore
from backend.app.services.points import PointsStore
from backend.tests.process_stream import post_process_stream


def _forbid_upload_reader(monkeypatch: pytest.MonkeyPatch) -> Callable[[], bool]:
    called = False

    async def forbidden_reader(*_args, **_kwargs) -> None:
        nonlocal called
        called = True
        raise AssertionError("request body must not be read before admission")

    monkeypatch.setattr(
        videos_endpoints,
        "save_request_stream_with_limit",
        forbidden_reader,
    )
    return lambda: called


def test_zero_credit_upload_is_rejected_before_body_read(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: a zero-credit account could previously stream the complete
    # upload and consume disk/ffprobe resources before the wallet was checked.
    upload_reader_called = _forbid_upload_reader(monkeypatch)
    monkeypatch.setattr(settings, "mock_external_services", False)

    response = post_process_stream(
        client,
        user_auth_headers,
        metadata={
            "authorized_credits": 30,
            "transcribe_provider": "elevenlabs",
        },
        content=b"must-not-be-consumed",
    )

    assert response.status_code == 402
    assert response.json()["detail"] == "Insufficient points"
    assert upload_reader_called() is False


def test_live_provider_requires_paid_credits_before_upload(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_reader_called = _forbid_upload_reader(monkeypatch)
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    PointsStore(Database()).credit(
        user_id,
        100,
        reason="test_promotional_only",
    )
    monkeypatch.setattr(settings, "mock_external_services", False)

    response = post_process_stream(
        client,
        user_auth_headers,
        metadata={
            "authorized_credits": 30,
            "transcribe_provider": "elevenlabs",
        },
        content=b"must-not-be-consumed",
    )

    assert response.status_code == 402
    assert response.json()["detail"] == "Insufficient paid credits"
    assert upload_reader_called() is False


def test_authorized_credits_are_reserved_before_upload_body_and_refunded_on_failure(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: a balance check alone let one paid balance authorize repeated
    # uploads without creating an outstanding wallet reservation.
    user_id = client.get(
        "/auth/me",
        headers=funded_user_auth_headers,
    ).json()["id"]
    points_store = PointsStore(Database())
    starting_balance = points_store.get_balance(user_id)
    observed_balances: list[int] = []

    async def fail_after_observing_reservation(*_args, **_kwargs) -> None:
        observed_balances.append(points_store.get_balance(user_id))
        raise OSError(errno.ENOSPC, "synthetic disk failure")

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(
        videos_endpoints,
        "save_request_stream_with_limit",
        fail_after_observing_reservation,
    )

    response = post_process_stream(
        client,
        funded_user_auth_headers,
        metadata={
            "authorized_credits": 30,
            "transcribe_provider": "elevenlabs",
        },
        content=b"private-video",
    )

    assert response.status_code == 507
    assert observed_balances == [starting_balance - 30]
    assert points_store.get_balance(user_id) == starting_balance
    assert JobStore(Database()).list_jobs_for_user(user_id) == []


def test_global_active_job_limit_rejects_new_upload_before_body_read(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: the old limit was per-user and racy, allowing many users to
    # saturate the same single-host FFmpeg runtime concurrently.
    upload_reader_called = _forbid_upload_reader(monkeypatch)
    monkeypatch.setattr(
        api_deps,
        "_production_media_capacity_enforced",
        lambda: True,
    )
    user_id = client.get(
        "/auth/me",
        headers=funded_user_auth_headers,
    ).json()["id"]
    job_store = JobStore(Database())
    active_job = job_store.create_job(
        f"global-capacity-{uuid.uuid4().hex}",
        user_id,
    )
    try:
        response = post_process_stream(
            client,
            funded_user_auth_headers,
            metadata={"authorized_credits": 30},
            content=b"must-not-be-consumed",
        )
    finally:
        job_store.delete_job(active_job.id)

    assert response.status_code == 429
    assert "currently at capacity" in response.json()["detail"]
    assert upload_reader_called() is False
