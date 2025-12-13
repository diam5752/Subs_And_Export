import uuid

import pytest

from backend.app.core.ratelimit import limiter_register


@pytest.fixture(autouse=True)
def reset_limiter():
    limiter_register.reset()
    yield

def test_spam_register_rate_limit(client):
    """Verify rate limiting prevents spam registration."""

    pwd = "StrongPassword123!"

    # 1. Success
    res1 = client.post("/auth/register", json={"email": f"u1_{uuid.uuid4().hex}@ex.com", "password": pwd, "name": "u1"})
    assert res1.status_code == 200, res1.text

    # 2. Success
    res2 = client.post("/auth/register", json={"email": f"u2_{uuid.uuid4().hex}@ex.com", "password": pwd, "name": "u2"})
    assert res2.status_code == 200, res2.text

    # 3. Success
    res3 = client.post("/auth/register", json={"email": f"u3_{uuid.uuid4().hex}@ex.com", "password": pwd, "name": "u3"})
    assert res3.status_code == 200, res3.text

    # 4. BLOCKED (Limit is 3)
    res4 = client.post("/auth/register", json={"email": f"u4_{uuid.uuid4().hex}@ex.com", "password": pwd, "name": "u4"})
    assert res4.status_code == 429, f"Expected 429, got {res4.status_code}"
    assert "Too many requests" in res4.json()["detail"]
