import io

import pytest
from fastapi.testclient import TestClient

from backend.app.api.endpoints import videos
from backend.app.api.endpoints import gcs_routes
from backend.app.api.endpoints import export_routes
from backend.app.core import gcs


def test_gcs_upload_url_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/videos/gcs/upload-url",
        json={"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 123},
    )
    assert resp.status_code == 401


def test_gcs_upload_url_requires_bucket(client: TestClient, user_auth_headers: dict[str, str]) -> None:
    resp = client.post(
        "/videos/gcs/upload-url",
        headers=user_auth_headers,
        json={"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 123},
    )
    assert resp.status_code == 503


def test_gcs_upload_url_happy_path(client: TestClient, user_auth_headers: dict[str, str], monkeypatch) -> None:
    monkeypatch.setenv("GSP_GCS_BUCKET", "test-bucket")
    monkeypatch.setattr(gcs_routes, "generate_signed_upload_url", lambda **_kwargs: "https://signed.example/upload")

    resp = client.post(
        "/videos/gcs/upload-url",
        headers=user_auth_headers,
        json={"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 123},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["upload_url"].startswith("https://signed.example/")
    assert body["upload_id"]
    assert body["object_name"].endswith(".mp4")
    assert body["required_headers"]["Content-Type"] == "video/mp4"


def test_gcs_process_consumes_upload_id(client: TestClient, user_auth_headers: dict[str, str], monkeypatch) -> None:
    monkeypatch.setenv("GSP_GCS_BUCKET", "test-bucket")
    monkeypatch.setattr(gcs_routes, "generate_signed_upload_url", lambda **_kwargs: "https://signed.example/upload")
    monkeypatch.setattr(gcs_routes, "run_gcs_video_processing", lambda **_kwargs: None)
    monkeypatch.setattr(gcs_routes, "reserve_processing_charges", lambda *args, **kwargs: (None, 5000))

    upload_resp = client.post(
        "/videos/gcs/upload-url",
        headers=user_auth_headers,
        json={"filename": "clip.mp4", "content_type": "video/mp4", "size_bytes": 123},
    )
    assert upload_resp.status_code == 200
    upload_id = upload_resp.json()["upload_id"]

    process_resp = client.post(
        "/videos/gcs/process",
        headers=user_auth_headers,
        json={"upload_id": upload_id},
    )
    assert process_resp.status_code == 200
    job_id = process_resp.json()["id"]
    assert job_id

    # Second use should fail (anti-replay)
    process_again = client.post(
        "/videos/gcs/process",
        headers=user_auth_headers,
        json={"upload_id": upload_id},
    )
    assert process_again.status_code == 404


@pytest.mark.skipif(True, reason="Requires GCS credentials at runtime - skip in CI")
def test_export_falls_back_to_gcs_when_input_missing(client: TestClient, user_auth_headers: dict[str, str], monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("GSP_GCS_BUCKET", "test-bucket")
    dummy_settings = videos.get_gcs_settings()
    assert dummy_settings is not None

    data_dir = tmp_path / "data"
    uploads_dir = data_dir / "uploads"
    artifacts_dir = data_dir / "artifacts"
    uploads_dir.mkdir(parents=True)
    artifacts_dir.mkdir(parents=True)
    
    # Patch data_roots in all modules that use it
    monkeypatch.setattr(videos, "_data_roots", lambda: (data_dir, uploads_dir, artifacts_dir))
    monkeypatch.setattr(export_routes, "data_roots", lambda: (data_dir, uploads_dir, artifacts_dir))

    called = {"download": 0}

    def fake_download(**kwargs):
        called["download"] += 1
        destination = kwargs["destination"]
        destination.write_bytes(b"video")
        return len(b"video")

    monkeypatch.setattr(export_routes, "download_object", fake_download)
    monkeypatch.setattr(export_routes, "upload_object", lambda **_kwargs: None)
    monkeypatch.setattr(export_routes, "get_gcs_settings", lambda: dummy_settings)

    def fake_run_processing(
        job_id: str,
        input_path,
        output_path,
        artifact_dir,
        settings,
        job_store,
        history_store=None,
        user=None,
        original_name=None,
        source_gcs_object_name=None,
        **_kwargs,
    ):
        artifact_dir.mkdir(parents=True, exist_ok=True)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"ok")
        result_data = {
            "video_path": "artifacts/out.mp4",
            "artifacts_dir": "artifacts",
            "public_url": "/static/artifacts/out.mp4",
            "artifact_url": "/static/artifacts",
            "transcription_url": "/static/artifacts/transcription.json",
            "source_gcs_object": f"{dummy_settings.uploads_prefix}/u/source.mp4",
        }
        job_store.update_job(job_id, status="completed", progress=100, message="Done!", result_data=result_data)

    monkeypatch.setattr(videos, "run_video_processing", fake_run_processing)

    process_resp = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files={"file": ("clip.mp4", io.BytesIO(b"123"), "video/mp4")},
    )
    assert process_resp.status_code == 200
    job_id = process_resp.json()["id"]

    # Ensure the local input is missing so export triggers the GCS fallback.
    for ext in (".mp4", ".mov", ".mkv"):
        (uploads_dir / f"{job_id}_input{ext}").unlink(missing_ok=True)

    # Patch generate_video_variant to create an export output under artifacts dir.
    def fake_generate_variant(job_id: str, input_video, artifact_dir, resolution, *_args, **_kwargs):
        out = artifact_dir / f"export_{resolution}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"variant")
        return out

    monkeypatch.setattr(export_routes, "generate_video_variant", fake_generate_variant)

    export_resp = client.post(
        f"/videos/jobs/{job_id}/export",
        headers=user_auth_headers,
        json={"resolution": "1080p"},
    )
    assert export_resp.status_code == 200
    assert called["download"] == 1
    assert export_resp.json()["result_data"]["variants"]["1080p"].startswith("/static/")


def test_static_redirects_to_gcs_when_missing(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("GSP_GCS_BUCKET", "test-bucket")
    import backend.main as main

    monkeypatch.setattr(main, "generate_signed_download_url", lambda **_kwargs: "https://signed.example/download")

    with TestClient(main.app) as test_client:
        resp = test_client.get("/static/artifacts/does-not-exist.mp4", follow_redirects=False)
        assert resp.status_code == 302
        assert resp.headers["location"].startswith("https://signed.example/")


def test_gcs_helpers_require_dependency(monkeypatch) -> None:
    monkeypatch.setattr(gcs, "storage", None)
    monkeypatch.setattr(gcs, "GoogleAuthRequest", None)

    settings = gcs.GcsSettings(
        bucket="test-bucket",
        uploads_prefix="uploads",
        static_prefix="static",
        upload_url_ttl_seconds=60,
        download_url_ttl_seconds=60,
        keep_uploads=True,
    )

    with pytest.raises(RuntimeError):
        gcs.generate_signed_upload_url(settings=settings, object_name="uploads/u/clip.mp4", content_type="video/mp4")
