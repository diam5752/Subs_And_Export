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


def resolve_tier_from_model(value: str | None) -> str:
    if not value:
        return settings.default_transcribe_tier
    normalized = value.strip().lower()
    if normalized in settings.transcribe_tier_provider:
        return normalized
    if "turbo" in normalized or normalized == "enhanced":
        return "standard"
    if normalized in {"ultimate", "whisper-1"}:
        return "pro"
    if "large" in normalized:
        return "pro"
    if normalized in {"medium", "small", "base"}:
        return "standard"
    if "openai" in normalized:
        return "pro"
    return settings.default_transcribe_tier


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
    normalized = normalize_tier(tier)
    minutes = max(0.0, float(duration_seconds)) / 60.0
    return minutes * float(settings.stt_price_per_minute.get(normalized, 0.003))


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
