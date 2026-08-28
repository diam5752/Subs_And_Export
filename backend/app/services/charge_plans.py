"""Charge reservation helpers for video transcription."""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.app.core.config import settings
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.services import pricing
from backend.app.services.credit_economics import assert_provider_economics
from backend.app.services.points import make_idempotency_id
from backend.app.services.usage_ledger import ChargePlan, ChargeReservation, UsageLedgerStore


@dataclass(frozen=True, slots=True)
class _ProcessingChargeRequirements:
    provider: str
    stt_model: str
    credits: int
    transcription_cost_usd: float
    require_paid_credits: bool

    @property
    def total_cost_usd(self) -> float:
        return self.transcription_cost_usd


def assert_external_provider_budget(
    *,
    ledger_store: UsageLedgerStore,
    estimated_cost_usd: float,
) -> None:
    """Fail closed before reserving work that would exceed configured budgets."""
    estimate = float(estimated_cost_usd)
    if not math.isfinite(estimate) or estimate < 0:
        raise ProviderBudgetExceededError("Invalid external provider cost estimate")
    if estimate == 0.0:
        return
    if estimate > settings.external_provider_per_request_budget_usd:
        raise ProviderBudgetExceededError("Per-request external provider budget exceeded")
    if (
        settings.external_provider_daily_budget_usd <= 0
        or settings.external_provider_monthly_budget_usd <= 0
    ):
        raise ProviderBudgetExceededError("External provider budgets are closed")
    guarded_estimate = estimate * settings.external_provider_price_safety_multiplier
    if not math.isfinite(guarded_estimate) or guarded_estimate <= 0:
        raise ProviderBudgetExceededError("Invalid guarded provider cost estimate")
    ledger_store.provider_budget_store.assert_can_reserve(
        estimated_usd=guarded_estimate,
        daily_limit_usd=settings.external_provider_daily_budget_usd,
        monthly_limit_usd=settings.external_provider_monthly_budget_usd,
    )


def assert_external_provider_economics(
    *,
    credits: int,
    estimated_cost_usd: float,
) -> None:
    """Fail closed before wallet or provider reservation if margin is unsafe."""
    estimate = float(estimated_cost_usd)
    if not math.isfinite(estimate) or estimate < 0:
        raise ProviderBudgetExceededError("Invalid external provider cost estimate")
    if estimate == 0.0:
        return
    assert_provider_economics(
        credits=credits,
        estimated_cost_usd=estimate,
        safety_multiplier=settings.external_provider_price_safety_multiplier,
    )


def reserve_transcription_charge(
    *,
    ledger_store: UsageLedgerStore,
    user_id: str,
    job_id: str,
    tier: str,
    duration_seconds: float,
    provider: str,
    model: str,
    enforce_budget: bool = True,
    require_paid_credits: bool | None = None,
    allow_downward_adjustment: bool = False,
) -> tuple[ChargeReservation, int]:
    credits = pricing.credits_for_video_duration(duration_seconds)
    min_credits = (
        pricing.VIDEO_CREDIT_BRACKETS[0].credits
        if allow_downward_adjustment
        else credits
    )
    cost_estimate = pricing.stt_provider_cost_usd(
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        model=model,
    )
    if enforce_budget:
        assert_external_provider_budget(
            ledger_store=ledger_store,
            estimated_cost_usd=cost_estimate,
        )
        assert_external_provider_economics(
            credits=credits,
            estimated_cost_usd=cost_estimate,
        )
    idempotency_key = make_idempotency_id("usage", "transcription", user_id, job_id)
    units = {
        "audio_seconds": duration_seconds,
        "model": model,
        "provider": provider,
        "reserved_credits": credits,
    }
    return ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action="transcription",
        provider=provider,
        model=model,
        tier=tier,
        credits=credits,
        min_credits=min_credits,
        cost_estimate_usd=cost_estimate,
        units=units,
        idempotency_key=idempotency_key,
        endpoint="audio/transcriptions",
        require_paid_credits=require_paid_credits,
    )


def _processing_charge_requirements(
    *,
    tier: str,
    duration_seconds: float,
    provider: str,
    stt_model: str,
) -> _ProcessingChargeRequirements:
    if settings.mock_external_services:
        provider = "mock"
        stt_model = "mock-caption-v1"

    transcription_cost = pricing.stt_provider_cost_usd(
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        model=stt_model,
    )
    normalized_provider = provider.strip().lower()
    provider_requires_paid = (
        transcription_cost > 0
        and normalized_provider not in {"local", "mock"}
    )
    return _ProcessingChargeRequirements(
        provider=provider,
        stt_model=stt_model,
        credits=pricing.credits_for_video_duration(duration_seconds),
        transcription_cost_usd=transcription_cost,
        require_paid_credits=provider_requires_paid,
    )


def _assert_processing_requirements(
    *,
    ledger_store: UsageLedgerStore,
    requirements: _ProcessingChargeRequirements,
) -> None:
    assert_external_provider_budget(
        ledger_store=ledger_store,
        estimated_cost_usd=requirements.total_cost_usd,
    )
    assert_external_provider_economics(
        credits=requirements.credits,
        estimated_cost_usd=requirements.total_cost_usd,
    )


def preflight_processing_charges(
    *,
    ledger_store: UsageLedgerStore,
    user_id: str,
    tier: str,
    duration_seconds: float,
    provider: str,
    stt_model: str,
) -> None:
    """Reject deterministic charge failures before creating a durable job."""
    requirements = _processing_charge_requirements(
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        stt_model=stt_model,
    )
    _assert_processing_requirements(
        ledger_store=ledger_store,
        requirements=requirements,
    )
    ledger_store.points_store.assert_can_spend(
        user_id,
        requirements.credits,
        require_paid=requirements.require_paid_credits,
    )


def preflight_processing_provider_budget(
    *,
    ledger_store: UsageLedgerStore,
    tier: str,
    duration_seconds: float,
    provider: str,
    stt_model: str,
) -> None:
    """Reject a known budget failure without inspecting or reserving credits."""
    requirements = _processing_charge_requirements(
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        stt_model=stt_model,
    )
    assert_external_provider_budget(
        ledger_store=ledger_store,
        estimated_cost_usd=requirements.total_cost_usd,
    )


def reserve_processing_charges(
    *,
    ledger_store: UsageLedgerStore,
    user_id: str,
    job_id: str,
    tier: str,
    duration_seconds: float,
    provider: str,
    stt_model: str,
    allow_downward_adjustment: bool = False,
) -> tuple[ChargePlan, int]:
    requirements = _processing_charge_requirements(
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        stt_model=stt_model,
    )
    _assert_processing_requirements(
        ledger_store=ledger_store,
        requirements=requirements,
    )

    transcription_reservation, balance = reserve_transcription_charge(
        ledger_store=ledger_store,
        user_id=user_id,
        job_id=job_id,
        tier=tier,
        duration_seconds=duration_seconds,
        provider=requirements.provider,
        model=requirements.stt_model,
        enforce_budget=False,
        require_paid_credits=requirements.require_paid_credits,
        allow_downward_adjustment=allow_downward_adjustment,
    )
    return ChargePlan(transcription=transcription_reservation), balance
