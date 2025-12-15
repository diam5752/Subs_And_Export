import pytest


@pytest.fixture
def test_user_data_session():
    """Test user data for session security test."""
    import uuid
    unique_id = uuid.uuid4().hex[:8]
    return {
        "email": f"security_test_{unique_id}@example.com",
        "password": "InitialPassword123",
        "name": "Security User"
    }

class TestSessionSecurity:
    """Tests for session security vulnerabilities."""

    def test_sessions_revoked_after_password_change(self, client, test_user_data_session):
        """
        SECURITY VERIFICATION:
        Verify that existing sessions ARE revoked when the password is changed.
        This ensures that if an attacker compromises a session, they lose access when the victim changes their password.
        """
        # 1. Register
        client.post("/auth/register", json=test_user_data_session)

        # 2. Login Device A (Attacker or Old Session)
        resp_a = client.post(
            "/auth/token",
            data={
                "username": test_user_data_session["email"],
                "password": test_user_data_session["password"]
            }
        )
        token_a = resp_a.json()["access_token"]

        # 3. Login Device B (Victim or Current Session)
        resp_b = client.post(
            "/auth/token",
            data={
                "username": test_user_data_session["email"],
                "password": test_user_data_session["password"]
            }
        )
        token_b = resp_b.json()["access_token"]

        # Verify both work initially
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"}).status_code == 200
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {token_b}"}).status_code == 200

        # 4. Change Password (using Token B)
        new_password = "NewPassword456"
        resp_update = client.put(
            "/auth/password",
            json={
                "password": new_password,
                "confirm_password": new_password
            },
            headers={"Authorization": f"Bearer {token_b}"}
        )
        assert resp_update.status_code == 200

        # 5. Verify Token A is REVOKED (The Security Fix)
        # Should return 401 Unauthorized
        check_a = client.get("/auth/me", headers={"Authorization": f"Bearer {token_a}"})
        assert check_a.status_code == 401

        # 6. Verify Token B is also REVOKED (All sessions revoked for safety)
        check_b = client.get("/auth/me", headers={"Authorization": f"Bearer {token_b}"})
        assert check_b.status_code == 401

        # 7. Verify login with OLD password fails
        fail_login = client.post(
             "/auth/token",
             data={
                 "username": test_user_data_session["email"],
                 "password": test_user_data_session["password"]
             }
         )
        assert fail_login.status_code == 400

        # 8. Verify login with NEW password succeeds
        new_login = client.post(
             "/auth/token",
             data={
                 "username": test_user_data_session["email"],
                 "password": new_password
             }
         )
        assert new_login.status_code == 200
