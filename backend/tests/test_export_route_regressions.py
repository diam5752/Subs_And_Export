import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from backend.app.api.deps import get_db, get_job_store
from backend.app.api.endpoints import export_routes, processing_tasks
from backend.app.api.endpoints.settings import ProcessingSettings
from backend.app.core.database import Database
from backend.app.services import jobs
from backend.app.services.ffmpeg_utils import MediaProbe
from backend.main import app


def test_srt_export_missing_transcript_returns_404(client: TestClient, monkeypatch, user_auth_headers, tmp_path: Path):
    # REGRESSION: missing transcript should preserve its original 404 instead of being wrapped as a 500.
    monkeypatch.setattr(export_routes.settings, "project_root", tmp_path)
    data_dir = tmp_path
    uploads_dir = tmp_path / "uploads"
    artifacts_root = tmp_path / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(export_routes, "data_roots", lambda: (data_dir, uploads_dir, artifacts_root))
    monkeypatch.setattr(export_routes, "get_gcs_settings", lambda: None)

    db = Database()
    store = jobs.JobStore(db)
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        user = client.get("/auth/me", headers=user_auth_headers).json()
        job_id = f"srt-missing-{uuid.uuid4().hex}"
        store.create_job(job_id, user["id"])
        (artifacts_root / job_id).mkdir(parents=True, exist_ok=True)
        store.update_job(job_id, status="completed", result_data={})

        response = client.post(
            f"/videos/jobs/{job_id}/export",
            headers=user_auth_headers,
            json={"resolution": "srt"},
        )

        assert response.status_code == 404
        assert "Transcript not found" in response.text
    finally:
        app.dependency_overrides = {}


def test_export_video_invalid_resolution_returns_422(client: TestClient, monkeypatch, user_auth_headers, tmp_path: Path):
    # REGRESSION: bogus resolution strings must be rejected instead of silently exporting the default size.
    monkeypatch.setattr(export_routes.settings, "project_root", tmp_path)
    data_dir = tmp_path
    uploads_dir = tmp_path / "uploads"
    artifacts_root = tmp_path / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(export_routes, "data_roots", lambda: (data_dir, uploads_dir, artifacts_root))
    monkeypatch.setattr(export_routes, "get_gcs_settings", lambda: None)

    db = Database()
    store = jobs.JobStore(db)
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        user = client.get("/auth/me", headers=user_auth_headers).json()
        job_id = f"bad-res-{uuid.uuid4().hex}"
        store.create_job(job_id, user["id"])

        artifact_dir = artifacts_root / job_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / f"{job_id}_input.mp4").write_bytes(b"video")
        (artifact_dir / f"{job_id}_input.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            encoding="utf-8",
        )
        store.update_job(job_id, status="completed", result_data={})

        response = client.post(
            f"/videos/jobs/{job_id}/export",
            headers=user_auth_headers,
            json={"resolution": "badres"},
        )

        assert response.status_code == 422
        assert "Invalid resolution format" in response.text
    finally:
        app.dependency_overrides = {}


def test_run_video_processing_uses_precomputed_probe(monkeypatch, tmp_path: Path):
    # REGRESSION: validation probes should be reused in the background task instead of re-running ffprobe.
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    input_path = uploads_dir / "job-1_input.mp4"
    input_path.write_bytes(b"video")
    output_path = artifacts_root / "job-1" / "processed.mp4"

    monkeypatch.setattr(processing_tasks, "data_roots", lambda: (data_dir, uploads_dir, artifacts_root))
    monkeypatch.setattr(
        processing_tasks,
        "probe_media",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("probe_media should not be called")),
    )

    captured: dict[str, object] = {}

    def fake_normalize_and_stub_subtitles(**kwargs):
        captured["media_probe"] = kwargs["media_probe"]
        destination = kwargs["output_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"preview")
        return destination

    monkeypatch.setattr(processing_tasks, "normalize_and_stub_subtitles", fake_normalize_and_stub_subtitles)
    monkeypatch.setattr(processing_tasks, "get_gcs_settings", lambda: None)

    job = SimpleNamespace(status="pending")
    job_store = MagicMock()
    job_store.get_job.return_value = job

    proc_settings = ProcessingSettings(
        transcribe_model="standard",
        transcribe_provider="groq",
        video_quality="balanced",
    )
    source_probe = MediaProbe(duration_s=12.5, audio_codec="aac")

    processing_tasks.run_video_processing(
        "job-1",
        input_path,
        output_path,
        artifacts_root / "job-1",
        proc_settings,
        job_store,
        source_probe=source_probe,
    )

    assert captured["media_probe"] == source_probe
    completed_update = job_store.update_job.call_args_list[-1].kwargs
    assert completed_update["result_data"]["duration_seconds"] == 12.5
