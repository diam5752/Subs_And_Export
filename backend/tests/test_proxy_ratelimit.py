import uuid

import pytest

from backend.app.core.ratelimit import limiter_register


@pytest.fixture(autouse=True)
def reset_limiter():
    limiter_register.reset()
    yield


@pytest.fixture(autouse=True)
def enable_ratelimit(monkeypatch):
    monkeypatch.delenv("GSP_DISABLE_RATELIMIT", raising=False)


def test_proxy_ip_differentiation(client):
    """
    Verify that X-Forwarded-For headers are respected for rate limiting.
    Without ProxyHeadersMiddleware, all requests appear from the same source (e.g. 'testclient'),
    causing users to share the same rate limit quota (DoS risk).
    """
    pwd = "StrongPassword123!"

    # User A (IP 10.0.0.1) - Consumes 3/3 quota
    # We send X-Forwarded-For. If middleware is missing, app ignores it and uses connection IP.
    headers_a = {"X-Forwarded-For": "10.0.0.1", "X-Forwarded-Proto": "https"}

    # Note: limiter_register limit is 3 per minute
    for i in range(3):
        res = client.post(
            "/auth/register",
            json={"email": f"a{i}_{uuid.uuid4().hex}@ex.com", "password": pwd, "name": "a"},
            headers=headers_a
        )
        assert res.status_code == 200, f"User A request {i} failed: {res.text}"

    # User A - 4th request (Should be blocked)
    res_a_blocked = client.post(
        "/auth/register",
        json={"email": f"a_blocked_{uuid.uuid4().hex}@ex.com", "password": pwd, "name": "a"},
        headers=headers_a
    )
    assert res_a_blocked.status_code == 429, "User A should be rate limited"

    # User B (IP 10.0.0.2) - Should NOT be blocked if middleware is working
    headers_b = {"X-Forwarded-For": "10.0.0.2", "X-Forwarded-Proto": "https"}
    res_b = client.post(
        "/auth/register",
        json={"email": f"b_{uuid.uuid4().hex}@ex.com", "password": pwd, "name": "b"},
        headers=headers_b
    )

    # If middleware is missing, this will be 429 (shared quota with User A).
    # If middleware is present and working, this will be 200 (separate quota).
    assert res_b.status_code == 200, "User B should not be blocked by User A's activity"
