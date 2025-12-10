from backend.app.core import auth, database


def test_get_secret_prefers_env_over_file(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text('MY_KEY = "file"')
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_path))
    monkeypatch.setenv("MY_KEY", "env-value")

    assert auth._get_secret("MY_KEY") == "env-value"


def test_get_secret_reads_local_file(monkeypatch, tmp_path):
    secrets_path = tmp_path / "secrets.toml"
    secrets_path.write_text('MY_KEY = "file-value"\nOTHER = 1')
    monkeypatch.delenv("MY_KEY", raising=False)
    monkeypatch.setenv("GSP_SECRETS_FILE", str(secrets_path))

    assert auth._get_secret("MY_KEY") == "file-value"


def test_get_secret_respects_disable_flag(monkeypatch):
    monkeypatch.delenv("MY_KEY", raising=False)
    monkeypatch.setenv("GSP_USE_FILE_SECRETS", "0")
    monkeypatch.delenv("GSP_SECRETS_FILE", raising=False)

    assert auth._get_secret("MY_KEY") is None


def test_derive_frontend_redirect(monkeypatch):
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SITE_URL", raising=False)
    monkeypatch.setenv("NEXT_PUBLIC_APP_URL", "https://example.com")

    assert auth._derive_frontend_redirect() == "https://example.com/login"


def test_database_loads_invalid_json_returns_empty():
    assert database.Database.loads("not valid") == {}
