from unittest.mock import MagicMock
from pathlib import Path
import pytest
from backend.app.core import gcs

def test_TimeoutRequest_implementation():
    """Verify TimeoutRequest adds timeout."""
    if not gcs.TimeoutRequest:
        pytest.skip("TimeoutRequest not defined (dependencies missing?)")

    # Instantiate TimeoutRequest with a mock session
    mock_session = MagicMock()
    req = gcs.TimeoutRequest(session=mock_session)

    # Invoke it
    req("http://example.com")

    # Verify timeout was injected
    assert mock_session.request.called
    kwargs = mock_session.request.call_args[1]
    assert "timeout" in kwargs, "Timeout not injected"
    assert kwargs["timeout"] == 30

def test_refresh_access_token_uses_TimeoutRequest(monkeypatch):
    """Verify _refresh_access_token uses the TimeoutRequest class."""
    mock_storage = MagicMock()
    monkeypatch.setattr(gcs, "storage", mock_storage)

    # Mock TimeoutRequest class to verify instantiation
    MockTR = MagicMock()
    monkeypatch.setattr(gcs, "TimeoutRequest", MockTR)

    # Mock client
    mock_client = MagicMock()
    mock_creds = MagicMock()
    mock_creds.token = "fake_token"
    mock_client._credentials = mock_creds

    gcs._refresh_access_token(mock_client)

    assert MockTR.called, "TimeoutRequest was not instantiated"
    assert mock_creds.refresh.called

    # Ensure the instance created from MockTR was passed to refresh
    instance = MockTR.return_value
    args = mock_creds.refresh.call_args[0]
    assert args[0] is instance

def test_upload_object_timeout(monkeypatch):
    """Verify upload_object passes a timeout."""
    mock_storage = MagicMock()
    monkeypatch.setattr(gcs, "storage", mock_storage)

    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()

    mock_storage.Client.return_value = mock_client
    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    settings = MagicMock()
    settings.bucket = "test-bucket"

    gcs.upload_object(
        settings=settings,
        object_name="obj",
        source=Path("path"),
        content_type="video/mp4"
    )

    assert mock_blob.upload_from_filename.called
    kwargs = mock_blob.upload_from_filename.call_args[1]
    assert "timeout" in kwargs, "upload_from_filename called without timeout"
    assert kwargs["timeout"] >= 60

def test_download_object_timeout(monkeypatch):
    """Verify download_object passes a timeout."""
    mock_storage = MagicMock()
    monkeypatch.setattr(gcs, "storage", mock_storage)

    mock_client = MagicMock()
    mock_bucket = MagicMock()
    mock_blob = MagicMock()
    mock_blob.size = 100

    mock_storage.Client.return_value = mock_client
    mock_client.bucket.return_value = mock_bucket
    mock_bucket.blob.return_value = mock_blob

    settings = MagicMock()
    settings.bucket = "test-bucket"

    gcs.download_object(
        settings=settings,
        object_name="obj",
        destination=Path("dest"),
        max_bytes=1000
    )

    assert mock_blob.download_to_filename.called
    kwargs = mock_blob.download_to_filename.call_args[1]
    assert "timeout" in kwargs, "download_to_filename called without timeout"
    assert kwargs["timeout"] >= 60
