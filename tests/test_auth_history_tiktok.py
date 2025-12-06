import pytest

from greek_sub_publisher import auth, database, history, tiktok


class DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tiktok.requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def test_local_register_and_auth(tmp_path):
    db = database.Database(tmp_path / "app.db")
    store = auth.UserStore(db=db)
    user = store.register_local_user("Test@Example.com", "secret", "Tester")
    assert user.email == "test@example.com"
    authed = store.authenticate_local("test@example.com", "secret")
    assert authed and authed.email == "test@example.com"
    with pytest.raises(ValueError):
        store.register_local_user("test@example.com", "secret", "Tester")


def test_session_roundtrip(tmp_path):
    db = database.Database(tmp_path / "app.db")
    store = auth.UserStore(db=db)
    sessions = auth.SessionStore(db=db)
    user = store.register_local_user("persist@example.com", "secret", "Persist")
    token = sessions.issue_session(user, user_agent="pytest")
    assert isinstance(token, str)
    restored = sessions.authenticate(token)
    assert restored and restored.email == user.email
    sessions.revoke(token)
    assert sessions.authenticate(token) is None


def test_google_oauth_config_reads_file(tmp_path, monkeypatch):
    for key in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "GSP_USE_FILE_SECRETS"):
        monkeypatch.delenv(key, raising=False)
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text(
        """
GOOGLE_CLIENT_ID = "cid"
GOOGLE_CLIENT_SECRET = "secret"
GOOGLE_REDIRECT_URI = "http://localhost/callback"
"""
    )
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_path))

    cfg = auth.google_oauth_config()
    assert cfg == {
        "client_id": "cid",
        "client_secret": "secret",
        "redirect_uri": "http://localhost/callback",
    }


def test_google_oauth_config_prefers_frontend_hint(monkeypatch):
    monkeypatch.delenv("GSP_SECRETS_FILE", raising=False)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "cid")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", "https://studio.example.com")

    cfg = auth.google_oauth_config()
    assert cfg
    assert cfg["redirect_uri"] == "https://studio.example.com/login"


def test_history_store_roundtrip(tmp_path):
    db = database.Database(tmp_path / "app.db")
    store = history.HistoryStore(db=db)
    user = auth.User(id="u1", email="a@b.com", name="A", provider="local")
    store.record_event(user, "process", "ran", {"ok": True})
    events = store.recent_for_user(user, limit=5)
    assert len(events) == 1
    assert events[0].data["ok"] is True
    assert events[0].summary == "ran"


def test_tiktok_auth_url_contains_state():
    cfg = {
        "client_key": "ck",
        "client_secret": "cs",
        "redirect_uri": "http://localhost",
    }
    url = tiktok.build_auth_url(cfg, state="abc", scope="video.upload")
    assert "state=abc" in url
    assert "client_key=ck" in url


def test_tiktok_auth_and_upload(monkeypatch, tmp_path):
    cfg = {
        "client_key": "ck",
        "client_secret": "cs",
        "redirect_uri": "http://localhost",
    }

    def fake_post(url, data=None, files=None, timeout=None):
        if url == tiktok.TOKEN_URL:
            return DummyResponse(
                {
                    "data": {
                        "access_token": "tok",
                        "refresh_token": "ref",
                        "expires_in": 120,
                    }
                }
            )
        if url == tiktok.UPLOAD_URL:
            assert data["access_token"] == "tok"
            return DummyResponse({"data": {"error_code": 0, "upload_id": "u123"}})
        raise AssertionError(f"Unexpected URL {url}")

    monkeypatch.setattr(tiktok.requests, "post", fake_post)

    tokens = tiktok.exchange_code_for_token(cfg, "code123")
    assert tokens.access_token == "tok"
    assert tokens.refresh_token == "ref"
    assert not tokens.is_expired()

    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake video")
    payload = tiktok.upload_video(tokens, video_path, "title", "desc")
    assert payload["upload_id"] == "u123"


