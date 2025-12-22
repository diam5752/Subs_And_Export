import pytest
from unittest.mock import MagicMock
from backend.app.core.auth import UserStore, User
from backend.app.api.deps import get_user_store, get_session_store

@pytest.fixture
def mock_user_store():
    mock = MagicMock(spec=UserStore)
    user = User(id="user123", email="test@example.com", name="Test", provider="local", password_hash="hash")
    mock.authenticate_local.return_value = user
    return mock

@pytest.fixture
def mock_session_store():
    mock = MagicMock()
    mock.issue_session.return_value = "fake_token"
    return mock

@pytest.fixture
def client_with_mocks(client, mock_user_store, mock_session_store):
    from backend.main import app
    app.dependency_overrides[get_user_store] = lambda: mock_user_store
    app.dependency_overrides[get_session_store] = lambda: mock_session_store
    yield client
    app.dependency_overrides = {}

def test_login_long_username(client_with_mocks, mock_user_store):
    """Test that excessively long username is rejected."""
    long_email = "a" * 256 + "@example.com"
    response = client_with_mocks.post(
        "/auth/token",
        data={
            "username": long_email,
            "password": "password123"
        }
    )
    # Expect 400 Bad Request with "Email too long"
    assert response.status_code == 400
    assert "email too long" in response.json()["detail"].lower()
    # Verify we didn't call the store
    mock_user_store.authenticate_local.assert_not_called()

def test_login_long_password(client_with_mocks, mock_user_store):
    """Test that excessively long password is rejected."""
    long_password = "a" * 129
    response = client_with_mocks.post(
        "/auth/token",
        data={
            "username": "valid@example.com",
            "password": long_password
        }
    )
    assert response.status_code == 400
    assert "password too long" in response.json()["detail"].lower()
    mock_user_store.authenticate_local.assert_not_called()

def test_login_normal_length(client_with_mocks, mock_user_store, mock_session_store):
    """Test that normal length inputs are accepted."""
    response = client_with_mocks.post(
        "/auth/token",
        data={
            "username": "user@example.com",
            "password": "password123"
        }
    )
    assert response.status_code == 200
    assert response.json()["access_token"] == "fake_token"
    mock_user_store.authenticate_local.assert_called_once()
