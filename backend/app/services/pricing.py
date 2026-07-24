"""Pricing and credits helpers for tiered AI usage."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.services.cost import CostService


@dataclass(frozen=True)
class LlmModels:
    social: str
    fact_check: str
    extraction: str


@dataclass(frozen=True, slots=True)
class VideoCreditQuote:
    key: str
    max_duration_seconds: int
    credits: int


VIDEO_CREDIT_BRACKETS: tuple[VideoCreditQuote, ...] = (
    VideoCreditQuote(key="up_to_3m", max_duration_seconds=180, credits=30),
    VideoCreditQuote(key="up_to_6m", max_duration_seconds=360, credits=60),
    VideoCreditQuote(key="up_to_10m", max_duration_seconds=600, credits=100),
)


def video_credit_quote(duration_seconds: float) -> VideoCreditQuote:
    """Return the immutable, server-authoritative price bracket for one video."""
    duration = float(duration_seconds)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("Video duration must be a positive finite number")

    for quote in VIDEO_CREDIT_BRACKETS:
        if duration <= quote.max_duration_seconds:
            return quote
    raise ValueError("Video duration exceeds the priced 10 minute limit")


def credits_for_video_duration(duration_seconds: float) -> int:
    return video_credit_quote(duration_seconds).credits


def video_credit_catalog() -> list[dict[str, int | str]]:
    """Return JSON-safe copies so callers cannot mutate pricing policy."""
    return [
        {
            "key": quote.key,
            "max_duration_seconds": quote.max_duration_seconds,
            "credits": quote.credits,
        }
        for quote in VIDEO_CREDIT_BRACKETS
    ]


def normalize_tier(tier: str | None) -> str:
    if not tier:
        return settings.default_transcribe_tier
    normalized = tier.strip().lower()
    if normalized not in settings.transcribe_tier_provider:
        raise ValueError("Invalid tier")
    return normalized


def resolve_transcribe_provider(tier: str) -> str:
    normalized = normalize_tier(tier)
    return settings.transcribe_tier_provider[normalized]


def resolve_transcribe_model(tier: str) -> str:
    normalized = normalize_tier(tier)
    return settings.transcribe_tier_model[normalized]


def resolve_requested_transcribe_model(
    *,
    tier: str,
    provider: str | None,
    openai_model: str | None = None,
) -> str:
    normalized_tier = normalize_tier(tier)
    normalized_provider = (provider or resolve_transcribe_provider(normalized_tier)).strip().lower()

    if normalized_provider == "mock":
        return "mock-caption-v1"
    if normalized_provider == "openai":
        selected_model = (openai_model or settings.openai_transcribe_model).strip()
        if selected_model.lower() != "whisper-1":
            raise ValueError("OpenAI caption processing requires the word-timed whisper-1 model")
        return selected_model
    if normalized_provider == "elevenlabs":
        return settings.elevenlabs_transcribe_model

    return settings.transcribe_tier_model[normalized_tier]


def resolve_llm_models(tier: str) -> LlmModels:
    normalized = normalize_tier(tier)
    if normalized == "pro":
        return LlmModels(
            social=settings.social_llm_model,
            fact_check=settings.factcheck_llm_model,
            extraction=settings.extraction_llm_model,
        )
    return LlmModels(
        social=settings.social_llm_model,
        fact_check=settings.factcheck_llm_model,
        extraction=settings.extraction_llm_model,
    )


def estimate_prompt_tokens(text: str) -> int:
    ratio = 4.0
    return max(1, math.ceil(len(text) / ratio))


def estimate_prompt_tokens_from_chars(char_count: int) -> int:
    ratio = 4.0
    return max(1, math.ceil(char_count / ratio))


def credits_for_tokens(
    *,
    tier: str,
    prompt_tokens: int,
    completion_tokens: int,
    min_credits: int,
) -> int:
    normalized = normalize_tier(tier)
    per_1k = settings.credits_per_1k_tokens[normalized]
    total_tokens = max(0, int(prompt_tokens) + int(completion_tokens))
    credits = math.ceil((total_tokens / 1000) * per_1k)
    return max(int(min_credits), int(credits))


def credits_for_minutes(
    *,
    tier: str,
    duration_seconds: float,
    min_credits: int,
) -> int:
    normalized = normalize_tier(tier)
    minutes = max(0.0, float(duration_seconds)) / 60.0
    per_min = settings.credits_per_minute_transcribe[normalized]
    credits = math.ceil(minutes * per_min)
    return max(int(min_credits), int(credits))


def stt_cost_usd(*, tier: str, duration_seconds: float) -> float:
    return stt_provider_cost_usd(tier=tier, duration_seconds=duration_seconds)


def stt_provider_cost_usd(
    *,
    tier: str,
    duration_seconds: float,
    provider: str | None = None,
    model: str | None = None,
) -> float:
    normalized = normalize_tier(tier)
    minutes = max(0.0, float(duration_seconds)) / 60.0
    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model or "").strip().lower()

    if normalized_provider in {"local", "mock"}:
        return 0.0
    if normalized_provider == "openai":
        # whisper-1 is the OpenAI caption-compatible model with word timestamps.
        return minutes * 0.006
    if normalized_provider == "groq":
        price_per_minute = 0.04 / 60 if "turbo" in normalized_model else 0.111 / 60
        return minutes * price_per_minute
    if normalized_provider == "elevenlabs":
        return minutes * (0.22 / 60)

    return minutes * float(settings.stt_price_per_minute.get(normalized, 0.04 / 60))


def llm_cost_estimate_usd(
    *,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    """Estimate a worst-case LLM call cost without requiring a database session."""
    model_pricing = settings.llm_pricing.get(model_name, {})
    input_price = float(model_pricing.get("input", settings.default_llm_input_price))
    output_price = float(model_pricing.get("output", settings.default_llm_output_price))
    return float(
        (max(0, prompt_tokens) / 1_000_000) * input_price
        + (max(0, completion_tokens) / 1_000_000) * output_price
    )


def llm_cost_usd(
    session: Session,
    *,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    pricing_row = CostService.get_model_pricing(session, model_name)
    if pricing_row:
        input_price = pricing_row.input_price_per_1m
        output_price = pricing_row.output_price_per_1m
    else:
        # Fallback from settings
        model_pricing = settings.llm_pricing.get(model_name, {})
        input_price = model_pricing.get("input", settings.default_llm_input_price)
        output_price = model_pricing.get("output", settings.default_llm_output_price)

    input_cost = (prompt_tokens / 1_000_000) * input_price
    output_cost = (completion_tokens / 1_000_000) * output_price
    return float(input_cost + output_cost)


def max_llm_credits_for_limits(
    *,
    tier: str,
    max_prompt_chars: int,
    max_completion_tokens: int,
    min_credits: int,
) -> dict[str, Any]:
    prompt_tokens = estimate_prompt_tokens_from_chars(max_prompt_chars)
    completion_tokens = max(0, int(max_completion_tokens))
    credits = credits_for_tokens(
        tier=normalize_tier(tier),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        min_credits=min_credits,
    )
    return {
        "credits": credits,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
