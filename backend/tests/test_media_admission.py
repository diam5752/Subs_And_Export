from __future__ import annotations

import errno
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from backend.app.api import deps as api_deps
from backend.app.api.endpoints import videos as videos_endpoints
from backend.app.api.endpoints.processing_tasks import refund_charge_best_effort
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
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: a balance check alone let one paid balance authorize repeated
    # uploads without creating an outstanding wallet reservation.
    user_id = client.get(
        "/auth/me",
        headers=user_auth_headers,
    ).json()["id"]
    points_store = PointsStore(Database())
    points_store.credit(
        user_id,
        100,
        reason="test_paid_upload_reservation",
        paid_credit_delta=100,
    )
    starting_balance = points_store.get_balance(user_id)
    observed_balances: list[int] = []

    async def fail_after_observing_reservation(*_args, **_kwargs) -> None:
        observed_balances.append(points_store.get_balance(user_id))
        raise OSError(errno.ENOSPC, "synthetic disk failure")

    monkeypatch.setattr(settings, "mock_external_services", False)
    monkeypatch.setattr(settings, "external_provider_per_request_budget_usd", 100.0)
    monkeypatch.setattr(settings, "external_provider_daily_budget_usd", 100.0)
    monkeypatch.setattr(settings, "external_provider_monthly_budget_usd", 100.0)
    monkeypatch.setattr(
        videos_endpoints,
        "save_request_stream_with_limit",
        fail_after_observing_reservation,
    )

    response = post_process_stream(
        client,
        user_auth_headers,
        metadata={
            "authorized_credits": 30,
            "transcribe_provider": settings.transcribe_tier_provider[
                settings.default_transcribe_tier
            ],
        },
        content=b"private-video",
    )

    assert response.status_code == 507, response.text
    assert observed_balances == [starting_balance - 30]
    assert points_store.get_balance(user_id) == starting_balance
    assert JobStore(Database()).list_jobs_for_user(user_id) == []


def test_global_active_job_limit_rejects_the_sixth_before_body_read(
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
    active_jobs = [
        job_store.create_job(
            f"global-capacity-{uuid.uuid4().hex}",
            user_id,
        )
        for _ in range(settings.max_active_media_jobs)
    ]
    try:
        response = post_process_stream(
            client,
            funded_user_auth_headers,
            metadata={"authorized_credits": 30},
            content=b"must-not-be-consumed",
        )
    finally:
        for active_job in active_jobs:
            job_store.delete_job(active_job.id)

    assert response.status_code == 429
    assert "currently at capacity" in response.json()["detail"]
    assert upload_reader_called() is False


def test_one_active_customer_leaves_capacity_for_four_more(
    client: TestClient,
    funded_user_auth_headers: dict[str, str],
) -> None:
    # REGRESSION: the production admission guard used a hard-coded global
    # capacity of one, rejecting every second customer before reading a byte.
    user_id = client.get(
        "/auth/me",
        headers=funded_user_auth_headers,
    ).json()["id"]
    job_store = JobStore(Database())
    active_job = job_store.create_job(
        f"five-user-capacity-{uuid.uuid4().hex}",
        user_id,
    )
    try:
        api_deps._assert_global_media_capacity(Database())
    finally:
        job_store.delete_job(active_job.id)


def test_five_customers_process_concurrently_and_sixth_is_rejected_before_upload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: the admission dependency held its global flock through every
    # background task, silently reducing the whole deployment to one customer.
    monkeypatch.setattr(
        api_deps,
        "_production_media_capacity_enforced",
        lambda: True,
    )
    database = Database()
    points_store = PointsStore(database)
    headers_by_user: list[dict[str, str]] = []
    for index in range(settings.max_active_media_jobs + 1):
        email = f"capacity-{uuid.uuid4().hex}-{index}@example.com"
        password = "testpassword123"
        register = client.post(
            "/auth/register",
            json={"email": email, "password": password, "name": f"Capacity {index}"},
        )
        assert register.status_code == 200, register.text
        token = client.post(
            "/auth/token",
            data={"username": email, "password": password},
        ).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        user_id = client.get("/auth/me", headers=headers).json()["id"]
        points_store.credit(user_id, 100, reason="five_user_capacity_test")
        headers_by_user.append(headers)

    original_stream_saver = videos_endpoints.save_request_stream_with_limit
    upload_calls = 0
    upload_calls_lock = threading.Lock()

    async def tracked_stream_saver(*args, **kwargs) -> int:
        nonlocal upload_calls
        with upload_calls_lock:
            upload_calls += 1
        return await original_stream_saver(*args, **kwargs)

    monkeypatch.setattr(
        videos_endpoints,
        "save_request_stream_with_limit",
        tracked_stream_saver,
    )

    all_started = threading.Event()
    release_processing = threading.Event()
    started = 0
    started_lock = threading.Lock()

    def held_processing(
        job_id,
        _input_path,
        _output_path,
        _artifact_path,
        _proc_settings,
        job_store,
        *_args,
        ledger_store=None,
        charge_plan=None,
        **_kwargs,
    ) -> None:
        nonlocal started
        job_store.update_job(job_id, status="processing")
        with started_lock:
            started += 1
            if started == settings.max_active_media_jobs:
                all_started.set()
        assert release_processing.wait(timeout=15)
        refund_charge_best_effort(
            ledger_store,
            charge_plan,
            status="failed",
            error="five-user concurrency test complete",
        )
        job_store.update_job(job_id, status="failed")

    monkeypatch.setattr(videos_endpoints, "run_video_processing", held_processing)

    def submit(headers: dict[str, str]):
        return post_process_stream(
            client,
            headers,
            metadata={"authorized_credits": 30},
            content=b"synthetic-video",
        )

    with ThreadPoolExecutor(max_workers=settings.max_active_media_jobs) as executor:
        futures = [
            executor.submit(submit, headers)
            for headers in headers_by_user[: settings.max_active_media_jobs]
        ]
        assert all_started.wait(timeout=15)

        sixth = submit(headers_by_user[-1])
        assert sixth.status_code == 429
        assert "currently at capacity" in sixth.json()["detail"]
        with upload_calls_lock:
            assert upload_calls == settings.max_active_media_jobs

        release_processing.set()
        responses = [future.result(timeout=15) for future in futures]

    assert [response.status_code for response in responses] == [200] * 5
    assert started == 5

    job_store = JobStore(database)
    for response in responses:
        job_store.delete_job(response.json()["id"])
