from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.core import gcs


def test_refresh_access_token_timeout(monkeypatch):
    """Verify that GCS auth token refresh uses a TimeoutRequest."""
    # Mock imports in gcs
    # We need to ensure GoogleAuthRequest is not None so _require_storage passes
    mock_base_request = MagicMock()
    monkeypatch.setattr(gcs, "GoogleAuthRequest", mock_base_request)
    monkeypatch.setattr(gcs, "storage", MagicMock())

    # Mock client with credentials
    mock_client = MagicMock()
    mock_creds = MagicMock()
    mock_client._credentials = mock_creds

    # Call function
    # This might fail if the code doesn't define TimeoutRequest and uses GoogleAuthRequest directly
    try:
        gcs._refresh_access_token(mock_client)
    except Exception:
        # If it fails due to logic we mock, we catch it.
        # But we want to inspect the 'request' passed to refresh.
        pass

    # Inspect the call to credentials.refresh(request)
    if mock_creds.refresh.called:
        args, _ = mock_creds.refresh.call_args
        request_obj = args[0]
        # We expect the request object to be an instance of a custom class named "TimeoutRequest"
        # OR we can verify it behaves like one if we can.
        # Checking name is easier if we follow the pattern in auth.py
        assert type(request_obj).__name__ == "TimeoutRequest", \
            f"Expected TimeoutRequest, got {type(request_obj).__name__}"
    else:
        pytest.fail("credentials.refresh was not called")

def test_upload_object_timeout(monkeypatch):
    """Verify upload_object passes a timeout."""
    mock_storage = MagicMock()
    monkeypatch.setattr(gcs, "storage", mock_storage)

    mock_client = MagicMock()
    mock_storage.Client.return_value = mock_client
    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    settings = MagicMock()
    settings.bucket = "test-bucket"

    gcs.upload_object(
        settings=settings,
        object_name="test.mp4",
        source=Path("local.mp4"),
        content_type="video/mp4"
    )

    # Check upload_from_filename call args
    assert mock_blob.upload_from_filename.called
    args, kwargs = mock_blob.upload_from_filename.call_args
    assert "timeout" in kwargs, "upload_from_filename missing timeout"
    assert kwargs["timeout"] >= 60

def test_download_object_timeout(monkeypatch):
    """Verify download_object passes a timeout."""
    mock_storage = MagicMock()
    monkeypatch.setattr(gcs, "storage", mock_storage)

    mock_client = MagicMock()
    mock_storage.Client.return_value = mock_client
    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    # Mock blob size
    mock_blob.size = 100

    settings = MagicMock()
    settings.bucket = "test-bucket"

    gcs.download_object(
        settings=settings,
        object_name="test.mp4",
        destination=Path("local.mp4"),
        max_bytes=1000
    )

    # Check download_to_filename call args
    assert mock_blob.download_to_filename.called
    args, kwargs = mock_blob.download_to_filename.call_args
    assert "timeout" in kwargs, "download_to_filename missing timeout"
    assert kwargs["timeout"] >= 60
