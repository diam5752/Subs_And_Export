
import shutil

from backend.app.core import config


def test_directory_listing_disabled(client):
    """
    Test that directory listing is DISABLED for /static/ endpoints.
    """
    # 1. Setup: Ensure DATA_DIR exists and has a subdirectory
    data_dir = config.PROJECT_ROOT / "data"
    test_subdir = data_dir / "test_listing_vuln"
    test_subdir.mkdir(parents=True, exist_ok=True)

    # Create a file inside
    (test_subdir / "secret.txt").write_text("This should not be listed")

    # 2. Access: Try to list the directory via /static/
    response = client.get("/static/test_listing_vuln")

    # 3. Assert: We expect 404 Not Found (as configured in fix)
    # This confirms directory listing is disabled and existence is hidden
    assert response.status_code == 404, f"Directory listing should be disabled (404), got {response.status_code}"

    # Also check /static/ itself if possible, though config.PROJECT_ROOT/data/static might not be the mapping
    # The route is @app.get("/static/{file_path:path}")
    # accessing /static/ with empty file_path might map to root
    # But usually TestClient handles paths.

    # Cleanup
    shutil.rmtree(test_subdir)
