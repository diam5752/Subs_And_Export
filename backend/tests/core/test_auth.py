
import time

import pytest

from backend.app.core import auth


def test_verify_password_scrypt_error():
    """Test verification handles scrypt errors gracefully."""
    # Malformed scrypt string
    malformed = "scrypt$1$1$1$salt$badhash"
    assert not auth._verify_password("password", malformed)

    # Missing parts
    assert not auth._verify_password("password", "scrypt$incomplete")

def test_get_secret_fallback(monkeypatch, tmp_path):
    """Test secret resolution priority."""
    # 1. Env var
    monkeypatch.setenv("TEST_SECRET", "env_value")
    assert auth._get_secret("TEST_SECRET") == "env_value"

    # 2. File
    monkeypatch.delenv("TEST_SECRET")
    secrets_file = tmp_path / "secrets.toml"
    secrets_file.write_text('TEST_SECRET = "file_value"')

    # Mock PROJECT_ROOT navigation
    # Defaults traverse parent.parent/config
    # We can just enforce GSP_SECRETS_FILE
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_file))

    assert auth._get_secret("TEST_SECRET") == "file_value"

    # 3. Missing
    monkeypatch.delenv("GSP_SECRETS_FILE")
    # Also ensure default path doesn't exist or doesn't have it (safe assumption usually)
    # But clean approach: Mock logic or ensure env is clean.
    assert auth._get_secret("NONEXISTENT_SECRET") is None

def test_google_client_id_missing(monkeypatch):
    """Google Identity Services stays fail-closed without a public client ID."""
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    assert auth.google_client_id() is None


def test_google_nonce_is_hashed_before_cookie_storage():
    nonce = auth.create_google_auth_nonce()

    assert nonce
    assert nonce not in auth.google_auth_nonce_hash(nonce)
    assert len(auth.google_auth_nonce_hash(nonce)) == 64


def test_verify_google_id_token_enforces_nonce_and_claims(monkeypatch):
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setattr(
        auth.settings,
        "google_oauth_certs_url",
        "http://app-edge:8081/oauth2/v1/certs",
    )
    nonce = auth.create_google_auth_nonce()
    observed: dict[str, object] = {}

    def fake_verify(
        token,
        request,
        audience,
        *,
        certs_url,
        clock_skew_in_seconds,
    ):
        observed.update(
            token=token,
            request=request,
            audience=audience,
            certs_url=certs_url,
            clock_skew_in_seconds=clock_skew_in_seconds,
        )
        return {
            "aud": "google-client",
            "iss": "https://accounts.google.com",
            "email": " User@Example.com ",
            "email_verified": True,
            "name": "Google User",
            "picture": "https://lh3.googleusercontent.com/a/google-avatar=s96-c",
            "sub": "google-subject",
            "nonce": nonce,
            "exp": int(time.time()) + 300,
        }

    monkeypatch.setattr("google.oauth2.id_token.verify_token", fake_verify)

    profile = auth.verify_google_id_token(
        "signed-id-token",
        expected_nonce_hash=auth.google_auth_nonce_hash(nonce),
        require_nonce=True,
    )

    assert profile["email"] == "user@example.com"
    assert profile["name"] == "Google User"
    assert profile["sub"] == "google-subject"
    # REGRESSION: Google profile pictures were discarded after token
    # verification, so the authenticated header could only show an initial.
    assert profile["avatar_url"] == (
        "https://lh3.googleusercontent.com/a/google-avatar=s96-c"
    )
    assert observed["token"] == "signed-id-token"
    assert observed["audience"] == "google-client"
    # REGRESSION: the production backend is intentionally isolated from direct
    # egress, so Google signing certificates must use the internal edge relay.
    assert observed["certs_url"] == "http://app-edge:8081/oauth2/v1/certs"
    assert observed["clock_skew_in_seconds"] == 30


