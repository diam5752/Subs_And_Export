from pathlib import Path
from unittest.mock import MagicMock

from backend.app.core import gcs


def test_refresh_access_token_timeout(monkeypatch):
    """Verify that GCS auth token refresh uses a TimeoutRequest."""
    mock_client = MagicMock()
    mock_creds = MagicMock()
    mock_creds.token = "access-token"
    mock_client._credentials = mock_creds

    assert gcs._refresh_access_token(mock_client) == "access-token"

    request_obj = mock_creds.refresh.call_args.args[0]
    assert isinstance(request_obj, gcs.TimeoutRequest)

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


def test_signed_download_forwards_content_disposition(monkeypatch):
    """The GCS fallback must preserve the same browser download filename."""
    mock_storage = MagicMock()
    monkeypatch.setattr(gcs, "storage", mock_storage)
    mock_blob = mock_storage.Client.return_value.bucket.return_value.blob.return_value
    mock_blob.generate_signed_url.return_value = "https://signed.example/download"
    settings = MagicMock(download_url_ttl_seconds=300)

    result = gcs.generate_signed_download_url(
        settings=settings,
        object_name="static/export.mp4",
        response_disposition="attachment; filename*=UTF-8''E%20Isous_subs.mp4",
    )

    assert result == "https://signed.example/download"
    assert mock_blob.generate_signed_url.call_args.kwargs["response_disposition"].endswith(
        "E%20Isous_subs.mp4"
    )
