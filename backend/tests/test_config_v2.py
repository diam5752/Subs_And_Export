"""Tests for the new unified pydantic-settings configuration."""

from __future__ import annotations

import pytest

from backend.app.core.config import AppEnv, Settings


def test_settings_defaults(monkeypatch) -> None:
    # Clear env to ensure we get pure defaults
    monkeypatch.delenv("GSP_APP_ENV", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("GSP_RETENTION_CLEANUP_ENABLED", raising=False)
    settings = Settings(_env_file=None)  # Disable .env loading for this test
    assert settings.app_env == AppEnv.PRODUCTION
    assert not settings.is_dev
    # REGRESSION: production previously advertised 95 MB while local defaults
    # silently allowed 1 GiB.
    assert settings.max_upload_mb == 500
    assert settings.max_video_duration_seconds == 600
    assert settings.workspace_retention_hours == 24
    assert settings.stale_job_retention_hours == 6
    assert settings.orphan_retention_hours == 1
    assert settings.cleanup_interval_minutes == 15
    assert settings.storage_min_free_mb == 2048
    assert settings.retention_cleanup_enabled is True
    assert settings.paid_credits_enabled is False
    assert settings.stripe_automatic_tax_enabled is False
    assert settings.external_provider_price_safety_multiplier == 1.25
    assert settings.watermark_path.name == "gsubs-logo.png"
    assert settings.watermark_path.exists()


def test_settings_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("GSP_MOCK_EXTERNAL_SERVICES", "false")
    monkeypatch.setenv("GSP_USE_LLM_BY_DEFAULT", "true")
    monkeypatch.setenv("GSP_LLM_MODEL", "gpt-env-test")
    monkeypatch.setenv("GSP_LLM_TEMPERATURE", "0.42")
    monkeypatch.setenv("GSP_MAX_UPLOAD_MB", "123")
    monkeypatch.setenv("GSP_MAX_VIDEO_DURATION_SECONDS", "480")
    monkeypatch.setenv("GSP_WORKSPACE_RETENTION_HOURS", "36")
    monkeypatch.setenv("GSP_STALE_JOB_RETENTION_HOURS", "8")
    monkeypatch.setenv("GSP_ORPHAN_RETENTION_HOURS", "2")
    monkeypatch.setenv("GSP_CLEANUP_INTERVAL_MINUTES", "20")
    monkeypatch.setenv("GSP_STORAGE_MIN_FREE_MB", "3072")
    monkeypatch.setenv("GSP_RETENTION_CLEANUP_ENABLED", "false")
    monkeypatch.setenv("GSP_ALLOWED_ORIGINS", '["https://one.example", "https://two.example"]')
    monkeypatch.setenv("GSP_TRUSTED_HOSTS", "localhost, 127.0.0.1")

    settings = Settings(_env_file=None)

    assert settings.mock_external_services is False
    assert settings.use_llm_by_default is True
    assert settings.llm_model == "gpt-env-test"
    assert settings.llm_temperature == 0.42
    assert settings.max_upload_mb == 123
    assert settings.max_video_duration_seconds == 480
    assert settings.workspace_retention_hours == 36
    assert settings.stale_job_retention_hours == 8
    assert settings.orphan_retention_hours == 2
    assert settings.cleanup_interval_minutes == 20
    assert settings.storage_min_free_mb == 3072
    assert settings.retention_cleanup_enabled is False
    assert settings.allowed_origins == ["https://one.example", "https://two.example"]
    assert settings.trusted_hosts == ["localhost", "127.0.0.1"]


def test_settings_rejects_nonpositive_upload_limit(monkeypatch) -> None:
    monkeypatch.setenv("GSP_MAX_UPLOAD_MB", "0")

    with pytest.raises(ValueError, match="greater than 0"):
        Settings(_env_file=None)


def test_settings_pricing_integration() -> None:
    settings = Settings()
    assert "gpt-5-mini" in settings.llm_pricing
    assert settings.stt_price_per_minute["standard"] == pytest.approx(0.04 / 60)


def test_paid_credits_configuration_fails_closed_without_restricted_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="restricted key"):
        settings.assert_paid_credits_configuration()


def test_paid_credits_configuration_accepts_reviewed_test_mode(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GSP_APP_ENV", "dev")
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", "rk_test_placeholder")
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    settings = Settings(_env_file=None)

    settings.assert_paid_credits_configuration()


def test_stripe_automatic_tax_remains_owner_gated(monkeypatch) -> None:
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_STRIPE_AUTOMATIC_TAX_ENABLED", "true")
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="owner-gated"):
        settings.assert_paid_credits_configuration()
