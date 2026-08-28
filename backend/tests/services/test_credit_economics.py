"""Regression tests for the paid-provider contribution-margin guard."""

from __future__ import annotations

from decimal import Decimal

import pytest

from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.services.billing import credit_packages
from backend.app.services.credit_economics import (
    MINIMUM_CONTRIBUTION_MARGIN,
    PACKAGE_GROSS_EUR_AND_CREDITS,
    assert_provider_economics,
    minimum_net_revenue_per_credit_eur,
)


def test_minimum_net_revenue_uses_the_most_conservative_package() -> None:
    net_per_credit = minimum_net_revenue_per_credit_eur()

    assert net_per_credit == pytest.approx(Decimal("0.005049516129032258"))


def test_economics_catalog_matches_server_owned_checkout_catalog() -> None:
    assert {
        (package.amount_eur_cents, package.credits)
        for package in credit_packages()
    } == {
        (int(gross_eur * 100), credits)
        for gross_eur, credits in PACKAGE_GROSS_EUR_AND_CREDITS
    }


def test_provider_economics_accepts_current_ten_minute_scribe_ceiling() -> None:
    quote = assert_provider_economics(
        credits=100,
        estimated_cost_usd=0.22 / 6,
        safety_multiplier=1.25,
    )

    assert quote.net_revenue_eur > quote.guarded_provider_cost_eur
    assert quote.contribution_margin >= MINIMUM_CONTRIBUTION_MARGIN


def test_thirty_credits_cover_three_minute_transcription_ceiling() -> None:
    scribe_cost_usd = 0.22 * (3 / 60)

    quote = assert_provider_economics(
        credits=30,
        estimated_cost_usd=scribe_cost_usd,
        safety_multiplier=1.25,
    )

    assert quote.credits == 30
    assert quote.net_revenue_eur > quote.guarded_provider_cost_eur
    assert quote.contribution_margin >= MINIMUM_CONTRIBUTION_MARGIN


def test_provider_economics_fails_closed_when_provider_price_destroys_margin() -> None:
    # REGRESSION: hard provider budgets alone must not allow a price drift that
    # turns a paid customer operation into a loss-making dispatch.
    with pytest.raises(
        ProviderBudgetExceededError,
        match="economics guard",
    ):
        assert_provider_economics(
            credits=30,
            estimated_cost_usd=0.20,
            safety_multiplier=1.25,
        )


@pytest.mark.parametrize(
    ("credits", "estimated_cost_usd", "safety_multiplier"),
    [
        (0, 0.01, 1.25),
        (-1, 0.01, 1.25),
        (30, -0.01, 1.25),
        (30, 0.01, 0.99),
    ],
)
def test_provider_economics_rejects_invalid_inputs(
    credits: int,
    estimated_cost_usd: float,
    safety_multiplier: float,
) -> None:
    with pytest.raises(ValueError):
        assert_provider_economics(
            credits=credits,
            estimated_cost_usd=estimated_cost_usd,
            safety_multiplier=safety_multiplier,
        )