@pytest.mark.parametrize(
    "picture",
    [
        "http://lh3.googleusercontent.com/a/avatar",
        "https://evil.example/avatar.png",
        "https://user@lh3.googleusercontent.com/a/avatar",
        "https://lh3.googleusercontent.com:444/a/avatar",
        "https://lh3.googleusercontent.com/a/avatar#tracking",
        "x" * 2_049,
    ],
)
def test_verify_google_id_token_drops_unsafe_profile_picture(
    monkeypatch,
    picture,
):
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
    nonce = "nonce"
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_token",
        lambda *_args, **_kwargs: {
            "aud": "google-client",
            "iss": "accounts.google.com",
            "email": "user@example.com",
            "email_verified": True,
            "name": "User",
            "picture": picture,
            "sub": "subject",
            "nonce": nonce,
            "exp": int(time.time()) + 300,
        },
    )

    profile = auth.verify_google_id_token(
        "signed-id-token",
        expected_nonce_hash=auth.google_auth_nonce_hash(nonce),
        require_nonce=True,
    )

    assert profile["avatar_url"] is None


@pytest.mark.parametrize(
    ("claim", "value", "message"),
    [
        ("aud", "other-client", "audience"),
        ("iss", "https://evil.example", "issuer"),
        ("email_verified", False, "verified"),
        ("sub", "", "subject"),
        ("sub", "x" * 256, "too long"),
        ("exp", None, "expiry is missing"),
        ("exp", "not-a-timestamp", "expiry is invalid"),
        ("exp", 0, "expired"),
        ("email", "", "missing an email"),
        ("email", "not-an-email", "email is invalid"),
    ],
)
def test_verify_google_id_token_rejects_invalid_claims(
    monkeypatch,
    claim,
    value,
    message,
):
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
    nonce = "nonce"
    payload = {
        "aud": "google-client",
        "iss": "accounts.google.com",
        "email": "user@example.com",
        "email_verified": True,
        "name": "User",
        "sub": "subject",
        "nonce": nonce,
        "exp": int(time.time()) + 300,
    }
    payload[claim] = value
    monkeypatch.setattr("google.oauth2.id_token.verify_token", lambda *_args, **_kwargs: payload)

    with pytest.raises(auth.GoogleAuthError, match=message):
        auth.verify_google_id_token(
            "signed-id-token",
            expected_nonce_hash=auth.google_auth_nonce_hash(nonce),
            require_nonce=True,
        )


def test_verify_google_id_token_rejects_missing_or_wrong_nonce(monkeypatch):
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setattr(
        "google.oauth2.id_token.verify_token",
        lambda *_args, **_kwargs: {
            "aud": "google-client",
            "iss": "accounts.google.com",
            "email": "user@example.com",
            "email_verified": True,
            "sub": "subject",
            "nonce": "wrong",
            "exp": int(time.time()) + 300,
        },
    )

    with pytest.raises(auth.GoogleAuthError, match="nonce"):
        auth.verify_google_id_token(
            "signed-id-token",
            expected_nonce_hash=auth.google_auth_nonce_hash("expected"),
            require_nonce=True,
        )

    with pytest.raises(auth.GoogleAuthError, match="nonce"):
        auth.verify_google_id_token(
            "signed-id-token",
            expected_nonce_hash=None,
            require_nonce=True,
        )


def test_verify_google_id_token_rejects_oversized_input(monkeypatch):
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")

    with pytest.raises(auth.GoogleAuthError, match="too large"):
        auth.verify_google_id_token(
            "x" * 16_385,
            expected_nonce_hash=None,
            require_nonce=False,
        )


def test_verify_google_id_token_fails_closed_before_claim_processing(monkeypatch):
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")

    with pytest.raises(auth.GoogleAuthError, match="required"):
        auth.verify_google_id_token(
            "",
            expected_nonce_hash=None,
            require_nonce=False,
        )

    monkeypatch.delenv("GOOGLE_CLIENT_ID")
    with pytest.raises(auth.GoogleAuthError, match="not configured"):
        auth.verify_google_id_token(
            "signed-id-token",
            expected_nonce_hash=None,
            require_nonce=False,
        )


def test_verify_google_id_token_hides_provider_verification_errors(monkeypatch):
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client")

    def fail_verification(*_args, **_kwargs):
        raise RuntimeError("provider internals")

    monkeypatch.setattr(
        "google.oauth2.id_token.verify_token",
        fail_verification,
    )

    with pytest.raises(auth.GoogleAuthError, match="could not be verified") as error:
        auth.verify_google_id_token(
            "signed-id-token",
            expected_nonce_hash=None,
            require_nonce=False,
        )

    assert "provider internals" not in str(error.value)
