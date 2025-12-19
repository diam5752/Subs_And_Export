import pytest

from backend.app.core.auth import SessionStore, UserStore
from backend.app.core.ratelimit import limiter_auth_change


@pytest.fixture(autouse=True)
def reset_limiter():
    limiter_auth_change.reset()
    yield

def test_auth_mutation_ratelimit(client):
    """Verify authenticated rate limiting on sensitive mutation endpoints."""
    # 1. Access DB from client app state (setup by startup event/conftest)
    db = client.app.state.db

    # 2. Create and login user
    user_store = UserStore(db=db)
    session_store = SessionStore(db=db)

    email = "limit@ex.com"
    pwd = "StrongPassword123!"
    user = user_store.register_local_user(email, pwd, "Limit")
    token = session_store.issue_session(user)
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Consume 5 requests (Limit is 5)
    # We use update_user_me as it is cheapest/safest to loop
    for i in range(5):
        res = client.put(
            "/auth/me",
            json={"name": f"Name{i}"},
            headers=headers
        )
        assert res.status_code == 200, f"Request {i} failed: {res.text}"

    # 4. Next request should fail
    res_fail = client.put(
        "/auth/me",
        json={"name": "Fail"},
        headers=headers
    )
    assert res_fail.status_code == 429, f"Expected 429, got {res_fail.status_code}"
    assert "Too many requests" in res_fail.json()["detail"]

    # 5. Verify password update also blocked (shared quota for mutation)
    res_fail_pwd = client.put(
        "/auth/password",
        json={"password": "NewPassword123!", "confirm_password": "NewPassword123!"},
        headers=headers
    )
    assert res_fail_pwd.status_code == 429

    # 6. Verify delete account also blocked (shared quota for mutation)
    res_fail_del = client.delete(
        "/auth/me",
        headers=headers
    )
    assert res_fail_del.status_code == 429
