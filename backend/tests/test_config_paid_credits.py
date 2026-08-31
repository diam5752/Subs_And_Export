"""Paid-credit and Stripe configuration contracts."""

from __future__ import annotations

import pytest

from backend.app.core.config import Settings

TEST_RESTRICTED_KEY = "_".join(("rk", "test", "placeholder"))
LIVE_RESTRICTED_KEY = "_".join(("rk", "live", "placeholder"))
WEBHOOK_SECRET = "_".join(("whsec", "placeholder"))


def test_stripe_stage_configuration_rejects_automatic_tax(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", TEST_RESTRICTED_KEY)
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("GSP_STRIPE_AUTOMATIC_TAX_ENABLED", "true")

    with pytest.raises(RuntimeError, match="Automatic Tax"):
        Settings(_env_file=None).assert_stripe_stage_configuration()


def test_stripe_stage_configuration_rejects_partial_bundle_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GSP_STRIPE_RESTRICTED_KEY", raising=False)
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)

    with pytest.raises(RuntimeError, match="restricted key is required"):
        Settings(_env_file=None).assert_stripe_stage_configuration()


def test_settings_pricing_integration() -> None:
    settings = Settings()
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
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", LIVE_RESTRICTED_KEY)
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("GSP_STRIPE_PRICE_STARTER", "price_starter")
    monkeypatch.setenv("GSP_STRIPE_PRICE_CORE", "price_core")
    monkeypatch.setenv("GSP_STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("GSP_STRIPE_API_BASE", "http://app-edge:8081/stripe")
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
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", LIVE_RESTRICTED_KEY)
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
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
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", TEST_RESTRICTED_KEY)
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
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
    monkeypatch.setenv("GSP_STRIPE_RESTRICTED_KEY", LIVE_RESTRICTED_KEY)
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
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
        TEST_RESTRICTED_KEY if app_env == "dev" else LIVE_RESTRICTED_KEY,
    )
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
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
        ("production", TEST_RESTRICTED_KEY, "rk_live_"),
        ("dev", LIVE_RESTRICTED_KEY, "rk_test_"),
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
    monkeypatch.setenv("GSP_STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
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
        ("GSP_ADJUSTMENT_WORKFLOW_READY", "approved manual adjustment workflow"),
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
