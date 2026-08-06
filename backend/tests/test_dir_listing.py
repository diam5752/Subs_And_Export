
import shutil
import uuid
from urllib.parse import quote

from backend.app.core.database import Database
from backend.app.services.jobs import JobStore
from backend.main import DATA_DIR


def test_directory_listing_disabled(client, user_auth_headers):
    """
    Test that directory listing is DISABLED for /static/ endpoints.
    """
    # 1. Setup: Ensure DATA_DIR exists and has a subdirectory
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    job_id = f"listing-{uuid.uuid4().hex}"
    store = JobStore(Database())
    store.create_job(job_id, user_id)
    test_subdir = DATA_DIR / "artifacts" / job_id / "nested"
    test_subdir.mkdir(parents=True, exist_ok=True)

    # Create a file inside
    (test_subdir / "secret.txt").write_text("This should not be listed")

    # 2. Access: Try to list the directory via /static/
    response = client.get(
        f"/static/artifacts/{job_id}/nested",
        headers=user_auth_headers,
    )

    # 3. Assert: We expect 404 Not Found (as configured in fix)
    # This confirms directory listing is disabled and existence is hidden
    assert response.status_code == 404, f"Directory listing should be disabled (404), got {response.status_code}"

    # Also check /static/ itself if possible, though config.PROJECT_ROOT/data/static might not be the mapping
    # The route is @app.get("/static/{file_path:path}")
    # accessing /static/ with empty file_path might map to root
    # But usually TestClient handles paths.

    # Cleanup
    shutil.rmtree(test_subdir.parent)
    store.delete_job(job_id)


def test_static_download_uses_requested_safe_export_filename(client, user_auth_headers) -> None:
    """REGRESSION: the response header overrode the browser's _subs filename."""
    user_id = client.get("/auth/me", headers=user_auth_headers).json()["id"]
    job_id = f"download-{uuid.uuid4().hex}"
    store = JobStore(Database())
    store.create_job(job_id, user_id)
    export_path = DATA_DIR / "artifacts" / job_id / "processed_1080x1920.mp4"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_bytes(b"video")

    try:
        filename = "Ε Isous_subs.mp4"
        response = client.get(
            f"/static/artifacts/{job_id}/processed_1080x1920.mp4",
            headers=user_auth_headers,
            params={"download": "true", "filename": filename},
        )

        assert response.status_code == 200
        disposition = response.headers["content-disposition"]
        assert "attachment" in disposition
        assert quote(filename) in disposition
        assert "processed_1080x1920" not in disposition
    finally:
        shutil.rmtree(export_path.parent, ignore_errors=True)
        store.delete_job(job_id)
