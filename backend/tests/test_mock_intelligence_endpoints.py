from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.services.jobs import JobStore


def _completed_job_with_transcript(
    *,
    client: TestClient,
    user_auth_headers: dict[str, str],
    artifacts_dir: Path,
) -> str:
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    job_id = f"mock_intelligence_{uuid.uuid4().hex}"
    store = JobStore(db=Database())
    store.create_job(job_id, user_id)
    store.update_job(job_id, status="completed", progress=100)
    job_dir = artifacts_dir / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "transcript.txt").write_text(
        "Αυτό είναι ένα τοπικό mock transcript για δοκιμή.",
        encoding="utf-8",
    )
    return job_id


def test_mock_intelligence_routes_use_no_external_service_or_points(
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
    monkeypatch.setattr(settings, "mock_external_services", True)
    monkeypatch.setattr(
        "backend.app.api.endpoints.intelligence_routes.data_roots",
        lambda: (data_dir, uploads_dir, artifacts_dir),
    )
    monkeypatch.setattr(
        "backend.app.api.endpoints.intelligence_routes.generate_fact_check",
        lambda *_args, **_kwargs: pytest.fail("live fact-check service was called"),
    )
    monkeypatch.setattr(
        "backend.app.api.endpoints.intelligence_routes.build_social_copy_llm",
        lambda *_args, **_kwargs: pytest.fail("live social-copy service was called"),
    )
    job_id = _completed_job_with_transcript(
        client=client,
        user_auth_headers=user_auth_headers,
        artifacts_dir=artifacts_dir,
    )
    balance_before = client.get("/auth/points", headers=user_auth_headers).json()["balance"]

    fact_response = client.post(
        f"/videos/jobs/{job_id}/fact-check",
        headers=user_auth_headers,
    )
    social_response = client.post(
        f"/videos/jobs/{job_id}/social-copy",
        headers=user_auth_headers,
    )

    assert fact_response.status_code == 200, fact_response.text
    assert fact_response.json()["claims_checked"] == 0
    assert fact_response.json()["truth_score"] == 0
    assert "mock" in fact_response.json()["items"][0]["mistake_el"].lower()
    assert social_response.status_code == 200, social_response.text
    assert social_response.json()["social_copy"]["hashtags"]
    assert (artifacts_dir / job_id / "social.json").exists()
    assert fact_response.json()["balance"] == balance_before
    assert social_response.json()["balance"] == balance_before
    assert client.get("/auth/points", headers=user_auth_headers).json()["balance"] == balance_before
