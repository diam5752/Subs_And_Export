"""Short-lived, exact-artifact grants for cross-browser downloads."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any, cast

GRANT_VERSION = 1
MIN_SECRET_BYTES = 32
MIN_TTL_SECONDS = 60
MAX_TTL_SECONDS = 600
MAX_TOKEN_CHARS = 4_096
MAX_FILE_PATH_CHARS = 1_024
MAX_FILENAME_CHARS = 255
MAX_USER_ID_CHARS = 128
_BASE64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class DownloadGrantError(ValueError):
    """Raised when a download grant cannot be safely created or accepted."""


@dataclass(frozen=True, slots=True)
class DownloadGrantClaims:
    user_id: str
    file_path: str
    filename: str
    issued_at: int
    expires_at: int


def _secret_bytes(secret: str) -> bytes:
    encoded = secret.encode("utf-8")
    if len(encoded) < MIN_SECRET_BYTES:
        raise DownloadGrantError("Download grant secret is too short")
    return encoded


def _validate_ttl(ttl_seconds: int) -> None:
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise DownloadGrantError("Download grant TTL is invalid")
    if not MIN_TTL_SECONDS <= ttl_seconds <= MAX_TTL_SECONDS:
        raise DownloadGrantError("Download grant TTL is outside the safe range")


def _validate_file_path(file_path: str) -> None:
    if not file_path or len(file_path) > MAX_FILE_PATH_CHARS or "\\" in file_path:
        raise DownloadGrantError("Download grant path is invalid")
    parts = file_path.split("/")
    if (
        len(parts) < 3
        or parts[0] != "artifacts"
        or any(not part or part in {".", ".."} for part in parts)
        or any(any(ord(character) < 32 or ord(character) == 127 for character in part) for part in parts)
    ):
        raise DownloadGrantError("Download grant path is invalid")


def _validate_claim_text(value: str, *, label: str, maximum: int) -> None:
    if not value or len(value) > maximum or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise DownloadGrantError(f"Download grant {label} is invalid")


def _encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode_base64url(value: str) -> bytes:
    if not value or _BASE64URL_RE.fullmatch(value) is None:
        raise DownloadGrantError("Download grant encoding is invalid")
    padding = "=" * (-len(value) % 4)
    try:
        return base64.b64decode(
            value + padding,
            altchars=b"-_",
            validate=True,
        )
    except (ValueError, TypeError) as exc:
        raise DownloadGrantError("Download grant encoding is invalid") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DownloadGrantError("Download grant payload is invalid")
        result[key] = value
    return result


def create_download_grant(
    *,
    secret: str,
    user_id: str,
    file_path: str,
    filename: str,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    """Sign an exact user, artifact path, filename and short expiry."""
    secret_bytes = _secret_bytes(secret)
    _validate_ttl(ttl_seconds)
    _validate_file_path(file_path)
    _validate_claim_text(user_id, label="user", maximum=MAX_USER_ID_CHARS)
    _validate_claim_text(filename, label="filename", maximum=MAX_FILENAME_CHARS)
    issued_at = int(time.time()) if now is None else now
    if isinstance(issued_at, bool) or not isinstance(issued_at, int) or issued_at < 0:
        raise DownloadGrantError("Download grant issue time is invalid")

    payload = {
        "exp": issued_at + ttl_seconds,
        "iat": issued_at,
        "name": filename,
        "path": file_path,
        "uid": user_id,
        "v": GRANT_VERSION,
    }
    encoded_payload = _encode_base64url(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
    )
    signature = hmac.new(
        secret_bytes,
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{encoded_payload}.{_encode_base64url(signature)}"


def _decode_signed_payload(token: str, *, secret_bytes: bytes) -> dict[str, Any]:
    if not token or len(token) > MAX_TOKEN_CHARS or token.count(".") != 1:
        raise DownloadGrantError("Download grant is malformed")
    encoded_payload, encoded_signature = token.split(".", 1)
    if _BASE64URL_RE.fullmatch(encoded_payload) is None:
        raise DownloadGrantError("Download grant encoding is invalid")
    supplied_signature = _decode_base64url(encoded_signature)
    expected_signature = hmac.new(
        secret_bytes,
        encoded_payload.encode("ascii", errors="strict"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise DownloadGrantError("Download grant signature is invalid")
    try:
        payload = json.loads(
            _decode_base64url(encoded_payload).decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DownloadGrantError("Download grant payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {"exp", "iat", "name", "path", "uid", "v"}:
        raise DownloadGrantError("Download grant payload is invalid")
    return cast(dict[str, Any], payload)


def _validated_claim_values(
    payload: dict[str, Any],
    *,
    ttl_seconds: int,
) -> tuple[str, str, str, int, int]:
    version = payload["v"]
    issued_at = payload["iat"]
    expires_at = payload["exp"]
    user_id = payload["uid"]
    file_path = payload["path"]
    filename = payload["name"]
    if version != GRANT_VERSION:
        raise DownloadGrantError("Download grant version is invalid")
    if (
        isinstance(issued_at, bool)
        or not isinstance(issued_at, int)
        or isinstance(expires_at, bool)
        or not isinstance(expires_at, int)
        or expires_at - issued_at != ttl_seconds
    ):
        raise DownloadGrantError("Download grant timing is invalid")
    if not isinstance(user_id, str) or not isinstance(file_path, str) or not isinstance(filename, str):
        raise DownloadGrantError("Download grant claims are invalid")
    _validate_claim_text(user_id, label="user", maximum=MAX_USER_ID_CHARS)
    _validate_claim_text(filename, label="filename", maximum=MAX_FILENAME_CHARS)
    _validate_file_path(file_path)
    return user_id, file_path, filename, issued_at, expires_at


def _validate_grant_window(*, issued_at: int, expires_at: int, now: int | None) -> None:
    current_time = int(time.time()) if now is None else now
    if isinstance(current_time, bool) or not isinstance(current_time, int) or current_time < 0 or issued_at < 0:
        raise DownloadGrantError("Download grant current time is invalid")
    if issued_at > current_time + 30:
        raise DownloadGrantError("Download grant is not active")
    if current_time >= expires_at:
        raise DownloadGrantError("Download grant has expired")


def validate_download_grant(
    token: str,
    *,
    secret: str,
    expected_file_path: str,
    ttl_seconds: int,
    now: int | None = None,
) -> DownloadGrantClaims:
    """Validate a grant without disclosing which claim failed to the caller."""
    secret_bytes = _secret_bytes(secret)
    _validate_ttl(ttl_seconds)
    _validate_file_path(expected_file_path)
    payload = _decode_signed_payload(token, secret_bytes=secret_bytes)
    user_id, file_path, filename, issued_at, expires_at = _validated_claim_values(
        payload,
        ttl_seconds=ttl_seconds,
    )
    if not hmac.compare_digest(
        file_path.encode("utf-8"),
        expected_file_path.encode("utf-8"),
    ):
        raise DownloadGrantError("Download grant is for a different artifact")

    _validate_grant_window(issued_at=issued_at, expires_at=expires_at, now=now)
    return DownloadGrantClaims(
        user_id=user_id,
        file_path=file_path,
        filename=filename,
        issued_at=issued_at,
        expires_at=expires_at,
    )
