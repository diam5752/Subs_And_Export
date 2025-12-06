from pathlib import Path

from greek_sub_publisher.app_settings import AppSettings, load_app_settings


def test_load_app_settings_from_file(tmp_path: Path):
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        """
[ai]
enable_by_default = true
model = "gpt-demo"
temperature = 0.42

[uploads]
max_upload_mb = 123
""",
        encoding="utf-8",
    )

    settings = load_app_settings(settings_path)

    assert settings.use_llm_by_default is True
    assert settings.llm_model == "gpt-demo"
    assert settings.llm_temperature == 0.42
    assert settings.max_upload_mb == 123


def test_load_app_settings_invalid_falls_back(tmp_path: Path, monkeypatch):
    bad_path = tmp_path / "bad.toml"
    bad_path.write_text("not-toml!", encoding="utf-8")
    monkeypatch.setenv("GSP_APP_SETTINGS_FILE", str(bad_path))

    settings = load_app_settings()

    assert settings == AppSettings()
