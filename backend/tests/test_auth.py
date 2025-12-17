"""Tests for the auth API endpoints."""
import sys
import types

import pytest

from backend.app.api.endpoints import auth as auth_ep
from backend.app.core import auth as backend_auth
from backend.app.core.database import Database


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
        db = Database()
        with db.connect() as conn:
            conn.execute("UPDATE users SET provider = 'google' WHERE email = ?", (test_user_data["email"],))

        # Use a valid password (>=12 chars) to pass validation, so we hit the provider check
        response = client.put(
            "/auth/password",
            json={"password": "newpassword123", "confirm_password": "newpassword123"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 400


class TestGoogleOAuthEndpoints:
    def test_google_url_requires_config(self, client, monkeypatch):
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
        monkeypatch.setattr(auth_ep, "google_oauth_config", lambda: None)
        resp = client.get("/auth/google/url")
        assert resp.status_code == 503

    def test_google_url_builds_auth_link(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
        monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost")

        class DummyFlow:
            called = False

            @classmethod
            def from_client_config(cls, cfg, scopes, redirect_uri=None):
                cls.called = True
                inst = cls()
                inst.cfg = cfg
                inst.scopes = scopes
                inst.redirect_uri = redirect_uri
                return inst

            def authorization_url(self, **kwargs):
                return "http://example.com/auth", None

        # Inject fake Flow into the module import path used by build_google_flow
        fake_module = types.SimpleNamespace(Flow=DummyFlow)
        monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", fake_module)

        resp = client.get("/auth/google/url")
        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_url"].startswith("http://example.com/auth")
        assert body["state"]
        assert DummyFlow.called is True

    def test_google_callback_requires_config(self, client, monkeypatch):
        monkeypatch.setattr(auth_ep, "google_oauth_config", lambda: None)
        resp = client.post("/auth/google/callback", json={"code": "c", "state": "s"})
        assert resp.status_code == 503

    def test_google_callback_success_and_failure(self, client, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "sec")
        monkeypatch.setenv("GOOGLE_REDIRECT_URI", "http://localhost")

        # Stub out flow + token verification
        class FakeFlow:
            def __init__(self):
                self.credentials = types.SimpleNamespace(id_token="tok")

            def authorization_url(self, **_kwargs):
                return "http://example.com/auth", None

            def fetch_token(self, code):
                self.fetched = code

        monkeypatch.setitem(
            sys.modules,
            "google_auth_oauthlib.flow",
            types.SimpleNamespace(Flow=types.SimpleNamespace(from_client_config=lambda cfg, scopes, redirect_uri=None: FakeFlow())),
        )
        monkeypatch.setitem(
            sys.modules,
            "google.auth.transport.requests",
            types.SimpleNamespace(Request=lambda: "req"),
        )
        monkeypatch.setitem(
            sys.modules,
            "google.oauth2.id_token",
            types.SimpleNamespace(verify_oauth2_token=lambda tok, req, client_id: {"email": "g@example.com", "name": None, "sub": "subid"}),
        )

        # Patch exchange to exercise both success and error branches
        monkeypatch.setattr(auth_ep, "exchange_google_code", backend_auth.exchange_google_code)

        # Get a valid state
        state = client.get("/auth/google/url").json()["state"]

        # Success path
        resp = client.post("/auth/google/callback", json={"code": "123", "state": state})
        assert resp.status_code == 200
        assert resp.json()["access_token"]

        # Failure path
        state2 = client.get("/auth/google/url").json()["state"]
        monkeypatch.setattr(auth_ep, "exchange_google_code", lambda cfg, code: (_ for _ in ()).throw(RuntimeError("boom")))
        resp_fail = client.post("/auth/google/callback", json={"code": "bad", "state": state2})
        assert resp_fail.status_code == 400


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
