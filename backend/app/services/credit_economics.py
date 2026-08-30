"""Runtime contribution-margin guard for paid external-provider work."""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, localcontext

from backend.app.core.errors import ProviderBudgetExceededError

VAT_RATE = Decimal("0.24")
# Checkout is restricted by billing country, not by card-issuing country. Use
# Stripe's international-card rate plus the possible currency-conversion
# uplift so the shared credit wallet remains safe regardless of purchase mix.
STRIPE_PERCENT_FEE = Decimal("0.0515")
STRIPE_FIXED_FEE_EUR = Decimal("0.25")
USD_TO_EUR_SAFETY_RATE = Decimal("1")
PROVIDER_COST_COVERAGE_MULTIPLIER = Decimal("3")
MINIMUM_CONTRIBUTION_MARGIN = Decimal("1") - (Decimal("1") / PROVIDER_COST_COVERAGE_MULTIPLIER)

# The same immutable packages exposed by the billing catalog. Economics use
# the lowest net value per credit across every package, never the selected
# package, so later purchase-mix changes cannot weaken the dispatch guard.
PACKAGE_GROSS_EUR_AND_CREDITS: tuple[tuple[Decimal, int], ...] = (
    (Decimal("1.00"), 100),
    (Decimal("3.00"), 350),
    (Decimal("10.00"), 1200),
)


@dataclass(frozen=True, slots=True)
class ProviderEconomicsQuote:
    """Auditable values used by the pre-dispatch economics decision."""

    credits: int
    net_revenue_eur: Decimal
    guarded_provider_cost_eur: Decimal
    contribution_margin: Decimal


def minimum_net_revenue_per_credit_eur() -> Decimal:
    """Return the stress-case net package value after VAT and Stripe."""
    with localcontext() as context:
        context.prec = 28
        values = []
        for gross_eur, credits in PACKAGE_GROSS_EUR_AND_CREDITS:
            net_of_vat = gross_eur / (Decimal("1") + VAT_RATE)
            stripe_fee = (gross_eur * STRIPE_PERCENT_FEE) + STRIPE_FIXED_FEE_EUR
            values.append((net_of_vat - stripe_fee) / Decimal(credits))
        return min(values)


def assert_provider_economics(
    *,
    credits: int,
    estimated_cost_usd: float,
    safety_multiplier: float,
) -> ProviderEconomicsQuote:
    """Fail closed unless net credit revenue covers guarded provider cost 3x."""
    if credits <= 0:
        raise ValueError("credits must be positive for provider economics")
    if not math.isfinite(estimated_cost_usd) or estimated_cost_usd < 0:
        raise ValueError("estimated provider cost must be finite and non-negative")
    if not math.isfinite(safety_multiplier) or safety_multiplier < 1:
        raise ValueError("provider safety multiplier must be finite and at least one")

    with localcontext() as context:
        context.prec = 28
        net_revenue_eur = minimum_net_revenue_per_credit_eur() * Decimal(credits)
        guarded_provider_cost_eur = (
            Decimal(str(estimated_cost_usd)) * Decimal(str(safety_multiplier)) * USD_TO_EUR_SAFETY_RATE
        )
        required_revenue = guarded_provider_cost_eur * PROVIDER_COST_COVERAGE_MULTIPLIER
        if net_revenue_eur < required_revenue:
            raise ProviderBudgetExceededError(
                "External provider economics guard rejected request",
            )
        contribution_margin = (
            Decimal("1")
            if guarded_provider_cost_eur == 0
            else (net_revenue_eur - guarded_provider_cost_eur) / net_revenue_eur
        )
        return ProviderEconomicsQuote(
            credits=credits,
            net_revenue_eur=net_revenue_eur,
            guarded_provider_cost_eur=guarded_provider_cost_eur,
            contribution_margin=contribution_margin,
        )
