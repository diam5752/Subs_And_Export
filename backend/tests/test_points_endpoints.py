from __future__ import annotations

import os
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos as videos_endpoints
from backend.app.core.database import Database
from backend.app.services.jobs import JobStore
from backend.app.services.points import STARTING_POINTS_BALANCE, PointsStore


def _db_from_env() -> Database:
    db_path = os.environ.get("GSP_DATABASE_PATH")
    assert db_path is not None
    return Database(db_path)


def test_auth_points_endpoint_returns_starting_balance(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    resp = client.get("/auth/points", headers=user_auth_headers)
    assert resp.status_code == 200
    assert resp.json()["balance"] == STARTING_POINTS_BALANCE


def test_process_video_charges_points_and_returns_balance(
    client: TestClient, user_auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fake_run_video_processing(job_id: str, *_args, **_kwargs) -> None:
        job_store = _args[4]
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
    before = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    resp = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("clip.mp4", b"123", "video/mp4")},
        data={"transcribe_model": "large"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["balance"] == before - 500

    after = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    assert after == body["balance"]

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
    monkeypatch.setattr(videos_endpoints, "_data_roots", lambda: (data_dir, uploads_dir, artifacts_dir))

    monkeypatch.setattr(
        videos_endpoints,
        "normalize_and_stub_subtitles",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    before = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    resp = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("clip.mp4", b"123", "video/mp4")},
        data={"transcribe_model": "large"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["balance"] == before - 500

    after = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    assert after == before

    job = client.get(f"/videos/jobs/{body['id']}", headers=user_auth_headers)
    assert job.status_code == 200
    assert job.json()["status"] == "failed"


def test_process_video_rejects_on_insufficient_points(
    client: TestClient, user_auth_headers: dict[str, str]
) -> None:
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    db = _db_from_env()
    PointsStore(db=db).spend(user_id, STARTING_POINTS_BALANCE, reason="test_setup")

    resp = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("clip.mp4", b"123", "video/mp4")},
        data={"transcribe_model": "medium"},
    )
    assert resp.status_code == 402
    assert resp.json()["detail"] == "Insufficient points"
    assert client.get("/auth/points", headers=user_auth_headers).json()["balance"] == 0


def test_fact_check_charges_points_and_rejects_on_insufficient_balance(
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
    monkeypatch.setattr(videos_endpoints, "_data_roots", lambda: (data_dir, uploads_dir, artifacts_dir))
    monkeypatch.setattr(videos_endpoints, "run_video_processing", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        "backend.app.services.subtitles.generate_fact_check",
        lambda *_args, **_kwargs: types.SimpleNamespace(items=[]),
    )

    process_resp = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("clip.mp4", b"123", "video/mp4")},
        data={"transcribe_model": "medium"},
    )
    assert process_resp.status_code == 200, process_resp.text
    job_id = process_resp.json()["id"]

    # Mark job completed + seed transcript.
    db = _db_from_env()
    JobStore(db=db).update_job(job_id, status="completed", progress=100)
    job_dir = artifacts_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "transcript.txt").write_text("hello", encoding="utf-8")

    before = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    fact_resp = client.post(f"/videos/jobs/{job_id}/fact-check", headers=user_auth_headers)
    assert fact_resp.status_code == 200, fact_resp.text
    assert fact_resp.json()["balance"] == before - 100

    # Drain remaining points and verify 402 path.
    me = client.get("/auth/me", headers=user_auth_headers)
    user_id = me.json()["id"]
    current = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    if current:
        PointsStore(db=db).spend(user_id, current, reason="test_setup")

    insufficient = client.post(f"/videos/jobs/{job_id}/fact-check", headers=user_auth_headers)
    assert insufficient.status_code == 402
    assert insufficient.json()["detail"] == "Insufficient points"


def test_fact_check_refunds_points_when_generation_fails(
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
    monkeypatch.setattr(videos_endpoints, "_data_roots", lambda: (data_dir, uploads_dir, artifacts_dir))

    monkeypatch.setattr(
        "backend.app.services.subtitles.generate_fact_check",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]

    db = _db_from_env()
    job_id = "job_fact_refund"
    JobStore(db=db).create_job(job_id, user_id)
    JobStore(db=db).update_job(job_id, status="completed", progress=100)
    job_dir = artifacts_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "transcript.txt").write_text("hello", encoding="utf-8")

    before = client.get("/auth/points", headers=user_auth_headers).json()["balance"]
    resp = client.post(f"/videos/jobs/{job_id}/fact-check", headers=user_auth_headers)
    assert resp.status_code == 500
    assert client.get("/auth/points", headers=user_auth_headers).json()["balance"] == before
