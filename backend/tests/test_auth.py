"""Tests for the auth API endpoints."""

import pytest

from backend.app.api.endpoints import auth as auth_ep
from backend.app.core.database import Database
from backend.app.db.models import DbUser


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


class TestAuthEndpoints:
    """Test authentication endpoints."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "greek-sub-publisher-api"

    def test_register_user(self, client, test_user_data):
        """Test user registration."""
        response = client.post("/auth/register", json=test_user_data)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user_data["email"]
        assert data["name"] == test_user_data["name"]
        assert data["provider"] == "local"
        assert "id" in data

    def test_register_duplicate_user(self, client, test_user_data):
        """Test that duplicate registration fails."""
        # First registration
        client.post("/auth/register", json=test_user_data)
        # Second registration should fail
        response = client.post("/auth/register", json=test_user_data)
        assert response.status_code == 400

    def test_login_success(self, client, test_user_data):
        """Test successful login."""
        # Register first
        client.post("/auth/register", json=test_user_data)
        # Login
        response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["name"] == test_user_data["name"]

    def test_login_wrong_password(self, client, test_user_data):
        """Test login with wrong password."""
        # Register first
        client.post("/auth/register", json=test_user_data)
        # Try to login with wrong password
        response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": "wrongpassword"
            }
        )
        assert response.status_code == 400

    def test_login_nonexistent_user(self, client):
        """Test login with non-existent user."""
        response = client.post(
            "/auth/token",
            data={
                "username": "nonexistent@example.com",
                "password": "anypassword"
            }
        )
        assert response.status_code == 400

    def test_get_current_user(self, client, test_user_data):
        """Test getting current user info."""
        # Register and login
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # Get current user
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == test_user_data["email"]
        assert data["name"] == test_user_data["name"]

    def test_get_current_user_unauthorized(self, client):
        """Test getting current user without auth."""
        response = client.get("/auth/me")
        assert response.status_code == 401

    def test_get_current_user_invalid_token(self, client):
        """Test getting current user with invalid token."""
        response = client.get(
            "/auth/me",
            headers={"Authorization": "Bearer invalid_token"}
        )
        assert response.status_code == 401


class TestVideoEndpoints:
    """Test video processing endpoints."""

    def test_list_jobs_unauthorized(self, client):
        """Test listing jobs without auth."""
        response = client.get("/videos/jobs")
        assert response.status_code == 401

    def test_list_jobs_authorized(self, client, test_user_data):
        """Test listing jobs with auth."""
        # Register and login
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # List jobs
        response = client.get(
            "/videos/jobs",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestUserUpdates:
    """Test user profile updates."""

    def test_update_name(self, client, test_user_data):
        """Test updating user name."""
        # Register and login
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # Update name
        new_name = "Updated Name"
        response = client.put(
            "/auth/me",
            json={"name": new_name},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == new_name

        # Verify persistence
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.json()["name"] == new_name

    def test_update_password(self, client, test_user_data):
        """Test updating password."""
        # Register and login
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # Update password
        new_password = "newpassword456"
        response = client.put(
            "/auth/password",
            json={"password": new_password, "confirm_password": new_password},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200

        # Login with new password
        response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": new_password
            }
        )
        assert response.status_code == 200

    def test_update_password_mismatch(self, client, test_user_data):
        """Test password update with mismatch."""
        # Register and login
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # Update password with mismatch
        # Use a valid password (>=12 chars) to pass validation, so we hit the mismatch check
        response = client.put(
            "/auth/password",
            json={"password": "validpassword123", "confirm_password": "mismatch"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 400

    def test_update_password_external_provider_rejected(self, client, test_user_data, monkeypatch):
        """Password updates are not allowed for non-local users."""
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # Flip the provider to google directly in the DB to simulate external account
        from sqlalchemy import select

        db = Database()
        with db.session() as session:
            user = session.scalar(select(DbUser).where(DbUser.email == test_user_data["email"]).limit(1))
            assert user is not None
            user.provider = "google"

        # Use a valid password (>=12 chars) to pass validation, so we hit the provider check
        response = client.put(
            "/auth/password",
            json={"password": "newpassword123", "confirm_password": "newpassword123"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 400


class TestGoogleOAuthEndpoints:
    def test_google_nonce_requires_config(self, client, monkeypatch):
        monkeypatch.setattr(auth_ep, "google_client_id", lambda: None)
        resp = client.get("/auth/google/nonce")
        assert resp.status_code == 503

    def test_google_nonce_sets_httponly_cookie(self, client, monkeypatch):
        from backend.app.core.auth import google_auth_nonce_hash

        monkeypatch.setattr(auth_ep, "google_client_id", lambda: "cid")
        resp = client.get("/auth/google/nonce")
        assert resp.status_code == 200
        body = resp.json()
        assert body["nonce"]
        assert body["expires_in"] == 600
        assert body["client_id"] == "cid"
        cookie = resp.headers["set-cookie"]
        assert f"gsubs_google_nonce={google_auth_nonce_hash(body['nonce'])}" in cookie
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie

    def test_google_id_token_login_uses_nonce_and_issues_session(self, client, monkeypatch):
        from backend.app.core.auth import google_auth_nonce_hash

        monkeypatch.setattr(auth_ep, "google_client_id", lambda: "cid")
        nonce_response = client.get("/auth/google/nonce")
        nonce = nonce_response.json()["nonce"]
        observed: dict[str, object] = {}

        def fake_verify(
            token: str,
            *,
            expected_nonce_hash: str | None,
            require_nonce: bool,
        ) -> dict[str, str | None]:
            observed.update(
                token=token,
                expected_nonce_hash=expected_nonce_hash,
                require_nonce=require_nonce,
            )
            return {
                "email": "g@example.com",
                "name": "Google User",
                "sub": "subid",
                "avatar_url": "https://lh3.googleusercontent.com/a/avatar=s96-c",
            }

        monkeypatch.setattr(auth_ep, "verify_google_id_token", fake_verify)
        resp = client.post("/auth/google", json={"id_token": "verified-google-token"})
        assert resp.status_code == 200
        assert resp.json()["access_token"]
        assert observed == {
            "token": "verified-google-token",
            "expected_nonce_hash": google_auth_nonce_hash(nonce),
            "require_nonce": True,
        }
        assert "gsubs_google_nonce=" in resp.headers["set-cookie"]
        assert "Max-Age=0" in resp.headers["set-cookie"]
        me = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {resp.json()['access_token']}"},
        )
        assert me.status_code == 200
        # REGRESSION: the verified Google picture must survive the user upsert
        # and be returned by the authenticated profile API.
        assert me.json()["avatar_url"] == (
            "https://lh3.googleusercontent.com/a/avatar=s96-c"
        )

    def test_google_login_rejects_unverified_token_without_leaking_provider_error(
        self,
        client,
        monkeypatch,
    ):
        from backend.app.core.auth import GoogleAuthError

        monkeypatch.setattr(auth_ep, "google_client_id", lambda: "cid")
        client.get("/auth/google/nonce")

        def fail_verify(*_args, **_kwargs):
            raise GoogleAuthError("Google token could not be verified.")

        monkeypatch.setattr(auth_ep, "verify_google_id_token", fail_verify)
        response = client.post("/auth/google", json={"id_token": "bad-token"})

        assert response.status_code == 401
        assert response.json()["detail"] == "Google token could not be verified."

    def test_google_login_cannot_take_over_existing_password_account(
        self,
        client,
        monkeypatch,
    ):
        import secrets

        monkeypatch.setattr(auth_ep, "google_client_id", lambda: "cid")
        suffix = secrets.token_hex(6)
        local_user = {
            "email": f"existing-{suffix}@example.com",
            "password": "existing-pass-123",
            "name": "Existing User",
        }
        assert client.post("/auth/register", json=local_user).status_code == 200
        client.get("/auth/google/nonce")
        monkeypatch.setattr(
            auth_ep,
            "verify_google_id_token",
            lambda *_args, **_kwargs: {
                "email": local_user["email"],
                "name": "Different Google Name",
                "sub": "different-google-sub",
            },
        )

        response = client.post("/auth/google", json={"id_token": "valid-token"})

        assert response.status_code == 401
        assert "cannot automatically link an existing email" in response.json()["detail"]
        local_login = client.post(
            "/auth/token",
            data={"username": local_user["email"], "password": local_user["password"]},
        )
        assert local_login.status_code == 200


class TestDeleteAccount:
    """Test account deletion endpoint."""

    def test_delete_account_success(self, client, test_user_data):
        """Test successful account deletion."""
        # Register user
        client.post("/auth/register", json=test_user_data)
        # Login
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # Delete account
        response = client.delete(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

        # Verify user can't login anymore
        login_again = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        assert login_again.status_code == 400

    def test_delete_account_prevents_repeat_credits(self, client, test_user_data):
        """Deleting and re-registering should not grant new starting credits."""
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"],
            },
        )
        token = login_response.json()["access_token"]

        response = client.delete(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        re_register = client.post("/auth/register", json=test_user_data)
        assert re_register.status_code == 200

        re_login = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"],
            },
        )
        assert re_login.status_code == 200
        re_token = re_login.json()["access_token"]

        points = client.get(
            "/auth/points",
            headers={"Authorization": f"Bearer {re_token}"},
        )
        assert points.status_code == 200
        assert points.json()["balance"] == 0

    def test_delete_account_unauthorized(self, client):
        """Test that deleting account requires authentication."""
        response = client.delete("/auth/me")
        assert response.status_code == 401

    def test_delete_account_error(self, client, test_user_data, monkeypatch):
        """Test 500 error when delete account fails (e.g. session revocation fails)."""
        # Register and login
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        from backend.app.core.auth import SessionStore

        def mock_revoke_all(*args, **kwargs):
            raise Exception("Database connection failed")

        monkeypatch.setattr(SessionStore, "revoke_all_sessions", mock_revoke_all)

        response = client.delete(
            "/auth/me",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 500
        assert "Failed to delete account" in response.json()["detail"]


class TestDeleteJob:
    """Test job deletion endpoint."""

    def test_delete_job_not_found(self, client, test_user_data):
        """Test deleting non-existent job."""
        # Register and login
        client.post("/auth/register", json=test_user_data)
        login_response = client.post(
            "/auth/token",
            data={
                "username": test_user_data["email"],
                "password": test_user_data["password"]
            }
        )
        token = login_response.json()["access_token"]

        # Try to delete non-existent job
        response = client.delete(
            "/videos/jobs/nonexistent-job-id",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 404

    def test_delete_job_unauthorized(self, client):
        """Test that deleting job requires authentication."""
        response = client.delete("/videos/jobs/some-job-id")
        assert response.status_code == 401
