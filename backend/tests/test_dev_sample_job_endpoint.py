from __future__ import annotations

import json
import uuid
from pathlib import Path

from fastapi.testclient import TestClient


def _auth_header(client: TestClient, email: str) -> dict[str, str]:
    password = "testpassword123"
    client.post("/auth/register", json={"email": email, "password": password, "name": "Dev User"})
    token = client.post(
        "/auth/token",
        data={"username": email, "password": password},
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_dev_sample_job_creates_completed_job(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GSP_DATABASE_PATH", str(tmp_path / "app.db"))

    from backend.app.core import config

    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)

    sample_job_id = str(uuid.uuid4())
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts" / sample_job_id
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # Mock _resolve_sample_source to return our manual setup
    monkeypatch.setattr(
        "backend.app.api.endpoints.dev._resolve_sample_source",
        lambda *args: (sample_job_id, uploads_dir / f"{sample_job_id}_input.mp4", artifacts_dir)
    )

    (uploads_dir / f"{sample_job_id}_input.mp4").write_bytes(b"video")
    (artifacts_dir / "transcription.json").write_text(
        json.dumps([{"start": 0.0, "end": 1.0, "text": "hi", "words": []}]),
        encoding="utf-8",
    )
    (artifacts_dir / f"{sample_job_id}_input.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")

    from backend.main import app

    with TestClient(app) as client:
        headers = _auth_header(client, f"dev-sample-{uuid.uuid4().hex}@example.com")

        resp = client.post("/dev/sample-job", headers=headers)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        assert payload["status"] == "completed"
        assert payload["result_data"]["transcription_url"].endswith("/transcription.json")
        assert payload["result_data"]["dev_sample_source_job_id"] == sample_job_id
