"""Tests for the new unified pydantic-settings configuration."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

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
    assert settings.consumer_policy_approved is False
    assert settings.durable_confirmation_channel_ready is False
    assert settings.adjustment_workflow_ready is False
    assert settings.paid_credit_checkout_enabled is False
    assert settings.stripe_automatic_tax_enabled is False
    assert settings.stripe_api_base == "https://api.stripe.com"
    assert settings.google_oauth_certs_url == "https://www.googleapis.com/oauth2/v1/certs"
    assert settings.external_provider_price_safety_multiplier == 1.25
    assert settings.watermark_path.name == "gsubs-logo.png"
    assert settings.watermark_path.exists()


def test_runtime_startup_rejects_environment_activation_of_draft_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend import main as main_module

    stage_validation = Mock()
    environment_validation = Mock()
    code_approval = Mock(
        side_effect=RuntimeError("consumer registry is unapproved"),
    )
    monkeypatch.setattr(
        main_module,
        "settings",
        SimpleNamespace(
            assert_stripe_stage_configuration=stage_validation,
            assert_paid_credits_configuration=environment_validation,
            paid_credit_checkout_enabled=True,
        ),
    )
    monkeypatch.setattr(
        main_module,
        "assert_consumer_contract_registry_approved",
        code_approval,
    )

    with pytest.raises(RuntimeError, match="registry is unapproved"):
        main_module.assert_runtime_billing_configuration()

    stage_validation.assert_called_once_with()
    environment_validation.assert_called_once_with()
    code_approval.assert_called_once_with()


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
    monkeypatch.setenv(
        "GSP_GOOGLE_OAUTH_CERTS_URL",
        "http://edge:8081/oauth2/v1/certs",
    )
    monkeypatch.setenv(
        "GSP_STRIPE_API_BASE",
        "http://edge:8081/stripe",
    )

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
    assert settings.google_oauth_certs_url == "http://edge:8081/oauth2/v1/certs"
    assert settings.stripe_api_base == "http://edge:8081/stripe"


def test_settings_rejects_nonpositive_upload_limit(monkeypatch) -> None:
    monkeypatch.setenv("GSP_MAX_UPLOAD_MB", "0")

    with pytest.raises(ValueError, match="greater than 0"):
        Settings(_env_file=None)


def test_settings_rejects_unapproved_google_oauth_certs_url(monkeypatch) -> None:
    monkeypatch.setenv(
        "GSP_GOOGLE_OAUTH_CERTS_URL",
        "https://attacker.example/google-certs",
    )

    with pytest.raises(ValueError, match="approved Google OAuth certificate endpoint"):
        Settings(_env_file=None)


def test_settings_rejects_unapproved_stripe_api_base(monkeypatch) -> None:
    monkeypatch.setenv(
        "GSP_STRIPE_API_BASE",
        "https://attacker.example/stripe",
    )

    with pytest.raises(ValueError, match="approved Stripe API endpoint"):
        Settings(_env_file=None)


def test_settings_normalizers_handle_empty_and_malformed_inputs() -> None:
    assert Settings.normalize_env(None) == AppEnv.PRODUCTION
    assert Settings.parse_list("") == []
    assert Settings.parse_list("[not-json]") == ["[not-json]"]
    assert Settings.parse_list(("one.example", " ", "two.example")) == [
        "one.example",
        "two.example",
    ]
    assert Settings.parse_list(42) == []


def test_settings_pricing_integration() -> None:
    settings = Settings()
    assert "gpt-5-mini" in settings.llm_pricing
    assert settings.stt_price_per_minute["standard"] == pytest.approx(0.04 / 60)


def test_paid_credits_configuration_fails_closed_without_restricted_key(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_CONSUMER_POLICY_APPROVED", "true")
    monkeypatch.setenv("GSP_DURABLE_CONFIRMATION_CHANNEL_READY", "true")
    monkeypatch.setenv("GSP_ADJUSTMENT_WORKFLOW_READY", "true")
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="restricted key"):
        settings.assert_paid_credits_configuration()


def test_paid_credits_configuration_is_a_noop_while_sales_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "false")
    settings = Settings(_env_file=None)

    settings.assert_paid_credits_configuration()


def test_stripe_stage_configuration_accepts_absent_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in (
        "GSP_STRIPE_RESTRICTED_KEY",
        "GSP_STRIPE_WEBHOOK_SECRET",
        "GSP_STRIPE_PRICE_STARTER",
        "GSP_STRIPE_PRICE_CORE",
        "GSP_STRIPE_PRICE_PRO",
    ):
        monkeypatch.delenv(variable, raising=False)
    settings = Settings(_env_file=None)

    assert settings.assert_stripe_stage_configuration() is False


def test_stripe_stage_configuration_accepts_complete_live_bundle_while_sales_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GSP_APP_ENV", "production")
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "false")
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", "rk_live_placeholder")
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("GSP_STRIPE_API_BASE", "http://edge:8081/stripe")
    monkeypatch.setenv(
        "GSP_STRIPE_SUCCESS_URL",
        "https://gsubs.gr/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
    )
    monkeypatch.setenv(
        "GSP_STRIPE_CANCEL_URL",
        "https://gsubs.gr/?checkout=cancelled",
    )
    settings = Settings(_env_file=None)

    assert settings.assert_stripe_stage_configuration() is True
    assert settings.paid_credit_checkout_enabled is False


@pytest.mark.parametrize(
    "missing_env",
    (
        "GSP_STRIPE_WEBHOOK_SECRET",
        "GSP_STRIPE_PRICE_STARTER",
        "GSP_STRIPE_PRICE_CORE",
        "GSP_STRIPE_PRICE_PRO",
    ),
)
def test_stripe_stage_configuration_rejects_partial_bundle(
    monkeypatch: pytest.MonkeyPatch,
    missing_env: str,
) -> None:
    monkeypatch.setenv("GSP_APP_ENV", "production")
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", "rk_live_placeholder")
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.delenv(missing_env)
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="complete or entirely absent"):
        settings.assert_stripe_stage_configuration()


def test_paid_credits_configuration_accepts_reviewed_test_mode(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GSP_APP_ENV", "dev")
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_CONSUMER_POLICY_APPROVED", "true")
    monkeypatch.setenv("GSP_DURABLE_CONFIRMATION_CHANNEL_READY", "true")
    monkeypatch.setenv("GSP_ADJUSTMENT_WORKFLOW_READY", "true")
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", "rk_test_placeholder")
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    settings = Settings(_env_file=None)

    settings.assert_paid_credits_configuration()


def test_paid_credits_configuration_accepts_live_key_outside_development(
    monkeypatch,
) -> None:
    monkeypatch.setenv("GSP_APP_ENV", "production")
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_CONSUMER_POLICY_APPROVED", "true")
    monkeypatch.setenv("GSP_DURABLE_CONFIRMATION_CHANNEL_READY", "true")
    monkeypatch.setenv("GSP_ADJUSTMENT_WORKFLOW_READY", "true")
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", "rk_live_placeholder")
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv(
        "GSP_STRIPE_SUCCESS_URL",
        "https://gsubs.gr/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
    )
    monkeypatch.setenv(
        "GSP_STRIPE_CANCEL_URL",
        "https://gsubs.gr/?checkout=cancelled",
    )
    settings = Settings(_env_file=None)

    settings.assert_paid_credits_configuration()


def _fully_gated_paid_credit_environment(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_env: str = "dev",
) -> None:
    monkeypatch.setenv("GSP_APP_ENV", app_env)
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_CONSUMER_POLICY_APPROVED", "true")
    monkeypatch.setenv("GSP_DURABLE_CONFIRMATION_CHANNEL_READY", "true")
    monkeypatch.setenv("GSP_ADJUSTMENT_WORKFLOW_READY", "true")
    monkeypatch.setenv(
        "GSP_STRIPE_RESTRICTED_KEY",
        "rk_test_placeholder" if app_env == "dev" else "rk_live_placeholder",
    )
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    if app_env != "dev":
        monkeypatch.setenv(
            "GSP_STRIPE_SUCCESS_URL",
            "https://gsubs.gr/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
        )
        monkeypatch.setenv(
            "GSP_STRIPE_CANCEL_URL",
            "https://gsubs.gr/?checkout=cancelled",
        )


@pytest.mark.parametrize(
    ("app_env", "restricted_key", "expected_prefix"),
    [
        ("production", "rk_test_placeholder", "rk_live_"),
        ("dev", "rk_live_placeholder", "rk_test_"),
    ],
)
def test_paid_credits_configuration_rejects_restricted_key_mode_mismatch(
    monkeypatch,
    app_env: str,
    restricted_key: str,
    expected_prefix: str,
) -> None:
    monkeypatch.setenv("GSP_APP_ENV", app_env)
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_CONSUMER_POLICY_APPROVED", "true")
    monkeypatch.setenv("GSP_DURABLE_CONFIRMATION_CHANNEL_READY", "true")
    monkeypatch.setenv("GSP_ADJUSTMENT_WORKFLOW_READY", "true")
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", restricted_key)
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", "whsec_placeholder")
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match=expected_prefix):
        settings.assert_paid_credits_configuration()


def test_stripe_automatic_tax_remains_owner_gated(monkeypatch) -> None:
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_CONSUMER_POLICY_APPROVED", "true")
    monkeypatch.setenv("GSP_DURABLE_CONFIRMATION_CHANNEL_READY", "true")
    monkeypatch.setenv("GSP_ADJUSTMENT_WORKFLOW_READY", "true")
    monkeypatch.setenv("GSP_STRIPE_AUTOMATIC_TAX_ENABLED", "true")
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="owner-gated"):
        settings.assert_paid_credits_configuration()


@pytest.mark.parametrize(
    ("missing_env", "message"),
    [
        ("GSP_CONSUMER_POLICY_APPROVED", "consumer policy approval"),
        (
            "GSP_DURABLE_CONFIRMATION_CHANNEL_READY",
            "durable contract-confirmation channel",
        ),
        ("GSP_ADJUSTMENT_WORKFLOW_READY", "accountant-approved adjustment workflow"),
    ],
)
def test_paid_credits_configuration_requires_each_independent_launch_gate(
    monkeypatch,
    missing_env: str,
    message: str,
) -> None:
    monkeypatch.setenv("GSP_PAID_CREDITS_ENABLED", "true")
    monkeypatch.setenv("GSP_CONSUMER_POLICY_APPROVED", "true")
    monkeypatch.setenv("GSP_DURABLE_CONFIRMATION_CHANNEL_READY", "true")
    monkeypatch.setenv("GSP_ADJUSTMENT_WORKFLOW_READY", "true")
    monkeypatch.delenv(missing_env)
    settings = Settings(_env_file=None)

    assert settings.paid_credit_checkout_enabled is False
    with pytest.raises(RuntimeError, match=message):
        settings.assert_paid_credits_configuration()


def test_stripe_gateway_configuration_rejects_missing_webhook_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fully_gated_paid_credit_environment(monkeypatch)
    monkeypatch.delenv("GSP_STRIPE_WEBHOOK_SECRET")
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="webhook signing secret"):
        settings.assert_stripe_gateway_configuration()


@pytest.mark.parametrize(
    ("invalid_env", "invalid_value", "message"),
    [
        ("GSP_STRIPE_PRICE_STARTER", "", "three Stripe credit Price IDs"),
        (
            "GSP_STRIPE_SUCCESS_URL",
            "http://localhost:3000/?checkout=success",
            r"\{CHECKOUT_SESSION_ID\}",
        ),
    ],
)
def test_paid_credits_configuration_rejects_incomplete_checkout_catalog(
    monkeypatch: pytest.MonkeyPatch,
    invalid_env: str,
    invalid_value: str,
    message: str,
) -> None:
    _fully_gated_paid_credit_environment(monkeypatch)
    monkeypatch.setenv(invalid_env, invalid_value)
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match=message):
        settings.assert_paid_credits_configuration()


@pytest.mark.parametrize(
    ("insecure_env", "insecure_url"),
    [
        (
            "GSP_STRIPE_SUCCESS_URL",
            "http://gsubs.gr/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
        ),
        ("GSP_STRIPE_CANCEL_URL", "http://gsubs.gr/?checkout=cancelled"),
    ],
)
def test_paid_credits_configuration_requires_https_return_urls_in_production(
    monkeypatch: pytest.MonkeyPatch,
    insecure_env: str,
    insecure_url: str,
) -> None:
    _fully_gated_paid_credit_environment(monkeypatch, app_env="production")
    monkeypatch.setenv(insecure_env, insecure_url)
    settings = Settings(_env_file=None)

    with pytest.raises(RuntimeError, match="return URLs must use HTTPS"):
        settings.assert_paid_credits_configuration()
