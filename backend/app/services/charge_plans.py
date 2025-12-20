"""Charge reservation helpers for processing and intelligence actions."""

from __future__ import annotations

from typing import Any

from backend.app.core import config
from backend.app.services import pricing
from backend.app.services.points import make_idempotency_id
from backend.app.services.usage_ledger import ChargePlan, ChargeReservation, UsageLedgerStore


def reserve_transcription_charge(
    *,
    ledger_store: UsageLedgerStore,
    user_id: str,
    job_id: str,
    tier: str,
    duration_seconds: float,
    provider: str,
    model: str,
) -> tuple[ChargeReservation, int]:
    min_credits = config.CREDITS_MIN_TRANSCRIBE[tier]
    credits = pricing.credits_for_minutes(
        tier=tier,
        duration_seconds=duration_seconds,
        min_credits=min_credits,
    )
    cost_estimate = pricing.stt_cost_usd(tier=tier, duration_seconds=duration_seconds)
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
) -> tuple[ChargeReservation, int]:
    reservation_info = pricing.max_llm_credits_for_limits(
        tier=tier,
        max_prompt_chars=max_prompt_chars,
        max_completion_tokens=max_completion_tokens,
        min_credits=min_credits,
    )
    idempotency_key = make_idempotency_id("usage", action, user_id, job_id or "none")
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
        cost_estimate_usd=0.0,
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
    transcription_reservation, balance = reserve_transcription_charge(
        ledger_store=ledger_store,
        user_id=user_id,
        job_id=job_id,
        tier=tier,
        duration_seconds=duration_seconds,
        provider=provider,
        model=stt_model,
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
            max_prompt_chars=config.MAX_LLM_INPUT_CHARS,
            max_completion_tokens=config.MAX_LLM_OUTPUT_TOKENS_SOCIAL,
            min_credits=config.CREDITS_MIN_SOCIAL_COPY[tier],
        )

    return ChargePlan(
        transcription=transcription_reservation,
        social_copy=social_reservation,
    ), balance
