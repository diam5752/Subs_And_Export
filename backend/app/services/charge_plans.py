"""Charge reservation helpers for processing and intelligence actions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.app.core.config import settings
from backend.app.core.errors import ProviderBudgetExceededError
from backend.app.services import pricing
from backend.app.services.points import make_idempotency_id
from backend.app.services.usage_ledger import ChargePlan, ChargeReservation, UsageLedgerStore


def _current_month_bounds() -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    return int(start.timestamp()), int(now.timestamp())


def assert_external_provider_budget(
    *,
    ledger_store: UsageLedgerStore,
    estimated_cost_usd: float,
) -> None:
    """Fail closed before reserving work that would exceed configured budgets."""
    estimate = max(0.0, float(estimated_cost_usd))
    if estimate == 0.0:
        return
    if estimate > settings.external_provider_per_request_budget_usd:
        raise ProviderBudgetExceededError("Per-request external provider budget exceeded")

    start_ts, end_ts = _current_month_bounds()
    spent = ledger_store.total_cost_usd(start_ts=start_ts, end_ts=end_ts)
    if spent + estimate > settings.external_provider_monthly_budget_usd:
        raise ProviderBudgetExceededError("Monthly external provider budget exceeded")


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
) -> tuple[ChargeReservation, int]:
    min_credits = settings.credits_min_transcribe[tier]
    credits = pricing.credits_for_minutes(
        tier=tier,
        duration_seconds=duration_seconds,
        min_credits=min_credits,
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
) -> tuple[ChargePlan, int]:
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
    assert_external_provider_budget(
        ledger_store=ledger_store,
        estimated_cost_usd=transcription_cost + social_cost,
    )

    transcription_reservation, balance = reserve_transcription_charge(
        ledger_store=ledger_store,
        user_id=user_id,
        job_id=job_id,
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        model=stt_model,
        enforce_budget=False,
    )

    social_reservation: ChargeReservation | None = None
    if use_llm:
        social_reservation, balance = reserve_llm_charge(
            ledger_store=ledger_store,
            user_id=user_id,
            job_id=job_id,
            tier=tier,
            action="social_copy",
            model=llm_model,
            max_prompt_chars=settings.max_llm_input_chars,
            max_completion_tokens=settings.max_llm_output_tokens_social,
            min_credits=settings.credits_min_social_copy[tier],
            enforce_budget=False,
        )

    return ChargePlan(
        transcription=transcription_reservation,
        social_copy=social_reservation,
    ), balance
