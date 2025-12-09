"""Pytest configuration for backend tests."""
import pytest
import os
import tempfile

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
