from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

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
    (artifacts_dir / "processed.mp4").write_bytes(b"rendered-video")
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
        assert payload["result_data"]["public_url"].endswith("/processed.mp4")
        assert payload["result_data"]["video_path"].endswith("/processed.mp4")
        assert payload["result_data"]["output_size"] == len(b"rendered-video")
        transcription_resp = client.get(payload["result_data"]["transcription_url"])
        assert transcription_resp.status_code == 200
        assert transcription_resp.json() == [{"start": 0.0, "end": 1.0, "text": "hi", "words": []}]


def test_resolve_sample_source_falls_back_when_exact_match_upload_is_missing(tmp_path: Path) -> None:
    from backend.app.api.endpoints.dev import DevSampleRequest, _resolve_sample_source

    uploads_dir = tmp_path / "data" / "uploads"
    artifacts_root = tmp_path / "data" / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    stale_job_id = "stale-groq-sample"
    usable_job_id = "usable-local-sample"

    (artifacts_root / stale_job_id).mkdir()
    (artifacts_root / stale_job_id / "transcription.json").write_text("[]", encoding="utf-8")
    (artifacts_root / usable_job_id).mkdir()
    (artifacts_root / usable_job_id / "transcription.json").write_text("[]", encoding="utf-8")
    usable_input = uploads_dir / f"{usable_job_id}_input.mp4"
    usable_input.write_bytes(b"video")

    class FakeJobStore:
        def get_job(self, job_id: str):
            if job_id == stale_job_id:
                return SimpleNamespace(result_data={"transcribe_provider": "groq", "model_size": "standard"})
            if job_id == usable_job_id:
                return SimpleNamespace(result_data={"transcribe_provider": "local", "model_size": "standard"})
            return None

    resolved_job_id, input_path, artifact_dir = _resolve_sample_source(
        uploads_dir,
        artifacts_root,
        FakeJobStore(),
        DevSampleRequest(provider="groq", model_size="standard"),
    )

    assert resolved_job_id == usable_job_id
    assert input_path == usable_input
    assert artifact_dir == artifacts_root / usable_job_id


def test_resolve_sample_source_uses_any_available_sample_when_filters_are_missing(tmp_path: Path) -> None:
    from backend.app.api.endpoints.dev import DevSampleRequest, _resolve_sample_source

    uploads_dir = tmp_path / "data" / "uploads"
    artifacts_root = tmp_path / "data" / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    sample_job_id = "sample-without-filters"
    (artifacts_root / sample_job_id).mkdir()
    (artifacts_root / sample_job_id / "transcription.json").write_text("[]", encoding="utf-8")
    sample_input = uploads_dir / f"{sample_job_id}_input.mp4"
    sample_input.write_bytes(b"video")

    class FakeJobStore:
        def get_job(self, job_id: str):
            if job_id == sample_job_id:
                return SimpleNamespace(result_data={"transcribe_provider": "local", "model_size": "standard"})
            return None

    resolved_job_id, input_path, artifact_dir = _resolve_sample_source(
        uploads_dir,
        artifacts_root,
        FakeJobStore(),
        DevSampleRequest(),
    )

    assert resolved_job_id == sample_job_id
    assert input_path == sample_input
    assert artifact_dir == artifacts_root / sample_job_id


def test_resolve_sample_source_seeds_bundled_fallback_when_repo_has_no_samples(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from backend.app.api.endpoints import dev

    uploads_dir = tmp_path / "data" / "uploads"
    artifacts_root = tmp_path / "data" / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    fallback = ("bundled-dev-sample", uploads_dir / "bundled-dev-sample_input.mp4", artifacts_root / "bundled-dev-sample")
    monkeypatch.setattr(dev, "_ensure_bundled_dev_sample", lambda *_args: fallback)

    class FakeJobStore:
        def get_job(self, job_id: str):
            return None

    resolved = dev._resolve_sample_source(
        uploads_dir,
        artifacts_root,
        FakeJobStore(),
        dev.DevSampleRequest(provider="groq", model_size="standard"),
    )

    assert resolved == fallback
