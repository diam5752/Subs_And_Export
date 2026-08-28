"""Pricing and credits helpers for tiered video transcription."""

from __future__ import annotations

import math
from dataclasses import dataclass

from backend.app.core.config import settings


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
