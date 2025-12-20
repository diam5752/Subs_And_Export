"""Pricing and credits helpers for tiered AI usage."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core import config
from backend.app.services.cost import CostService


@dataclass(frozen=True)
class LlmModels:
    social: str
    fact_check: str
    extraction: str


def normalize_tier(tier: str | None) -> str:
    if not tier:
        return config.DEFAULT_TRANSCRIBE_TIER
    normalized = tier.strip().lower()
    if normalized not in config.TRANSCRIBE_TIERS:
        raise ValueError("Invalid tier")
    return normalized


def resolve_transcribe_provider(tier: str) -> str:
    normalized = normalize_tier(tier)
    return config.TRANSCRIBE_TIER_PROVIDER[normalized]


def resolve_transcribe_model(tier: str) -> str:
    normalized = normalize_tier(tier)
    return config.TRANSCRIBE_TIER_MODEL[normalized]


def resolve_llm_models(tier: str) -> LlmModels:
    normalized = normalize_tier(tier)
    if normalized == "pro":
        return LlmModels(
            social=config.SOCIAL_LLM_MODEL_PRO,
            fact_check=config.FACTCHECK_LLM_MODEL_PRO,
            extraction=config.EXTRACTION_LLM_MODEL_PRO,
        )
    return LlmModels(
        social=config.SOCIAL_LLM_MODEL_STANDARD,
        fact_check=config.FACTCHECK_LLM_MODEL_STANDARD,
        extraction=config.EXTRACTION_LLM_MODEL_STANDARD,
    )


def resolve_tier_from_model(value: str | None) -> str:
    if not value:
        return config.DEFAULT_TRANSCRIBE_TIER
    normalized = value.strip().lower()
    if normalized in config.TRANSCRIBE_TIERS:
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
    return config.DEFAULT_TRANSCRIBE_TIER


def estimate_prompt_tokens(text: str) -> int:
    ratio = config.LLM_TOKEN_CHAR_RATIO
    if ratio <= 0:
        ratio = 4.0
    return max(1, math.ceil(len(text) / ratio))


def estimate_prompt_tokens_from_chars(char_count: int) -> int:
    ratio = config.LLM_TOKEN_CHAR_RATIO
    if ratio <= 0:
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
    per_1k = config.CREDITS_PER_1K_TOKENS[normalized]
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
    per_min = config.CREDITS_PER_MINUTE_TRANSCRIBE[normalized]
    credits = math.ceil(minutes * per_min)
    return max(int(min_credits), int(credits))


def stt_cost_usd(*, tier: str, duration_seconds: float) -> float:
    normalized = normalize_tier(tier)
    minutes = max(0.0, float(duration_seconds)) / 60.0
    return minutes * float(config.STT_PRICE_PER_MINUTE_USD[normalized])


def llm_cost_usd(
    session: Session,
    *,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    pricing = CostService.get_model_pricing(session, model_name)
    if pricing:
        input_price = pricing.input_price_per_1m
        output_price = pricing.output_price_per_1m
    else:
        fallback = config.MODEL_PRICING.get(model_name) or config.MODEL_PRICING.get("default")
        input_price = float(fallback["input"]) if fallback else 0.0
        output_price = float(fallback["output"]) if fallback else 0.0

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
