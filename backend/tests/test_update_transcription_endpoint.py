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
    # Also patch where settings is directly imported
    monkeypatch.setattr("backend.app.api.endpoints.dev.settings.project_root", tmp_path)
    monkeypatch.setattr("backend.app.api.endpoints.dev.settings.data_dir", tmp_path / "data")
    monkeypatch.setattr("backend.app.api.endpoints.file_utils.settings.project_root", tmp_path)
    monkeypatch.setattr("backend.app.api.endpoints.file_utils.settings.data_dir", tmp_path / "data")

    source_job_id = str(uuid.uuid4())
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    source_artifacts_dir = data_dir / "artifacts" / source_job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    source_artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Mock _resolve_sample_source to return our manual setup
    monkeypatch.setattr(
        "backend.app.api.endpoints.dev._resolve_sample_source",
        lambda *args: (source_job_id, uploads_dir / f"{source_job_id}_input.mp4", source_artifacts_dir)
    )

    (uploads_dir / f"{source_job_id}_input.mp4").write_bytes(b"video")
    source_transcription = [{"start": 0.0, "end": 1.0, "text": "hi", "words": []}]
    (source_artifacts_dir / "transcription.json").write_text(
        json.dumps(source_transcription),
        encoding="utf-8",
    )
    (source_artifacts_dir / f"{source_job_id}_input.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nhi\n",
        encoding="utf-8",
    )

    from backend.main import app

    with TestClient(app) as client:
        headers = _auth_header(client, f"update-transcript-{uuid.uuid4().hex}@example.com")

        created = client.post("/dev/sample-job", headers=headers)
        assert created.status_code == 200, created.text
        job_id = created.json()["id"]

        target_transcription_path = data_dir / "artifacts" / job_id / "transcription.json"
        assert target_transcription_path.exists()

        update_body = {
            "cues": [
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": "hello world",
                    "words": [
                        {"start": 0.0, "end": 0.5, "text": "hello"},
                        {"start": 0.5, "end": 1.0, "text": "world"},
                    ],
                }
            ]
        }

        resp = client.put(f"/videos/jobs/{job_id}/transcription", headers=headers, json=update_body)
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "ok"

        updated = json.loads(target_transcription_path.read_text(encoding="utf-8"))
        assert updated == update_body["cues"]

        source_after = json.loads((source_artifacts_dir / "transcription.json").read_text(encoding="utf-8"))
        assert source_after == source_transcription

        job_detail = client.get(f"/videos/jobs/{job_id}", headers=headers)
        assert job_detail.status_code == 200, job_detail.text
        assert job_detail.json()["result_data"]["transcription_edited"] is True
