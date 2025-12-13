"""Pytest configuration for backend tests."""

import os
import sys
import tempfile
from unittest.mock import MagicMock

import pytest

# Mock module dependencies that might be missing
sys.modules["stable_whisper"] = MagicMock()
sys.modules["moviepy"] = MagicMock()
sys.modules["moviepy.editor"] = MagicMock()
sys.modules["moviepy.video.io.VideoFileClip"] = MagicMock()

# Set test environment
os.environ["APP_ENV"] = "test"
os.environ["PIPELINE_LOGGING"] = "0"
# Allow test client hosts in TrustedHostMiddleware
os.environ["GSP_TRUSTED_HOSTS"] = "localhost,127.0.0.1,testserver,testclient"


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Use a temporary database for tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        os.environ["GSP_DATABASE_PATH"] = f.name
    yield
    # Cleanup
    try:
        os.unlink(os.environ["GSP_DATABASE_PATH"])
    except:
        pass


@pytest.fixture
def client():
    """Create a test client."""
    from fastapi.testclient import TestClient

    from backend.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset_login_rate_limiter() -> None:
    """
    Reset the login rate limiter between tests.

    The /auth/token endpoint is protected by a strict per-IP limiter (5/min).
    Without resetting, test suites can flake depending on execution speed/order.
    """
    from backend.app.core.ratelimit import limiter_login, limiter_processing, limiter_register

    limiter_login.reset()
    limiter_register.reset()
    limiter_processing.reset()


@pytest.fixture
def user_auth_headers(client):
    """Return auth headers for a test user."""
    from backend.app.core.ratelimit import limiter_login, limiter_register
    limiter_login.reset()
    limiter_register.reset()

    email = "test@example.com"
    password = "testpassword123"
    client.post("/auth/register", json={"email": email, "password": password, "name": "Test User"})
    response = client.post(
        "/auth/token",
        data={"username": email, "password": password}
    )
    token = response.json().get("access_token")
    if not token:
        # If user already exists (shared db), try login
        response = client.post(
            "/auth/token",
            data={"username": email, "password": password}
        )
        token = response.json().get("access_token")

    return {"Authorization": f"Bearer {token}"}
