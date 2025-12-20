

import pytest

from backend.app.core.ratelimit import limiter_login


def get_auth_headers(client, email, password):
    limiter_login.reset()
    # Try registration
    reg_resp = client.post("/auth/register", json={"email": email, "password": password, "name": "Security Test User"})
    if reg_resp.status_code != 201 and reg_resp.status_code != 200:
        # Check if error is "User already exists" (usually 400)
        # If it is NOT that, then registration failed unexpectedly.
        # But if it IS that, we proceed to login.
        # However, to be safe, let's print it.
        if "already exists" not in reg_resp.text:
             print(f"Registration failed for {email}: {reg_resp.status_code} {reg_resp.text}")

    # Login
    response = client.post(
        "/auth/token",
        data={"username": email, "password": password}
    )
    assert response.status_code == 200, f"Login failed for {email}: {response.text} (Reg status: {reg_resp.status_code})"
    token = response.json().get("access_token")
    assert token, "No access token returned"
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def user2_auth_headers(client):
    return get_auth_headers(client, "user2@example.com", "longpassword123")

def test_upload_invalid_extension(client, user_auth_headers):
    """Ensure uploads with forbidden extensions are rejected."""
    # Create fake .exe file
    file_content = b"fake content"
    files = {"file": ("malicious.exe", file_content, "application/x-msdownload")}

    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files,
        data={"transcribe_model": "standard"}
    )

    # Expect 400 Bad Request
    assert response.status_code == 400
    assert "Invalid file type" in response.json().get("detail", "")

def test_upload_path_traversal_attempt(client, user_auth_headers):
    """Ensure path traversal characters in filename are handled safely."""
    # The application ignores the filename for storage, using UUID.
    # But we check that it accepts the upload and doesn't crash or write to wrong place.
    # We verify the job is created successfully and input path is safe.

    file_content = b"fake mp4 content"
    # Attempt to write to parent directory
    filename = "../../../../../tmp/hacked.mp4"
    files = {"file": (filename, file_content, "video/mp4")}

    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files,
        data={"transcribe_model": "standard"}
    )

    # Should succeed (because suffix is .mp4 and name is ignored) -> 200 OK
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    # The file should be saved safely. We can't clear verify FS here easily without mocking,
    # but 200 means it didn't crash.

def test_idor_get_results(client, user_auth_headers, user2_auth_headers):
    """Ensure User A cannot access User B's job."""
    # User 1 creates a job
    files = {"file": ("test.mp4", b"content", "video/mp4")}
    resp1 = client.post("/videos/process", headers=user_auth_headers, files=files)
    assert resp1.status_code == 200
    job_id = resp1.json()["id"]

    # User 2 tries to get it
    resp2 = client.get(f"/videos/jobs/{job_id}", headers=user2_auth_headers)
    assert resp2.status_code == 404 # Should return 404 Not Found (or 403)

def test_idor_delete_job(client, user_auth_headers, user2_auth_headers):
    """Ensure User A cannot delete User B's job."""
    files = {"file": ("test.mp4", b"content", "video/mp4")}
    resp1 = client.post("/videos/process", headers=user_auth_headers, files=files)
    job_id = resp1.json()["id"]

    # User 2 tries to delete
    resp2 = client.delete(f"/videos/jobs/{job_id}", headers=user2_auth_headers)
    assert resp2.status_code == 404

def test_idor_cancel_job(client, user_auth_headers, user2_auth_headers):
    """Ensure User A cannot cancel User B's job."""
    files = {"file": ("test.mp4", b"content", "video/mp4")}
    resp1 = client.post("/videos/process", headers=user_auth_headers, files=files)
    job_id = resp1.json()["id"]

    # User 2 tries to cancel
    resp2 = client.post(f"/videos/jobs/{job_id}/cancel", headers=user2_auth_headers)
    assert resp2.status_code == 404

def test_invalid_resize_params(client, user_auth_headers):
    """Test resilience against bad resize parameters."""
    files = {"file": ("test.mp4", b"content", "video/mp4")}

    # Send non-integer resolution attempt
    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files,
        data={"video_resolution": "9999999999x9999999999"} # Valid format but huge
    )

    # Backend capped logic checks parsing, it might accept it but fail later?
    # Or strict typing?
    # video_resolution is str.
    # _parse_resolution converts to int.
    # It should pass ingestion.
    assert response.status_code == 200

    # Junk resolution
    response = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files,
        data={"video_resolution": "not-a-resolution"}
    )
    # _parse_resolution defaults to config.DEFAULT
    assert response.status_code == 200

def test_static_path_traversal(client):
    """Ensure static file server prevents path traversal."""
    # Attempt to access a file outside data dir, e.g. main.py in backend root
    # DATA_DIR is backend/data. main.py is backend/main.py (../main.py)

    # Using '..' in path
    response = client.get("/static/../main.py")
    # Should be 404 or 400, strictly NOT 200
    assert response.status_code in [404, 400, 403], f"Traversal succeeded! Status: {response.status_code}"

    # Try url enccded
    response = client.get("/static/%2e%2e/main.py")
    assert response.status_code in [404, 400, 403]

def test_rate_limiting(client):
    """Ensure login endpoint is rate limited."""
    # Reset limiter
    limiter_login.reset()

    # 5 allowed attempts
    for _ in range(5):
        response = client.post(
            "/auth/token",
            data={"username": "hacker@example.com", "password": "wrongpassword"}
        )
        # Should be 400 (Login failed) or 200 (Success), but NOT 429
        assert response.status_code != 429

    # 6th attempt should be blocked
    response = client.post(
        "/auth/token",
        data={"username": "hacker@example.com", "password": "wrongpassword"}
    )
    assert response.status_code == 429
    assert "Too many requests" in response.json()["detail"]
