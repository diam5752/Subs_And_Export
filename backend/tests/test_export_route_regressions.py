import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.app.api.deps import get_db, get_job_store
from backend.app.api.endpoints import export_routes, job_routes, processing_tasks
from backend.app.api.endpoints.settings import ProcessingSettings
from backend.app.core.database import Database
from backend.app.services import account_erasure, jobs
from backend.app.services.ffmpeg_utils import MediaProbe
from backend.main import app


@pytest.mark.parametrize(
    ("resolution", "deletion_kind"),
    [
        ("srt", "single"),
        ("720x1280", "single"),
        ("srt", "batch"),
        ("720x1280", "account"),
    ],
)
def test_successful_delete_waits_for_export_and_leaves_no_recreated_artifact(
    resolution: str,
    deletion_kind: str,
    client: TestClient,
    monkeypatch,
    user_auth_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    # REGRESSION: deletion could return success while an in-flight subtitle or
    # video export later recreated transcript-derived files for the erased job.
    data_dir = tmp_path / resolution
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_root.mkdir(parents=True)
    monkeypatch.setattr(
        export_routes,
        "data_roots",
        lambda: (data_dir, uploads_dir, artifacts_root),
    )
    monkeypatch.setattr(
        job_routes,
        "data_roots",
        lambda: (data_dir, uploads_dir, artifacts_root),
    )
    monkeypatch.setattr(export_routes.settings, "data_dir", data_dir)

    db = Database()
    store = jobs.JobStore(db)
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db
    export_entered = Event()
    allow_export_write = Event()
    delete_reached_erasure = Event()

    try:
        user = client.get("/auth/me", headers=user_auth_headers).json()
        job_id = f"export-delete-race-{deletion_kind}-{resolution}-{uuid.uuid4().hex}"
        store.create_job(job_id, user["id"])
        artifact_dir = artifacts_root / job_id
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "transcription.json").write_text(
            '[{"start": 0.0, "end": 1.0, "text": "private transcript"}]',
            encoding="utf-8",
        )
        (uploads_dir / f"{job_id}_input.mp4").write_bytes(b"private video")
        store.update_job(job_id, status="completed", result_data={})

        def wait_then_write_subtitle(**kwargs):
            export_entered.set()
            assert allow_export_write.wait(timeout=5)
            export_path = kwargs["export_path"]
            export_path.parent.mkdir(parents=True, exist_ok=True)
            export_path.write_text("private transcript", encoding="utf-8")
            return SimpleNamespace(path=export_path)

        def wait_then_write_video(
            _job_id,
            _input_video,
            destination_dir,
            _resolution,
            _job_store,
            _user_id,
            *,
            subtitle_settings,
            video_crf,
            held_render_slots,
            progress_callback,
        ):
            assert isinstance(video_crf, int)
            assert held_render_slots
            assert callable(progress_callback)
            progress_callback(50)
            export_entered.set()
            assert allow_export_write.wait(timeout=5)
            destination_dir.mkdir(parents=True, exist_ok=True)
            output_path = destination_dir / "processed_720x1280.mp4"
            output_path.write_bytes(b"private rendered video")
            return output_path

        original_job_delete = job_routes.delete_job_workspace
        original_account_delete = account_erasure.delete_job_workspace

        def mark_job_workspace_delete(**kwargs) -> None:
            delete_reached_erasure.set()
            original_job_delete(**kwargs)

        def mark_account_workspace_delete(**kwargs) -> None:
            delete_reached_erasure.set()
            original_account_delete(**kwargs)

        monkeypatch.setattr(export_routes, "export_subtitle_file", wait_then_write_subtitle)
        monkeypatch.setattr(export_routes, "generate_video_variant", wait_then_write_video)
        monkeypatch.setattr(job_routes, "delete_job_workspace", mark_job_workspace_delete)
        monkeypatch.setattr(
            account_erasure,
            "delete_job_workspace",
            mark_account_workspace_delete,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            export_request = executor.submit(
                client.post,
                f"/videos/jobs/{job_id}/export",
                headers=user_auth_headers,
                json={"resolution": resolution},
            )
            assert export_entered.wait(timeout=5)
            if deletion_kind == "single":
                delete_request = executor.submit(
                    client.delete,
                    f"/videos/jobs/{job_id}",
                    headers=user_auth_headers,
                )
            elif deletion_kind == "batch":
                delete_request = executor.submit(
                    client.post,
                    "/videos/jobs/batch-delete",
                    headers=user_auth_headers,
                    json={"job_ids": [job_id]},
                )
            else:
                delete_request = executor.submit(
                    client.delete,
                    "/auth/me",
                    headers=user_auth_headers,
                )
            try:
                assert not delete_reached_erasure.wait(timeout=0.5)
            finally:
                allow_export_write.set()

            export_response = export_request.result(timeout=5)
            delete_response = delete_request.result(timeout=5)

        assert export_response.status_code == 200
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "deleted"
        assert store.get_job(job_id) is None
        assert not artifact_dir.exists()
        assert not any(uploads_dir.glob(f"{job_id}_input.*"))
    finally:
        allow_export_write.set()
        app.dependency_overrides = {}


def test_srt_export_missing_transcript_returns_404(client: TestClient, monkeypatch, user_auth_headers, tmp_path: Path):
    # REGRESSION: missing transcript should preserve its original 404 instead of being wrapped as a 500.
    monkeypatch.setattr(export_routes.settings, "project_root", tmp_path)
    data_dir = tmp_path
    uploads_dir = tmp_path / "uploads"
    artifacts_root = tmp_path / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(export_routes, "data_roots", lambda: (data_dir, uploads_dir, artifacts_root))
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


def test_subtitle_file_export_validates_style_settings(client: TestClient, monkeypatch, user_auth_headers, tmp_path: Path):
    # REGRESSION: subtitle-only exports must enforce the same range checks as video exports.
    monkeypatch.setattr(export_routes.settings, "project_root", tmp_path)
    data_dir = tmp_path
    uploads_dir = tmp_path / "uploads"
    artifacts_root = tmp_path / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(export_routes, "data_roots", lambda: (data_dir, uploads_dir, artifacts_root))
    db = Database()
    store = jobs.JobStore(db)
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        user = client.get("/auth/me", headers=user_auth_headers).json()
        job_id = f"srt-style-validation-{uuid.uuid4().hex}"
        store.create_job(job_id, user["id"])
        artifact_dir = artifacts_root / job_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "transcription.json").write_text(
            '[{"start": 0.0, "end": 1.0, "text": "Hello"}]',
            encoding="utf-8",
        )
        store.update_job(job_id, status="completed", result_data={})

        response = client.post(
            f"/videos/jobs/{job_id}/export",
            headers=user_auth_headers,
            json={"resolution": "srt", "max_subtitle_lines": 99},
        )

        assert response.status_code == 400
        assert "max_subtitle_lines out of range" in response.text
    finally:
        app.dependency_overrides = {}


