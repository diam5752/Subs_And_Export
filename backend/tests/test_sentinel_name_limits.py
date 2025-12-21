import pytest
from unittest.mock import MagicMock
from backend.app.core.auth import UserStore, Database

# Simple mock for DbUser to track state changes
class MockDbUser:
    def __init__(self, id, email, name, provider="local"):
        self.id = id
        self.email = email
        self.name = name
        self.provider = provider
        self.password_hash = "hash"
        self.google_sub = None
        self.created_at = "now"
        self.email_verified = True

def test_update_name_enforces_limit():
    """Verify that UserStore REJECTS names longer than 100 chars."""
    mock_db = MagicMock(spec=Database)
    mock_session = MagicMock()
    mock_db.session.return_value.__enter__.return_value = mock_session

    # Mock existing user
    mock_user = MockDbUser(id="123", email="test@example.com", name="Old Name")
    mock_session.get.return_value = mock_user

    store = UserStore(mock_db)
    # 101 chars
    long_name = "A" * 101

    # This should now FAIL
    with pytest.raises(ValueError, match="Name must be at most 100 characters long"):
        store.update_name("123", long_name)

    # Name should NOT be updated
    assert mock_user.name == "Old Name"

def test_upsert_google_user_truncates_long_name():
    """Verify that UserStore TRUNCATES names longer than 100 chars for Google users."""
    mock_db = MagicMock(spec=Database)
    mock_session = MagicMock()
    mock_db.session.return_value.__enter__.return_value = mock_session
    mock_session.scalar.return_value = None # New user

    store = UserStore(mock_db)
    # 150 chars
    long_name = "A" * 150

    # Capture what is added
    added_users = []
    def capture_add(obj):
        added_users.append(obj)
    mock_session.add.side_effect = capture_add

    user = store.upsert_google_user("test@example.com", long_name, "sub123")

    # Should be truncated to 100
    assert len(user.name) == 100
    assert user.name == "A" * 100
