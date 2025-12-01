import app as streamlit_app


def test_has_secret_key_handles_missing(monkeypatch):
    class RaisingSecrets(dict):
        def __contains__(self, key):
            raise RuntimeError("missing secrets")

    monkeypatch.setattr(streamlit_app.st, "secrets", RaisingSecrets(), raising=False)

    assert streamlit_app._has_secret_key("OPENAI_API_KEY") is False


def test_resolve_openai_api_key_prioritizes_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(streamlit_app.st, "secrets", {"OPENAI_API_KEY": "secret-key"}, raising=False)

    assert streamlit_app._resolve_openai_api_key() == "env-key"



def test_resolve_openai_api_key_from_secrets(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(streamlit_app.st, "secrets", {"OPENAI_API_KEY": "secret-key"}, raising=False)

    assert streamlit_app._resolve_openai_api_key() == "secret-key"


def test_resolve_openai_api_key_handles_secret_errors(monkeypatch):
    class RaisingSecrets(dict):
        def __contains__(self, key):
            raise RuntimeError("missing secrets")

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(streamlit_app.st, "secrets", RaisingSecrets(), raising=False)

    assert streamlit_app._resolve_openai_api_key() is None


def test_load_ai_settings_custom_path(tmp_path, monkeypatch):
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("""
[ai]
enable_by_default = true
model = "gpt-custom"
temperature = 0.75
"""
    )

    settings = streamlit_app._load_ai_settings(settings_path)

    assert settings["enable_by_default"] is True
    assert settings["model"] == "gpt-custom"
    assert settings["temperature"] == 0.75



def test_should_autorun_follows_runtime(monkeypatch):
    monkeypatch.setattr(streamlit_app.st.runtime, "exists", lambda: True)
    assert streamlit_app._should_autorun() is True

    monkeypatch.setattr(streamlit_app.st.runtime, "exists", lambda: False)
    assert streamlit_app._should_autorun() is False
