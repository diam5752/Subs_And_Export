"""Tests for the auth API endpoints."""
import pytest
from fastapi.testclient import TestClient
from backend.main import app




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
        response = client.put(
            "/auth/password",
            json={"password": "pwd", "confirm_password": "mismatch"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 400
