"""Charge reservation helpers for processing and intelligence actions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

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
    use_llm: bool
    credits: int
    transcription_cost_usd: float
    social_cost_usd: float
    require_paid_credits: bool

    @property
    def total_cost_usd(self) -> float:
        return self.transcription_cost_usd + self.social_cost_usd


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


def reserve_llm_charge(
    *,
    ledger_store: UsageLedgerStore,
    user_id: str,
    job_id: str | None,
    tier: str,
    action: str,
    model: str,
    max_prompt_chars: int,
    max_completion_tokens: int,
    min_credits: int,
    enforce_budget: bool = True,
) -> tuple[ChargeReservation, int]:
    reservation_info = pricing.max_llm_credits_for_limits(
        tier=tier,
        max_prompt_chars=max_prompt_chars,
        max_completion_tokens=max_completion_tokens,
        min_credits=min_credits,
    )
    idempotency_key = make_idempotency_id("usage", action, user_id, job_id or "none")
    cost_estimate = pricing.llm_cost_estimate_usd(
        model_name=model,
        prompt_tokens=reservation_info["prompt_tokens"],
        completion_tokens=reservation_info["completion_tokens"],
    )
    if enforce_budget:
        assert_external_provider_budget(
            ledger_store=ledger_store,
            estimated_cost_usd=cost_estimate,
        )
        assert_external_provider_economics(
            credits=reservation_info["credits"],
            estimated_cost_usd=cost_estimate,
        )
    units: dict[str, Any] = {
        "max_prompt_tokens": reservation_info["prompt_tokens"],
        "max_completion_tokens": reservation_info["completion_tokens"],
        "max_total_tokens": reservation_info["total_tokens"],
        "reserved_credits": reservation_info["credits"],
    }
    return ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action=action,
        provider="openai",
        model=model,
        tier=tier,
        credits=reservation_info["credits"],
        min_credits=min_credits,
        cost_estimate_usd=cost_estimate,
        units=units,
        idempotency_key=idempotency_key,
        endpoint="chat/completions",
        allow_terminal_retry=True,
    )


def reserve_included_llm_charge(
    *,
    ledger_store: UsageLedgerStore,
    parent: ChargeReservation,
    user_id: str,
    job_id: str,
    tier: str,
    action: str,
    model: str,
    max_prompt_chars: int,
    max_completion_tokens: int,
) -> tuple[ChargeReservation, int]:
    """Reserve provider money while keeping the visible video price all-inclusive."""
    reservation_info = pricing.max_llm_credits_for_limits(
        tier=tier,
        max_prompt_chars=max_prompt_chars,
        max_completion_tokens=max_completion_tokens,
        min_credits=0,
    )
    cost_estimate = pricing.llm_cost_estimate_usd(
        model_name=model,
        prompt_tokens=reservation_info["prompt_tokens"],
        completion_tokens=reservation_info["completion_tokens"],
    )
    idempotency_key = make_idempotency_id("usage", action, user_id, job_id, "included")
    return ledger_store.reserve(
        user_id=user_id,
        job_id=job_id,
        action=action,
        provider="openai",
        model=model,
        tier=tier,
        credits=0,
        min_credits=0,
        cost_estimate_usd=cost_estimate,
        units={
            "max_prompt_tokens": reservation_info["prompt_tokens"],
            "max_completion_tokens": reservation_info["completion_tokens"],
            "included_in_video_credits": parent.reserved_credits,
        },
        idempotency_key=idempotency_key,
        endpoint="chat/completions",
        covered_by_ledger_id=parent.ledger_id,
    )


def _processing_charge_requirements(
    *,
    tier: str,
    duration_seconds: float,
    use_llm: bool,
    llm_model: str,
    provider: str,
    stt_model: str,
) -> _ProcessingChargeRequirements:
    if settings.mock_external_services:
        provider = "mock"
        stt_model = "mock-caption-v1"
        use_llm = False

    transcription_cost = pricing.stt_provider_cost_usd(
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        model=stt_model,
    )
    social_cost = 0.0
    if use_llm:
        reservation_info = pricing.max_llm_credits_for_limits(
            tier=tier,
            max_prompt_chars=settings.max_llm_input_chars,
            max_completion_tokens=settings.max_llm_output_tokens_social,
            min_credits=settings.credits_min_social_copy[tier],
        )
        social_cost = pricing.llm_cost_estimate_usd(
            model_name=llm_model,
            prompt_tokens=reservation_info["prompt_tokens"],
            completion_tokens=reservation_info["completion_tokens"],
        )

    normalized_provider = provider.strip().lower()
    provider_requires_paid = (
        transcription_cost > 0
        and normalized_provider not in {"local", "mock"}
    )
    return _ProcessingChargeRequirements(
        provider=provider,
        stt_model=stt_model,
        use_llm=use_llm,
        credits=pricing.credits_for_video_duration(duration_seconds),
        transcription_cost_usd=transcription_cost,
        social_cost_usd=social_cost,
        require_paid_credits=(
            provider_requires_paid or (use_llm and social_cost > 0)
        ),
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
    use_llm: bool,
    llm_model: str,
    provider: str,
    stt_model: str,
) -> None:
    """Reject deterministic charge failures before creating a durable job."""
    requirements = _processing_charge_requirements(
        tier=tier,
        duration_seconds=duration_seconds,
        use_llm=use_llm,
        llm_model=llm_model,
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


def reserve_processing_charges(
    *,
    ledger_store: UsageLedgerStore,
    user_id: str,
    job_id: str,
    tier: str,
    duration_seconds: float,
    use_llm: bool,
    llm_model: str,
    provider: str,
    stt_model: str,
    allow_downward_adjustment: bool = False,
) -> tuple[ChargePlan, int]:
    requirements = _processing_charge_requirements(
        tier=tier,
        duration_seconds=duration_seconds,
        use_llm=use_llm,
        llm_model=llm_model,
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
        require_paid_credits=(
            requirements.use_llm and requirements.social_cost_usd > 0
        ),
        allow_downward_adjustment=allow_downward_adjustment,
    )

    social_reservation: ChargeReservation | None = None
    if requirements.use_llm:
        try:
            social_reservation, balance = reserve_included_llm_charge(
                ledger_store=ledger_store,
                parent=transcription_reservation,
                user_id=user_id,
                job_id=job_id,
                tier=tier,
                action="social_copy",
                model=llm_model,
                max_prompt_chars=settings.max_llm_input_chars,
                max_completion_tokens=settings.max_llm_output_tokens_social,
            )
        except Exception as exc:
            ledger_store.fail(
                transcription_reservation,
                status="failed",
                error=f"Bundled provider reservation failed: {type(exc).__name__}",
            )
            raise

    return ChargePlan(
        transcription=transcription_reservation,
        social_copy=social_reservation,
    ), balance
