"""Test session revocation on password update."""
import pytest


@pytest.fixture
def test_user_data():
    """Test user data."""
    import uuid
    unique_id = uuid.uuid4().hex[:8]
    return {
        "email": f"testuser_{unique_id}@example.com",
        "password": "testpassword123",
        "name": "Test User"
    }

def test_password_update_revokes_sessions(client, test_user_data):
    """Test that updating password revokes other sessions."""
    # 1. Register
    client.post("/auth/register", json=test_user_data)

    # 2. Login Session A
    resp_a = client.post(
        "/auth/token",
        data={
            "username": test_user_data["email"],
            "password": test_user_data["password"]
        }
    )
    token_a = resp_a.json()["access_token"]

    # 3. Login Session B (simulate another device)
    resp_b = client.post(
        "/auth/token",
        data={
            "username": test_user_data["email"],
            "password": test_user_data["password"]
        }
    )
    token_b = resp_b.json()["access_token"]

    # Verify both are valid
    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    assert client.get("/auth/me", headers=headers_a).status_code == 200
    assert client.get("/auth/me", headers=headers_b).status_code == 200

    # 4. Update password using Session A
    new_password = "newpassword456"
    resp_update = client.put(
        "/auth/password",
        json={"password": new_password, "confirm_password": new_password},
        headers=headers_a
    )
    assert resp_update.status_code == 200

    # 5. Verify Session B is revoked
    # If the vulnerability exists, this will return 200 (assert fail)
    # If fixed, this should return 401
    resp_check_b = client.get("/auth/me", headers=headers_b)

    # We expect 401 if secure, but currently it is likely 200
    if resp_check_b.status_code == 200:
        pytest.fail("Session B was not revoked after password update! Vulnerability confirmed.")

    assert resp_check_b.status_code == 401

    # 6. Verify Session A is also revoked (strict interpretation of 'revoke all')
    resp_check_a = client.get("/auth/me", headers=headers_a)
    assert resp_check_a.status_code == 401
