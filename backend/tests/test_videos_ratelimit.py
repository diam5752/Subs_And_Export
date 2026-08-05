import pytest

from backend.tests.process_stream import post_process_stream


@pytest.fixture(autouse=True)
def enable_ratelimit(monkeypatch):
    monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)


def test_process_rate_limit(client, user_auth_headers):
    """Verify rate limiting prevents flooding the process endpoint."""
    # Top up points so the rate limiter triggers before points exhaustion.
    me = client.get("/auth/me", headers=user_auth_headers)
    assert me.status_code == 200
    user_id = me.json()["id"]
    from backend.app.core.database import Database
    from backend.app.services.points import PointsStore

    PointsStore(db=Database()).credit(user_id, 5000, reason="test_topup")

    # Create a dummy file content
    file_content = b"dummy content"

    # We need to send form data for required fields
    data = {
        "transcribe_tier": "standard",
        "video_quality": "balanced",
    }

    # 1. First 10 requests should succeed (limit is 10)
    for i in range(10):
        res = post_process_stream(
            client,
            user_auth_headers,
            filename="test.mp4",
            content=file_content,
            metadata=data,
        )
        # We expect 200 OK because the mock environment handles the processing logic
        assert res.status_code == 200, f"Request {i + 1} failed: {res.text}"

    # 2. 11th request should be BLOCKED
    res = post_process_stream(
        client,
        user_auth_headers,
        filename="test.mp4",
        content=file_content,
        metadata=data,
    )
    assert res.status_code == 429, f"Expected 429, got {res.status_code}"
    assert "Too many requests" in res.json()["detail"]
