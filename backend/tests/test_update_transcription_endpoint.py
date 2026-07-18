from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


def _auth_header(client: TestClient, email: str) -> dict[str, str]:
    from backend.app.core import ratelimit
    from backend.app.core.database import Database
    from backend.app.services.points import PointsStore

    ratelimit.limiter_login.reset()
    ratelimit.limiter_register.reset()
    ratelimit.limiter_processing.reset()
    ratelimit.limiter_content.reset()

    password = "testpassword123"
    register_resp = client.post(
        "/auth/register",
        json={"email": email, "password": password, "name": "Transcript User"},
    )
    assert register_resp.status_code == 200, register_resp.text

    token_resp = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    )
    assert token_resp.status_code == 200, token_resp.text
    token = token_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Ensure user has credits
    me_resp = client.get("/auth/me", headers=headers)
    if me_resp.status_code == 200:
        user_id = me_resp.json().get("id")
        if user_id:
            db = Database()
            points_store = PointsStore(db=db)
            points_store.ensure_account(user_id)
            # Grant additional credits for tests
            points_store.credit(user_id, 1000, "test_credit", {"source": "unit_tests"})

    return headers


def test_update_transcription_overwrites_job_artifacts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GSP_DATABASE_PATH", str(tmp_path / "app.db"))

    from backend.app.core import config

    monkeypatch.setattr(config.settings, "project_root", tmp_path)
    monkeypatch.setattr(config.settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr("backend.app.api.endpoints.file_utils.settings.project_root", tmp_path)
    monkeypatch.setattr("backend.app.api.endpoints.file_utils.settings.data_dir", tmp_path / "data")

    job_id = str(uuid.uuid4())
    data_dir = tmp_path / "data"
    target_artifacts_dir = data_dir / "artifacts" / job_id
    target_artifacts_dir.mkdir(parents=True, exist_ok=True)

    source_transcription = [{"start": 0.0, "end": 1.0, "text": "hi", "words": []}]
    (target_artifacts_dir / "transcription.json").write_text(
        json.dumps(source_transcription),
        encoding="utf-8",
    )
    (target_artifacts_dir / f"{job_id}_input.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n",
        encoding="utf-8",
    )

    from backend.main import app

    with TestClient(app) as client:
        headers = _auth_header(client, f"update-transcript-{uuid.uuid4().hex}@example.com")
        me_resp = client.get("/auth/me", headers=headers)
        assert me_resp.status_code == 200, me_resp.text

        from backend.app.services.jobs import JobStore

        job_store = JobStore(db=client.app.state.db)
        job_store.create_job(job_id, me_resp.json()["id"])
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            result_data={"artifacts_dir": f"artifacts/{job_id}"},
        )

        target_transcription_path = data_dir / "artifacts" / job_id / "transcription.json"
        assert target_transcription_path.exists()

        update_body = {
            "cues": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "γειά κόσμε",
                    "words": [
                        {"start": 0.0, "end": 0.5, "text": "γειά"},
                        {"start": 0.5, "end": 1.0, "text": "κόσμε"},
                    ],
                }
            ]
        }

        resp = client.put(f"/videos/jobs/{job_id}/transcription", headers=headers, json=update_body)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"

        updated = json.loads(target_transcription_path.read_text(encoding="utf-8"))
        assert updated == [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "ΓΕΙΑ ΚΟΣΜΕ",
                "words": [
                    {"start": 0.0, "end": 0.5, "text": "ΓΕΙΑ"},
                    {"start": 0.5, "end": 1.0, "text": "ΚΟΣΜΕ"},
                ],
            }
        ]

        job_detail = client.get(f"/videos/jobs/{job_id}", headers=headers)
        assert job_detail.status_code == 200, job_detail.text
        assert job_detail.json()["result_data"]["transcription_edited"] is True