def test_tiktok_upload_error(monkeypatch, tmp_path):
    tokens = tiktok.TikTokTokens(
        access_token="tok",
        refresh_token=None,
        expires_in=100,
        obtained_at=0,
    )

    def fake_post(url, data=None, files=None, timeout=None):
        return DummyResponse({"data": {"error_code": 1005}}, status_code=200)

    monkeypatch.setattr(tiktok.requests, "post", fake_post)
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"fake video")
    with pytest.raises(tiktok.TikTokError):
        tiktok.upload_video(tokens, video_path, "title", "desc")


def test_tiktok_exchange_error(monkeypatch):
    cfg = {"client_key": "k", "client_secret": "s", "redirect_uri": "u"}

    def fake_post_bad(url, data=None, files=None, timeout=None):
        return DummyResponse({"data": {}})  # Missing access_token

    monkeypatch.setattr(tiktok.requests, "post", fake_post_bad)
    with pytest.raises(tiktok.TikTokError):
        tiktok.exchange_code_for_token(cfg, "bad_code")


def test_tiktok_refresh_error(monkeypatch):
    cfg = {"client_key": "k", "client_secret": "s", "redirect_uri": "u"}

    def fake_post_bad(url, data=None, files=None, timeout=None):
        return DummyResponse({"data": {"error_code": 123}}, status_code=200)

    monkeypatch.setattr(tiktok.requests, "post", fake_post_bad)
    with pytest.raises(tiktok.TikTokError):
        tiktok.refresh_access_token(cfg, "bad_refresh")


def test_tiktok_refresh_success(monkeypatch):
    cfg = {"client_key": "k", "client_secret": "s", "redirect_uri": "u"}

    def fake_post(url, data=None, files=None, timeout=None):
        return DummyResponse({"data": {"access_token": "new", "refresh_token": "r", "expires_in": 10}})

    monkeypatch.setattr(tiktok.requests, "post", fake_post)
    tokens = tiktok.refresh_access_token(cfg, "refresh")
    assert tokens.access_token == "new"
    assert tokens.refresh_token == "r"


def test_upload_video_missing_file(tmp_path):
    tokens = tiktok.TikTokTokens(access_token="tok", refresh_token=None, expires_in=100, obtained_at=0)
    with pytest.raises(FileNotFoundError):
        tiktok.upload_video(tokens, tmp_path / "missing.mp4", "t", "d")


def test_user_store_validation_and_google_update(tmp_path):
    db = database.Database(tmp_path / "app.db")
    store = auth.UserStore(db=db)

    with pytest.raises(ValueError):
        store.register_local_user("   ", "pw", "Name")
    with pytest.raises(ValueError):
        store.register_local_user("person@example.com", "", "Name")

    first = store.upsert_google_user("g@example.com", "G Name", "sub1")
    updated = store.upsert_google_user("g@example.com", "New Name", "sub2")
    assert updated.id == first.id
    assert updated.name == "New Name"
    assert updated.google_sub == "sub2"

    # Google users don't have passwords, so authenticate_local should fail
    assert store.authenticate_local("g@example.com", "anything") is None


def test_session_store_and_password_helpers(tmp_path):
    db = database.Database(tmp_path / "app.db")
    store = auth.UserStore(db=db)
    sessions = auth.SessionStore(db=db)

    user = store.register_local_user("pwcheck@example.com", "pw", "Pw")
    token = sessions.issue_session(user)
    assert sessions.authenticate(token)
    assert sessions.authenticate("") is None

    assert auth._verify_password("pw", "not-a-hash") is False


def test_exchange_google_code_missing_id_token(monkeypatch):
    cfg = {"client_id": "cid", "client_secret": "sec", "redirect_uri": "http://localhost"}

    class FakeFlow:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def fetch_token(self, code=None):  # noqa: ARG002
            return None

        @property
        def credentials(self):
            class Creds:
                id_token = None

            return Creds()

    monkeypatch.setattr(auth, "build_google_flow", lambda cfg: FakeFlow())

    with pytest.raises(ValueError):
        auth.exchange_google_code(cfg, "nope")
