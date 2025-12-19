from unittest.mock import patch

def test_delete_account_error_sanitization(client, user_auth_headers):
    # Mock shutil.rmtree to raise an exception with a path
    # We use a path that should trigger the regex in sanitize_error (/app/...)
    with patch("shutil.rmtree", side_effect=OSError("Permission denied: /app/data/artifacts/job123")):
        # We need to simulate the job existing so delete_account tries to clean it up.
        # Create a job first via API
        files = {"file": ("test_delete.mp4", b"content", "video/mp4")}
        client.post("/videos/process", headers=user_auth_headers, files=files)

        # Now trigger delete. It will call shutil.rmtree on the artifact dir.
        response = client.delete("/auth/me", headers=user_auth_headers)

        assert response.status_code == 500
        detail = response.json()["detail"]
        print(f"Detail: {detail}")

        # After fix, the path should be masked
        assert "/app/data/artifacts/job123" not in detail
        # Check that we either have the redacted path OR a generic error
        assert "[INTERNAL_PATH]" in detail or "internal error" in detail.lower()
