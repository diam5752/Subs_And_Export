import pytest
from unittest.mock import MagicMock, patch
import app
from greek_sub_publisher import auth

@pytest.fixture
def mock_cookie_manager():
    with patch("app._get_cookie_manager") as mock:
        manager = MagicMock()
        mock.return_value = manager
        yield manager

@pytest.fixture
def mock_st():
    with patch("app.st") as mock:
        mock.session_state = {}
        yield mock

def test_persist_session_sets_cookie(mock_cookie_manager, mock_st):
    """Verify _persist_session sets the auth_cookie."""
    user = auth.User(id="123", email="test@example.com", name="Test", provider="local")
    
    # Mock the session store
    with patch("app.SESSION_STORE") as mock_store:
        mock_store.issue_session.return_value = "new_token"
        
        # Call the function
        app._persist_session(user, mock_cookie_manager)
    
        # Check session state
        assert mock_st.session_state["session_token"] == "new_token"
        assert mock_st.session_state["user"]["email"] == "test@example.com"
        
        # Check cookie was set
        mock_cookie_manager.set.assert_called_once()
        args, kwargs = mock_cookie_manager.set.call_args
        assert args[0] == "auth_token"
        assert args[1] == "new_token"
        assert "expires_at" in kwargs

def test_current_user_reads_cookie(mock_cookie_manager, mock_st):
    """Verify _current_user checks cookie if session_state is empty."""
    # Setup: No session state, but cookie exists
    mock_st.session_state = {}
    mock_cookie_manager.get.return_value = "valid_token"
    
    # Mock the session store to return a user for "valid_token"
    with patch("app.SESSION_STORE") as mock_store:
        user = auth.User(id="123", email="cookie@example.com", name="Cookie User", provider="local")
        mock_store.authenticate.return_value = user
        
        # Call
        result = app._current_user(mock_cookie_manager)
        
        # Verify
        assert result == user
        mock_cookie_manager.get.assert_called_with("auth_token")
        # Should populate session state
        assert mock_st.session_state["session_token"] == "valid_token"
        assert mock_st.session_state["user"]["email"] == "cookie@example.com"

def test_logout_deletes_cookie(mock_cookie_manager, mock_st):
    """Verify _logout_user deletes the cookie."""
    mock_st.session_state = {"session_token": "old_token", "user": {}}
    
    app._logout_user(mock_cookie_manager)
    
    mock_cookie_manager.delete.assert_called_with("auth_token", key="delete_auth_token")
    assert "session_token" not in mock_st.session_state
