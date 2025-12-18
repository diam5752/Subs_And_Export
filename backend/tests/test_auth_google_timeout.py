from unittest.mock import MagicMock

from backend.app.core import auth


def test_exchange_google_code_timeout(monkeypatch):
    """Verify that Google OAuth calls enforce a timeout."""

    # Mock Flow
    mock_flow = MagicMock()
    mock_flow.credentials.id_token = "fake_token"

    # Mock build_google_flow to return our mock flow
    monkeypatch.setattr(auth, "build_google_flow", lambda cfg: mock_flow)

    # Mock id_token.verify_oauth2_token
    mock_verify = MagicMock(return_value={"email": "test@example.com", "sub": "123"})
    monkeypatch.setattr("google.oauth2.id_token.verify_oauth2_token", mock_verify)

    # Configuration
    cfg = {"client_id": "cid", "client_secret": "cs", "redirect_uri": "uri"}

    # Run function
    auth.exchange_google_code(cfg, "fake_code")

    # Check fetch_token timeout
    args, kwargs = mock_flow.fetch_token.call_args
    assert "timeout" in kwargs, "flow.fetch_token missing timeout"
    assert kwargs["timeout"] >= 10, "flow.fetch_token timeout too short"

    # Check verify_oauth2_token request object
    args, _ = mock_verify.call_args
    request_obj = args[1]

    # Verify it uses our custom class
    assert type(request_obj).__name__ == "TimeoutRequest"

    # Verify behavior: Calling it should inject timeout
    mock_session = MagicMock()
    request_obj.session = mock_session

    # Call the request object
    request_obj("http://example.com")

    # Check if session.request was called with timeout
    assert mock_session.request.called
    c_args, c_kwargs = mock_session.request.call_args
    assert "timeout" in c_kwargs
    assert c_kwargs["timeout"] == 30
