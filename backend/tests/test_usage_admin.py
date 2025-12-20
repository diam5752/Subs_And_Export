from __future__ import annotations

import time
import uuid

from fastapi.testclient import TestClient

from backend.app.core.database import Database
from backend.app.db.models import DbJob
from backend.app.services.points import PointsStore
from backend.app.services.usage_ledger import UsageLedgerStore


def _admin_headers(client: TestClient, email: str) -> dict[str, str]:
    client.post("/auth/register", json={"email": email, "password": "testpassword123", "name": "Admin"})
    token = client.post(
        "/auth/token",
        data={"username": email, "password": "testpassword123"},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _seed_job(db: Database, user_id: str, job_id: str) -> str:
    now = int(time.time())
    with db.session() as session:
        session.add(
            DbJob(
                id=job_id,
                user_id=user_id,
                status="pending",
                created_at=now,
                updated_at=now,
            )
        )
    return job_id


def test_admin_usage_summary_returns_data(client: TestClient, monkeypatch) -> None:
    admin_email = f"admin_{uuid.uuid4().hex}@example.com"
    monkeypatch.setenv("GSP_ADMIN_EMAILS", admin_email)
    headers = _admin_headers(client, admin_email)

    me = client.get("/auth/me", headers=headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    fixed_ts = 1_700_000_000
    monkeypatch.setattr("backend.app.services.usage_ledger.time.time", lambda: fixed_ts)

    db = Database()
    job_id = f"admin-summary-{uuid.uuid4().hex[:8]}"
    _seed_job(db, user_id, job_id)
    points_store = PointsStore(db=db)
    ledger_store = UsageLedgerStore(db=db, points_store=points_store)

    reservation, _ = ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider="groq",
        model="whisper-large-v3-turbo",
        tier="standard",
        credits=25,
        min_credits=25,
        cost_estimate_usd=0.01,
        units={"audio_seconds": 30},
        idempotency_key=f"admin-summary-{uuid.uuid4().hex[:8]}",
        endpoint="audio/transcriptions",
    )
    ledger_store.finalize(reservation, credits_charged=25, cost_usd=0.01, units={})

    resp = client.get(
        f"/videos/admin/usage/summary?group_by=action&start_ts={fixed_ts - 1}&end_ts={fixed_ts + 1}",
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["group_by"] == "action"
    assert any(item["bucket"] == "transcription" for item in payload["items"])
