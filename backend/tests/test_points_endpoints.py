from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api.endpoints import processing_tasks
from backend.app.api.endpoints import videos as videos_endpoints
from backend.app.core.database import Database
from backend.app.services import pricing
from backend.app.services.points import PointsStore
from backend.tests.process_stream import post_process_stream


def _db_from_env() -> Database:
    return Database()


def _grant_paid_credits(
    client: TestClient,
    headers: dict[str, str],
    *,
    amount: int = 500,
) -> str:
    user_id = client.get("/auth/me", headers=headers).json()["id"]
    PointsStore(db=_db_from_env()).credit(
        user_id,
        amount,
        reason="test_paid_funding",
        paid_credit_delta=amount,
    )
    return user_id


def test_auth_points_endpoint_returns_zero_for_new_account(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    # REGRESSION: registration must not silently grant promotional credits.
    resp = client.get("/auth/points", headers=user_auth_headers)
    assert resp.status_code == 200
    assert resp.json() == {
        "balance": 0,
        "paid_balance": 0,
        "promotional_balance": 0,
        "reversal_debt": 0,
        "ai_spendable_balance": 0,
    }


def test_process_video_charges_points_and_returns_balance(
    client: TestClient, user_auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run_video_processing(job_id: str, *_args, **_kwargs) -> None:
        job_store = _args[4]
        charge_plan = _kwargs["charge_plan"]
        transcription_reservation = charge_plan.transcription
        assert transcription_reservation is not None
        _kwargs["ledger_store"].finalize(
            transcription_reservation,
            credits_charged=pricing.credits_for_video_duration(10.0),
            cost_usd=0.0,
            units={"audio_seconds": 10.0},
        )
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message="Done!",
            result_data={"video_path": "artifacts/out.mp4"},
        )

    monkeypatch.setattr(
        videos_endpoints,
        "run_video_processing",
        _fake_run_video_processing,
    )
    _grant_paid_credits(client, user_auth_headers)
    before = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    authorized_credits = 100
    resp = post_process_stream(
        client,
        user_auth_headers,
        content=b"123",
        metadata={
            "authorized_credits": authorized_credits,
            "transcribe_tier": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    expected_charge = pricing.credits_for_video_duration(10.0)
    assert body["balance"] == before - authorized_credits

    after = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    assert after == before - expected_charge


def test_process_video_refunds_points_when_processing_fails(
    client: TestClient,
    user_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)
    monkeypatch.setattr(videos_endpoints, "data_roots", lambda: (data_dir, uploads_dir, artifacts_dir))

    monkeypatch.setattr(
        processing_tasks,
        "process_video_pipeline",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    _grant_paid_credits(client, user_auth_headers)
    before = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    authorized_credits = 100
    resp = post_process_stream(
        client,
        user_auth_headers,
        content=b"123",
        metadata={
            "authorized_credits": authorized_credits,
            "transcribe_tier": "standard",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["balance"] == before - authorized_credits

    after = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    assert after == before

    job = client.get(f"/videos/jobs/{body['id']}", headers=user_auth_headers)
    assert job.status_code == 200
    assert job.json()["status"] == "failed"


def test_process_video_rejects_on_insufficient_points(client: TestClient, user_auth_headers: dict[str, str]) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    db = _db_from_env()
    points_store = PointsStore(db=db)
    current_balance = points_store.get_balance(user_id)
    assert current_balance == 0

    resp = post_process_stream(
        client,
        user_auth_headers,
        content=b"123",
        metadata={"transcribe_tier": "standard"},
    )
    assert resp.status_code == 402
    assert resp.json()["detail"] == "Insufficient points"
    assert client.get("/auth/points", headers=user_auth_headers).json()["balance"] == 0
