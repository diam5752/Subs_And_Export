import time
from types import SimpleNamespace
from unittest.mock import MagicMock

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
    assert profile["avatar_url"] == ("https://lh3.googleusercontent.com/a/google-avatar=s96-c")
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


def _mock_database_session() -> tuple[MagicMock, MagicMock]:
    db = MagicMock()
    session = MagicMock()
    db.session.return_value.__enter__.return_value = session
    db.session.return_value.__exit__.return_value = False
    return db, session


def test_user_store_rejects_missing_local_credentials() -> None:
    store = auth.UserStore(MagicMock())
    with pytest.raises(ValueError, match="Email is required"):
        store.register_local_user("   ", "Password1234", "User")
    with pytest.raises(ValueError, match="Password is required"):
        store.register_local_user("user@example.com", "", "User")


def test_user_store_derives_a_name_for_blank_local_registration(monkeypatch) -> None:
    db, session = _mock_database_session()
    store = auth.UserStore(db)
    monkeypatch.setattr(store, "get_user_by_email", lambda _email: None)
    monkeypatch.setattr(auth.PointsStore, "ensure_account", lambda _self, _user_id: None)

    user = store.register_local_user(
        " Person@Example.com ",
        "Password1234",
        "   ",
    )

    assert user.email == "person@example.com"
    assert user.name == "person"
    session.add.assert_called_once()


@pytest.mark.parametrize("sub", ["", "x" * 256])
def test_google_upsert_rejects_missing_or_oversized_subject(sub: str) -> None:
    with pytest.raises(auth.GoogleAuthError, match="subject"):
        auth.UserStore(MagicMock()).upsert_google_user(
            "person@example.com",
            "Person",
            sub,
        )


@pytest.mark.parametrize(
    ("avatar_url", "expected_avatar"),
    [
        ("https://lh3.googleusercontent.com/a/avatar", "https://lh3.googleusercontent.com/a/avatar"),
        ("https://evil.example/avatar", "existing-avatar"),
    ],
)
def test_google_upsert_updates_an_existing_identity_without_recreating_points(
    monkeypatch,
    avatar_url: str,
    expected_avatar: str,
) -> None:
    db, session = _mock_database_session()
    existing = SimpleNamespace(
        id="user-1",
        email="person@example.com",
        name="Old Name",
        provider="google",
        password_hash=None,
        google_sub="google-sub",
        avatar_url="existing-avatar",
        created_at="2026-01-01T00:00:00+00:00",
        email_verified=True,
    )
    session.scalar.return_value = existing
    ensure_account = MagicMock()
    monkeypatch.setattr(auth.PointsStore, "ensure_account", ensure_account)

    user = auth.UserStore(db).upsert_google_user(
        "person@example.com",
        "Updated Name",
        "google-sub",
        avatar_url,
    )

    assert user.name == "Updated Name"
    assert existing.avatar_url == expected_avatar
    session.flush.assert_called_once_with()
    ensure_account.assert_not_called()


def test_user_store_missing_records_are_safe_noops() -> None:
    db, session = _mock_database_session()
    session.get.return_value = None
    store = auth.UserStore(db)

    store.update_name("missing", "Valid Name")
    store.update_password("missing", "Password1234")
    assert store.get_user_by_id("") is None
    store.delete_user_in_session(session, "missing")
    session.delete.assert_not_called()


@pytest.mark.parametrize("password", ["short1", "letters-only-password", "1234567890123"])
def test_password_policy_rejects_weak_passwords(password: str) -> None:
    with pytest.raises(ValueError, match="Password"):
        auth._validate_password_strength(password)


def test_secret_file_without_requested_key_falls_through(monkeypatch, tmp_path) -> None:
    secrets_file = tmp_path / "secrets.toml"
    secrets_file.write_text('OTHER_KEY = "value"', encoding="utf-8")
    monkeypatch.delenv("MISSING_KEY", raising=False)
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_file))

    assert auth._get_secret("MISSING_KEY") is None


def test_optional_google_nonce_accepts_a_missing_cookie() -> None:
    auth._assert_google_nonce({}, expected_nonce_hash=None, require_nonce=False)
