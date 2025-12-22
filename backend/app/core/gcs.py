"""Google Cloud Storage helpers (signed uploads, downloads)."""

from __future__ import annotations

import datetime as dt
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.cloud import storage
except Exception:  # pragma: no cover
    GoogleAuthRequest = None  # type: ignore[assignment]
    storage = None  # type: ignore[assignment]

# Define TimeoutRequest to enforce timeouts on auth calls
if GoogleAuthRequest:
    class TimeoutRequest(GoogleAuthRequest):
        def __call__(self, *args, **kwargs):
            kwargs.setdefault("timeout", 30)
            return super().__call__(*args, **kwargs)
else:
    TimeoutRequest = None

from .config import settings

_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]$")
_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/_-]{0,250}[A-Za-z0-9]$")


@dataclass(frozen=True)
class GcsSettings:
    bucket: str
    uploads_prefix: str
    static_prefix: str
    upload_url_ttl_seconds: int
    download_url_ttl_seconds: int
    keep_uploads: bool


def _require_storage() -> None:
    if storage is None or GoogleAuthRequest is None:
        raise RuntimeError("google-cloud-storage is required; install backend requirements")


def _coerce_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _clamp_ttl_seconds(value: int, default: int) -> int:
    if value <= 0:
        return default
    # Avoid long-lived signed URLs. Large uploads can take time, but hours-long URLs
    # increase replay exposure if leaked.
    return max(60, min(value, 6 * 60 * 60))


def _normalize_prefix(value: str | None, default: str) -> str:
    cleaned = (value or "").strip().strip("/")
    if not cleaned:
        cleaned = default
    if ".." in cleaned or cleaned.startswith(("/", "\\")) or cleaned.endswith(("/", "\\")):
        raise ValueError("Invalid GCS prefix")
    if not _PREFIX_RE.match(cleaned):
        raise ValueError("Invalid GCS prefix")
    return cleaned


def get_gcs_settings() -> GcsSettings | None:
    """Return configured GCS settings, or None when GCS is disabled."""
    bucket = os.getenv("GSP_GCS_BUCKET")
    if not bucket:
        return None
    bucket = bucket.strip()
    if not _BUCKET_RE.match(bucket):
        raise ValueError("Invalid GSP_GCS_BUCKET")
    uploads_prefix = _normalize_prefix(os.getenv("GSP_GCS_UPLOADS_PREFIX"), "uploads")
    static_prefix = _normalize_prefix(os.getenv("GSP_GCS_STATIC_PREFIX"), "static")
    upload_ttl = _clamp_ttl_seconds(int(os.getenv("GSP_GCS_UPLOAD_URL_TTL_SECONDS", "3600")), 3600)
    download_ttl = _clamp_ttl_seconds(int(os.getenv("GSP_GCS_DOWNLOAD_URL_TTL_SECONDS", "600")), 600)
    keep_uploads = _coerce_bool(os.getenv("GSP_GCS_KEEP_UPLOADS"), True)
    return GcsSettings(
        bucket=bucket,
        uploads_prefix=uploads_prefix,
        static_prefix=static_prefix,
        upload_url_ttl_seconds=upload_ttl,
        download_url_ttl_seconds=download_ttl,
        keep_uploads=keep_uploads,
    )


def _refresh_access_token(client: Any) -> str:
    _require_storage()
    credentials = client._credentials
    # Use TimeoutRequest to prevent hanging on auth refresh
    request = TimeoutRequest() if TimeoutRequest else GoogleAuthRequest()  # type: ignore[operator]
    credentials.refresh(request)
    token = credentials.token
    if not token:
        raise RuntimeError("Could not obtain Google access token for signing")
    return token


def _signing_service_account_email(client: Any) -> str:
    _require_storage()
    override = os.getenv("GSP_GCS_SIGNER_EMAIL")
    if override:
        return override.strip()
    credentials = client._credentials
    email = getattr(credentials, "service_account_email", None) or getattr(credentials, "signer_email", None)
    if not email:
        raise RuntimeError("Could not determine signer email; set GSP_GCS_SIGNER_EMAIL")
    return str(email)


