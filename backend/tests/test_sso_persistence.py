from backend.app.core.auth import UserStore


def test_sso_persistence_vulnerability(tmp_path):
    """
    Test that a local user converted to Google SSO retains their password,
    allowing continued access via the old password (which cannot be changed).
    """
    db_path = tmp_path / "test.db"
    user_store = UserStore(path=db_path)

    # 1. Register local user
    email = "victim@example.com"
    password = "SecretPassword123"
    user_store.register_local_user(email, password, "Victim Local")

    local_user = user_store.get_user_by_email(email)
    assert local_user.provider == "local"
    assert local_user.password_hash is not None

    # Verify local login works
    authenticated = user_store.authenticate_local(email, password)
    assert authenticated is not None

    # 2. Simulate Google Login (Upsert)
    # This happens when the user logs in via Google for the first time
    user_store.upsert_google_user(email, "Victim Google", "google-sub-123")

    sso_user = user_store.get_user_by_email(email)
    assert sso_user.provider == "google"
    assert sso_user.google_sub == "google-sub-123"

    # 3. Verify Local Login FAILS (Security Fix)
    # The user is now a "google" user, so the password hash should be gone.
    still_authenticated = user_store.authenticate_local(email, password)

    assert still_authenticated is None

    # Verify hash is gone
    refreshed_user = user_store.get_user_by_email(email)
    assert refreshed_user.password_hash is None
    assert refreshed_user.provider == "google"
