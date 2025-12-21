"""Tests for the new unified pydantic-settings configuration."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from backend.app.core.config import AppEnv, Settings


def test_settings_defaults(monkeypatch) -> None:
    # Clear env to ensure we get pure defaults
    monkeypatch.delenv("GSP_APP_ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("GSP_APP_SETTINGS_FILE", "/non/existent/path")
    
    settings = Settings(_env_file=None) # Disable .env loading for this test
    assert settings.app_env == AppEnv.PRODUCTION
    assert not settings.is_dev


def test_settings_toml_override(tmp_path: Path, monkeypatch) -> None:
    toml_path = tmp_path / "app_settings.toml"
    toml_path.write_text(
        """
[ai]
enable_by_default = true
model = "gpt-toml-test"
temperature = 0.42

[uploads]
max_upload_mb = 123
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("GSP_APP_SETTINGS_FILE", str(toml_path))
    
    settings = Settings(_env_file=None)
    
    assert settings.use_llm_by_default is True
    assert settings.llm_model == "gpt-toml-test"
    assert settings.llm_temperature == 0.42
    assert settings.max_upload_mb == 123


def test_settings_pricing_integration() -> None:
    settings = Settings()
    assert "gpt-5.1-mini" in settings.llm_pricing
    assert settings.stt_price_per_minute["standard"] == 0.003