def generate_signed_upload_url(
    *,
    settings: GcsSettings,
    object_name: str,
    content_type: str,
    ttl_seconds: int | None = None,
    content_length: int | None = None,
) -> str:
    """
    Generate a V4 signed URL for a direct browser upload (PUT) to GCS.

    Note: In Cloud Run / GCE environments, signed URLs require IAM signBlob permissions
    (typically `roles/iam.serviceAccountTokenCreator` on the runtime service account).
    """
    _require_storage()
    client = storage.Client()
    bucket = client.bucket(settings.bucket)
    blob = bucket.blob(object_name)

    access_token = _refresh_access_token(client)
    signer_email = _signing_service_account_email(client)

    ttl = ttl_seconds if ttl_seconds is not None else settings.upload_url_ttl_seconds
    ttl = _clamp_ttl_seconds(ttl, settings.upload_url_ttl_seconds)

    headers = {}
    if content_length is not None:
        headers["Content-Length"] = str(content_length)

    return blob.generate_signed_url(
        version="v4",
        expiration=dt.timedelta(seconds=ttl),
        method="PUT",
        content_type=content_type,
        service_account_email=signer_email,
        access_token=access_token,
        scheme="https",
        headers=headers if headers else None,
    )


def generate_signed_download_url(
    *,
    settings: GcsSettings,
    object_name: str,
    ttl_seconds: int | None = None,
) -> str:
    """Generate a signed GET URL for downloads (short-lived)."""
    _require_storage()
    client = storage.Client()
    bucket = client.bucket(settings.bucket)
    blob = bucket.blob(object_name)

    access_token = _refresh_access_token(client)
    signer_email = _signing_service_account_email(client)

    ttl = ttl_seconds if ttl_seconds is not None else settings.download_url_ttl_seconds
    ttl = _clamp_ttl_seconds(ttl, settings.download_url_ttl_seconds)

    return blob.generate_signed_url(
        version="v4",
        expiration=dt.timedelta(seconds=ttl),
        method="GET",
        service_account_email=signer_email,
        access_token=access_token,
        scheme="https",
    )


def upload_object(
    *,
    settings: GcsSettings,
    object_name: str,
    source: Path,
    content_type: str | None = None,
) -> None:
    _require_storage()
    client = storage.Client()
    blob = client.bucket(settings.bucket).blob(object_name)
    # Enforce timeout on upload to prevent hanging
    blob.upload_from_filename(str(source), content_type=content_type, timeout=60)


def delete_prefix(*, settings: GcsSettings, prefix: str) -> None:
    _require_storage()
    client = storage.Client()
    bucket = client.bucket(settings.bucket)
    for blob in bucket.list_blobs(prefix=prefix):
        blob.delete()


def download_object(
    *,
    settings: GcsSettings,
    object_name: str,
    destination: Path,
    max_bytes: int,
) -> int:
    """Download a GCS object to disk, enforcing a maximum size."""
    _require_storage()
    client = storage.Client()
    blob = client.bucket(settings.bucket).blob(object_name)
    blob.reload()
    size = blob.size
    if size is None:
        raise RuntimeError("Could not determine object size")
    if size <= 0:
        raise RuntimeError("Empty object")
    if size > max_bytes:
        raise ValueError("Object too large")

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Enforce timeout on download to prevent hanging
    blob.download_to_filename(str(destination), timeout=60)
    return int(size)


def delete_object(*, settings: GcsSettings, object_name: str) -> None:
    _require_storage()
    client = storage.Client()
    client.bucket(settings.bucket).blob(object_name).delete()


def max_upload_bytes(provided_settings: Any | None = None) -> int:
    s = provided_settings or settings
    return int(s.max_upload_mb) * 1024 * 1024
