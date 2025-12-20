"""Unit tests for pricing service (tier resolution, credit calculations, cost estimates)."""

from __future__ import annotations

import pytest

from backend.app.core import config
from backend.app.services import pricing


class TestTierNormalization:
    """Test tier string normalization."""

    def test_normalize_standard_tier(self) -> None:
        assert pricing.normalize_tier("standard") == "standard"
        assert pricing.normalize_tier("STANDARD") == "standard"
        assert pricing.normalize_tier("  Standard  ") == "standard"

    def test_normalize_pro_tier(self) -> None:
        assert pricing.normalize_tier("pro") == "pro"
        assert pricing.normalize_tier("PRO") == "pro"
        assert pricing.normalize_tier("  Pro  ") == "pro"

    def test_normalize_none_returns_default(self) -> None:
        assert pricing.normalize_tier(None) == config.DEFAULT_TRANSCRIBE_TIER

    def test_normalize_invalid_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid tier"):
            pricing.normalize_tier("invalid")


class TestTierResolution:
    """Test resolving tier from legacy model strings."""

    def test_resolve_tier_from_standard(self) -> None:
        assert pricing.resolve_tier_from_model("standard") == "standard"
        assert pricing.resolve_tier_from_model("turbo") == "standard"
        assert pricing.resolve_tier_from_model("enhanced") == "standard"
        assert pricing.resolve_tier_from_model("whisper-large-v3-turbo") == "standard"

    def test_resolve_tier_from_pro(self) -> None:
        assert pricing.resolve_tier_from_model("pro") == "pro"
        assert pricing.resolve_tier_from_model("ultimate") == "pro"
        assert pricing.resolve_tier_from_model("whisper-1") == "pro"
        assert pricing.resolve_tier_from_model("whisper-large-v3") == "pro"
        assert pricing.resolve_tier_from_model("openai") == "pro"

    def test_resolve_tier_from_none_returns_default(self) -> None:
        assert pricing.resolve_tier_from_model(None) == config.DEFAULT_TRANSCRIBE_TIER

    def test_resolve_tier_from_empty_returns_default(self) -> None:
        assert pricing.resolve_tier_from_model("") == config.DEFAULT_TRANSCRIBE_TIER


class TestProviderResolution:
    """Test transcription provider resolution."""

    def test_resolve_standard_provider(self) -> None:
        provider = pricing.resolve_transcribe_provider("standard")
        assert provider == "groq"

    def test_resolve_pro_provider(self) -> None:
        provider = pricing.resolve_transcribe_provider("pro")
        assert provider == "groq"


class TestModelResolution:
    """Test transcription model resolution."""

    def test_resolve_standard_model(self) -> None:
        model = pricing.resolve_transcribe_model("standard")
        assert model == config.GROQ_MODEL_STANDARD

    def test_resolve_pro_model(self) -> None:
        model = pricing.resolve_transcribe_model("pro")
        assert model == config.GROQ_MODEL_ULTIMATE


class TestLlmModelsResolution:
    """Test LLM model resolution by tier."""

    def test_standard_tier_llm_models(self) -> None:
        models = pricing.resolve_llm_models("standard")
        assert models.social == config.SOCIAL_LLM_MODEL_STANDARD
        assert models.fact_check == config.FACTCHECK_LLM_MODEL_STANDARD
        assert models.extraction == config.EXTRACTION_LLM_MODEL_STANDARD

    def test_pro_tier_llm_models(self) -> None:
        models = pricing.resolve_llm_models("pro")
        assert models.social == config.SOCIAL_LLM_MODEL_PRO
        assert models.fact_check == config.FACTCHECK_LLM_MODEL_PRO
        assert models.extraction == config.EXTRACTION_LLM_MODEL_PRO


class TestCreditsCalculation:
    """Test credit calculation functions."""

    def test_credits_for_minutes_standard(self) -> None:
        credits = pricing.credits_for_minutes(tier="standard", duration_seconds=60.0, min_credits=25)
        # 1 minute at 10 credits/min = 10, but min is 25
        assert credits == 25

    def test_credits_for_minutes_longer_video(self) -> None:
        credits = pricing.credits_for_minutes(tier="standard", duration_seconds=180.0, min_credits=25)
        # 3 minutes at 10 credits/min = 30
        assert credits == 30

    def test_credits_for_minutes_pro(self) -> None:
        credits = pricing.credits_for_minutes(tier="pro", duration_seconds=180.0, min_credits=50)
        # 3 minutes at 20 credits/min = 60
        assert credits == 60

    def test_credits_for_tokens_standard(self) -> None:
        credits = pricing.credits_for_tokens(
            tier="standard",
            prompt_tokens=1000,
            completion_tokens=500,
            min_credits=10,
        )
        # 1500 tokens at 2/1k = 3, but min is 10
        assert credits == 10

    def test_credits_for_tokens_many(self) -> None:
        credits = pricing.credits_for_tokens(
            tier="standard",
            prompt_tokens=5000,
            completion_tokens=2000,
            min_credits=10,
        )
        # 7000 tokens at 2/1k = 14
        assert credits == 14

    def test_credits_for_tokens_pro(self) -> None:
        credits = pricing.credits_for_tokens(
            tier="pro",
            prompt_tokens=5000,
            completion_tokens=2000,
            min_credits=20,
        )
        # 7000 tokens at 7/1k = 49
        assert credits == 49


class TestCostEstimation:
    """Test cost estimation functions."""

    def test_stt_cost_usd_standard(self) -> None:
        cost = pricing.stt_cost_usd(tier="standard", duration_seconds=180.0)
        # 3 minutes at $0.003/min = $0.009
        assert 0.008 < cost < 0.01

    def test_stt_cost_usd_pro(self) -> None:
        cost = pricing.stt_cost_usd(tier="pro", duration_seconds=180.0)
        # 3 minutes at $0.006/min = $0.018
        assert 0.017 < cost < 0.02


class TestTokenEstimation:
    """Test token estimation from text."""

    def test_estimate_prompt_tokens(self) -> None:
        # 100 chars at 4 chars/token = 25 tokens
        tokens = pricing.estimate_prompt_tokens("a" * 100)
        assert tokens == 25

    def test_estimate_prompt_tokens_from_chars(self) -> None:
        tokens = pricing.estimate_prompt_tokens_from_chars(100)
        assert tokens == 25

    def test_estimate_minimum_one_token(self) -> None:
        tokens = pricing.estimate_prompt_tokens("")
        assert tokens == 1
