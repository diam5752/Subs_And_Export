from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.api_core.exceptions import NotFound

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
    mock_client = MagicMock()
    monkeypatch.setattr(gcs, "_storage_client", lambda: mock_client)
    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    settings = MagicMock()
    settings.bucket = "test-bucket"

    gcs.upload_object(settings=settings, object_name="test.mp4", source=Path("local.mp4"), content_type="video/mp4")

    # Check upload_from_filename call args
    assert mock_blob.upload_from_filename.called
    args, kwargs = mock_blob.upload_from_filename.call_args
    assert "timeout" in kwargs, "upload_from_filename missing timeout"
    assert kwargs["timeout"] >= 60


def test_download_object_timeout(monkeypatch):
    """Verify download_object passes a timeout."""
    mock_client = MagicMock()
    monkeypatch.setattr(gcs, "_storage_client", lambda: mock_client)
    mock_bucket = MagicMock()
    mock_client.bucket.return_value = mock_bucket
    mock_blob = MagicMock()
    mock_bucket.blob.return_value = mock_blob

    # Mock blob size
    mock_blob.size = 100

    settings = MagicMock()
    settings.bucket = "test-bucket"

    gcs.download_object(settings=settings, object_name="test.mp4", destination=Path("local.mp4"), max_bytes=1000)

    # Check download_to_filename call args
    assert mock_blob.download_to_filename.called
    args, kwargs = mock_blob.download_to_filename.call_args
    assert "timeout" in kwargs, "download_to_filename missing timeout"
    assert kwargs["timeout"] >= 60


def test_signed_download_forwards_content_disposition(monkeypatch):
    """The GCS fallback must preserve the same browser download filename."""
    mock_client = MagicMock()
    monkeypatch.setattr(gcs, "_storage_client", lambda: mock_client)
    mock_blob = mock_client.bucket.return_value.blob.return_value
    mock_blob.generate_signed_url.return_value = "https://signed.example/download"
    settings = MagicMock(download_url_ttl_seconds=300)

    result = gcs.generate_signed_download_url(
        settings=settings,
        object_name="static/export.mp4",
        response_disposition="attachment; filename*=UTF-8''E%20Isous_subs.mp4",
    )

    assert result == "https://signed.example/download"
    assert mock_blob.generate_signed_url.call_args.kwargs["response_disposition"].endswith("E%20Isous_subs.mp4")


def test_storage_client_reports_missing_optional_dependency(monkeypatch):
    """The mock runtime can import the app without installing the GCS SDK."""

    def missing_storage(_module_name: str):
        raise ModuleNotFoundError("google.cloud.storage")

    monkeypatch.setattr(gcs.importlib, "import_module", missing_storage)

    with pytest.raises(RuntimeError, match="Google Cloud Storage support is not installed"):
        gcs._storage_client()


def test_delete_object_is_idempotent_only_when_object_is_missing(
    monkeypatch,
) -> None:
    mock_client = MagicMock()
    mock_blob = mock_client.bucket.return_value.blob.return_value
    monkeypatch.setattr(gcs, "_storage_client", lambda: mock_client)
    settings = MagicMock(bucket="test-bucket")

    mock_blob.delete.side_effect = NotFound("missing")
    gcs.delete_object(settings=settings, object_name="static/missing.mp4")
    # REGRESSION: privacy erasure previously used an unbounded provider call
    # and could hang indefinitely during a GCS outage.
    assert mock_blob.delete.call_args.kwargs["timeout"] >= 60

    mock_blob.delete.side_effect = RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError, match="provider unavailable"):
        gcs.delete_object(
            settings=settings,
            object_name="static/not-deleted.mp4",
        )


def test_delete_object_preserves_provider_error_when_exception_types_are_unavailable(
    monkeypatch,
) -> None:
    mock_client = MagicMock()
    provider_error = RuntimeError("provider unavailable")
    mock_client.bucket.return_value.blob.return_value.delete.side_effect = provider_error
    monkeypatch.setattr(gcs, "_storage_client", lambda: mock_client)
    monkeypatch.setattr(
        gcs.importlib,
        "import_module",
        MagicMock(side_effect=ModuleNotFoundError("google.api_core.exceptions")),
    )

    with pytest.raises(RuntimeError, match="provider unavailable") as caught:
        gcs.delete_object(
            settings=MagicMock(bucket="test-bucket"),
            object_name="static/not-deleted.mp4",
        )

    assert caught.value is provider_error
