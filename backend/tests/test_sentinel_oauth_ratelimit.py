import pytest
from backend.app.core.ratelimit import limiter_login, limiter_auth_change

@pytest.fixture
def reset_limiters():
    limiter_login.reset()
    limiter_auth_change.reset()
    yield

def test_google_url_rate_limit(client, reset_limiters):
    """Verify rate limiting on Google OAuth URL endpoint (unauthenticated)."""
    # limiter_login: 5/min
    limit = 5

    # We loop limit + 2 times.
    for i in range(limit + 2):
        res = client.get("/auth/google/url")
        # Even if 503 (not configured) or 200, it should count towards the limit.
        if i < limit:
            assert res.status_code != 429, f"Request {i+1} was rate limited unexpectedly (status {res.status_code})"
        else:
            assert res.status_code == 429, f"Request {i+1} should be rate limited"
            assert "Too many requests" in res.json()["detail"]

def test_tiktok_url_rate_limit(client, user_auth_headers, reset_limiters):
    """Verify rate limiting on TikTok OAuth URL endpoint (authenticated)."""
    # limiter_auth_change: 5/min
    limit = 5

    for i in range(limit + 2):
        res = client.get(
            "/tiktok/url",
            headers=user_auth_headers
        )
        if i < limit:
            assert res.status_code != 429, f"Request {i+1} was rate limited unexpectedly (status {res.status_code})"
        else:
            assert res.status_code == 429, f"Request {i+1} should be rate limited"
            assert "Too many requests" in res.json()["detail"]