def test_subtitle_file_export_malformed_transcript_returns_422(client: TestClient, monkeypatch, user_auth_headers, tmp_path: Path):
    # REGRESSION: corrupt persisted captions should be reported as an export contract error, not a generic 500.
    monkeypatch.setattr(export_routes.settings, "project_root", tmp_path)
    data_dir = tmp_path
    uploads_dir = tmp_path / "uploads"
    artifacts_root = tmp_path / "artifacts"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(export_routes, "data_roots", lambda: (data_dir, uploads_dir, artifacts_root))
    db = Database()
    store = jobs.JobStore(db)
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        user = client.get("/auth/me", headers=user_auth_headers).json()
        job_id = f"srt-malformed-{uuid.uuid4().hex}"
        store.create_job(job_id, user["id"])
        artifact_dir = artifacts_root / job_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "transcription.json").write_text(
            '{"start": 0, "end": 1, "text": "not a list"}',
            encoding="utf-8",
        )
        store.update_job(job_id, status="completed", result_data={})

        response = client.post(
            f"/videos/jobs/{job_id}/export",
            headers=user_auth_headers,
            json={"resolution": "srt"},
        )

        assert response.status_code == 422
        assert "Cannot export malformed transcript" in response.text
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


def test_video_export_reuses_exact_cached_render_and_invalidates_on_transcript_change(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    user_auth_headers: dict[str, str],
    tmp_path: Path,
) -> None:
    """Repeated downloads must not burn the same video through FFmpeg again."""
    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_root = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_root.mkdir(parents=True)
    monkeypatch.setattr(
        export_routes,
        "data_roots",
        lambda: (data_dir, uploads_dir, artifacts_root),
    )

    db = Database()
    store = jobs.JobStore(db)
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_db] = lambda: db

    try:
        user = client.get("/auth/me", headers=user_auth_headers).json()
        job_id = f"cached-export-{uuid.uuid4().hex}"
        store.create_job(job_id, user["id"])
        input_video = uploads_dir / f"{job_id}_input.mp4"
        input_video.write_bytes(b"source-video")
        artifact_dir = artifacts_root / job_id
        artifact_dir.mkdir(parents=True)
        (artifact_dir / f"{job_id}_input.srt").write_text(
            "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
            encoding="utf-8",
        )
        transcription_path = artifact_dir / "transcription.json"
        transcription_path.write_text(
            '[{"start": 0, "end": 1, "text": "Hello"}]',
            encoding="utf-8",
        )
        store.update_job(
            job_id,
            status="completed",
            result_data={"video_crf": 12},
        )

        render_crfs: list[int | None] = []

        def fake_generate_variant(
            _job_id: str,
            _input_video: Path,
            destination_dir: Path,
            resolution: str,
            *_args: object,
            video_crf: int | None = None,
            **_kwargs: object,
        ) -> Path:
            render_crfs.append(video_crf)
            output_path = destination_dir / f"processed_{resolution}.mp4"
            output_path.write_bytes(f"render-{len(render_crfs)}".encode())
            return output_path

        monkeypatch.setattr(export_routes, "generate_video_variant", fake_generate_variant)
        payload = {
            "resolution": "1080x1920",
            "video_quality": "balanced",
            "subtitle_size": 85,
        }

        first = client.post(
            f"/videos/jobs/{job_id}/export",
            headers=user_auth_headers,
            json=payload,
        )
        second = client.post(
            f"/videos/jobs/{job_id}/export",
            headers=user_auth_headers,
            json=payload,
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert render_crfs == [23]
        assert second.json()["result_data"]["export_cache"]["1080x1920"]["size"] == len(b"render-1")

        transcription_path.write_text(
            '[{"start": 0, "end": 1, "text": "Changed"}]',
            encoding="utf-8",
        )
        changed = client.post(
            f"/videos/jobs/{job_id}/export",
            headers=user_auth_headers,
            json=payload,
        )

        assert changed.status_code == 200, changed.text
        assert render_crfs == [23, 23]
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

    def fake_process_video_pipeline(**kwargs):
        captured["media_probe"] = kwargs["media_probe"]
        destination = kwargs["output_path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"preview")
        return destination

    monkeypatch.setattr(processing_tasks, "process_video_pipeline", fake_process_video_pipeline)
    job = SimpleNamespace(status="pending")
    job_store = MagicMock()
    job_store.get_job.return_value = job

    proc_settings = ProcessingSettings(
        transcribe_tier="standard",
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
    completed_update = job_store.update_job_if_status.call_args_list[-1].kwargs
    assert completed_update["expected_statuses"] == {"processing"}
    assert completed_update["result_data"]["duration_seconds"] == 12.5
