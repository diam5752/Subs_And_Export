from backend.app.core.ratelimit import limiter_content, limiter_login


def test_tiktok_upload_rate_limit(client, user_auth_headers):
    """Verify rate limiting on TikTok upload endpoint."""
    limiter_content.reset()
    limit = 10

    # We loop limit + 2 times. The first 'limit' requests should succeed (or at least not be 429).
    # The next ones should be 429.
    for i in range(limit + 2):
        res = client.post(
            "/tiktok/upload",
            headers=user_auth_headers,
            json={
                "access_token": "fake",
                "video_path": "fake.mp4",
                "title": "fake",
                "description": "fake"
            }
        )
        if i < limit:
            assert res.status_code != 429, f"Request {i+1} was rate limited unexpectedly"
        else:
            assert res.status_code == 429, f"Request {i+1} should be rate limited"

def test_tiktok_callback_rate_limit(client, user_auth_headers):
    """Verify rate limiting on TikTok callback endpoint."""
    limiter_login.reset()
    limit = 5

    for i in range(limit + 2):
        res = client.post(
            "/tiktok/callback",
            headers=user_auth_headers,
            json={
                "code": "fake_code",
                "state": "fake_state"
            }
        )
        if i < limit:
            assert res.status_code != 429, f"Request {i+1} was rate limited unexpectedly"
        else:
            assert res.status_code == 429, f"Request {i+1} should be rate limited"
