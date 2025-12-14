

def test_process_rate_limit(client, user_auth_headers):
    """Verify rate limiting prevents flooding the process endpoint."""

    # Create a dummy file content
    file_content = b"dummy content"

    # We need to send form data for required fields
    data = {
        "transcribe_model": "tiny",
        "video_quality": "balanced"
    }

    # 1. First 10 requests should succeed (limit is 10)
    for i in range(10):
        # Create a new file tuple for each request to avoid seek issues
        files = {"file": ("test.mp4", file_content, "video/mp4")}
        res = client.post(
            "/videos/process",
            headers=user_auth_headers,
            files=files,
            data=data
        )
        # We expect 200 OK because the mock environment handles the processing logic
        assert res.status_code == 200, f"Request {i+1} failed: {res.text}"

    # 2. 11th request should be BLOCKED
    files = {"file": ("test.mp4", file_content, "video/mp4")}
    res = client.post(
        "/videos/process",
        headers=user_auth_headers,
        files=files,
        data=data
    )
    assert res.status_code == 429, f"Expected 429, got {res.status_code}"
    assert "Too many requests" in res.json()["detail"]
