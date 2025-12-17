from __future__ import annotations

from backend.app.core.env import AppEnv, get_app_env, normalize_app_env


def test_normalize_app_env_defaults_to_production() -> None:
    assert normalize_app_env(None) == AppEnv.PRODUCTION


def test_normalize_app_env_maps_common_values() -> None:
    assert normalize_app_env("dev") == AppEnv.DEV
    assert normalize_app_env("development") == AppEnv.DEV
    assert normalize_app_env("local") == AppEnv.DEV
    assert normalize_app_env("localhost") == AppEnv.DEV
    assert normalize_app_env("prod") == AppEnv.PRODUCTION
    assert normalize_app_env("production") == AppEnv.PRODUCTION


def test_normalize_app_env_treats_unknown_as_production() -> None:
    assert normalize_app_env("staging") == AppEnv.PRODUCTION


def test_get_app_env_prefers_app_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ENV", "dev")
    assert get_app_env() == AppEnv.PRODUCTION


def test_get_app_env_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("ENV", "development")
    assert get_app_env() == AppEnv.DEV
