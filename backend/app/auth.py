"""
Backend authentication helpers reuse the shared core implementation.

Importing directly from ``greek_sub_publisher.auth`` keeps the FastAPI API in
sync with the CLI and avoids maintaining duplicate logic.
"""
from greek_sub_publisher.auth import (  # noqa: F401
    User,
    UserStore,
    SessionStore,
    google_oauth_config,
    build_google_flow,
    exchange_google_code,
    _hash_password,
    _hash_token,
    _verify_password,
    _utc_iso,
)

__all__ = [
    "User",
    "UserStore",
    "SessionStore",
    "google_oauth_config",
    "build_google_flow",
    "exchange_google_code",
    "_hash_password",
    "_hash_token",
    "_verify_password",
    "_utc_iso",
]
