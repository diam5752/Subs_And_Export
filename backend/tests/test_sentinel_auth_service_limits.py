import pytest
from unittest.mock import MagicMock
from backend.app.core.auth import UserStore, Database

def test_register_local_user_password_length_limit():
    """Verify that UserStore rejects passwords longer than 128 chars."""
    mock_db = MagicMock(spec=Database)
    mock_session = MagicMock()
    mock_db.session.return_value.__enter__.return_value = mock_session
    # Mock no existing user
    mock_session.scalar.return_value = None

    store = UserStore(mock_db)

    # 129 chars
    long_password = "A" * 129

    # This should fail with ValueError about length
    with pytest.raises(ValueError, match="Password must be at most 128 characters long"):
        store.register_local_user("test@example.com", long_password, "Test")

def test_register_local_user_email_length_limit():
    """Verify that UserStore rejects emails longer than 255 chars."""
    mock_db = MagicMock(spec=Database)
    mock_session = MagicMock()
    mock_db.session.return_value.__enter__.return_value = mock_session
    mock_session.scalar.return_value = None

    store = UserStore(mock_db)

    # 256 chars
    long_email = "a" * 243 + "@example.com" # 243 + 1 + 11 + 1 (implicit) ? wait.
    # len("@example.com") is 12.
    # 256 - 12 = 244.
    long_email = "a" * 244 + "@example.com"

    assert len(long_email) == 256

    # This should fail with ValueError about length
    with pytest.raises(ValueError, match="Email must be at most 255 characters long"):
        # We pass a valid password
        store.register_local_user(long_email, "Password123456", "Test")
