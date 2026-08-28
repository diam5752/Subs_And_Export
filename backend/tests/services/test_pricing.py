"""Unit tests for transcription pricing and credit calculations."""

from __future__ import annotations

import pytest

from backend.app.core.config import settings
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
        assert pricing.normalize_tier(None) == settings.default_transcribe_tier

    def test_normalize_invalid_tier_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid tier"):
            pricing.normalize_tier("invalid")


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
        assert model == settings.transcribe_tier_model["standard"]

    def test_resolve_pro_model(self) -> None:
        model = pricing.resolve_transcribe_model("pro")
        assert model == settings.transcribe_tier_model["pro"]

    def test_resolve_requested_model_for_openai_override(self) -> None:
        model = pricing.resolve_requested_transcribe_model(
            tier="pro",
            provider="openai",
            openai_model="whisper-1",
        )
        assert model == "whisper-1"

    def test_rejects_openai_model_without_word_timestamps(self) -> None:
        with pytest.raises(ValueError, match="requires the word-timed whisper-1"):
            pricing.resolve_requested_transcribe_model(
                tier="pro",
                provider="openai",
                openai_model="gpt-4o-transcribe",
            )

    def test_resolve_requested_model_for_openai_default(self) -> None:
        model = pricing.resolve_requested_transcribe_model(
            tier="pro",
            provider="openai",
            openai_model=None,
        )
        assert model == settings.openai_transcribe_model


class TestCreditsCalculation:
    """Test credit calculation functions."""

    @pytest.mark.parametrize(
        ("duration_seconds", "expected_credits", "expected_key"),
        [
            (0.001, 25, "up_to_3m"),
            (180.0, 25, "up_to_3m"),
            (180.001, 60, "up_to_6m"),
            (360.0, 60, "up_to_6m"),
            (360.001, 100, "up_to_10m"),
            (600.0, 100, "up_to_10m"),
        ],
    )
    def test_video_credit_brackets(
        self,
        duration_seconds: float,
        expected_credits: int,
        expected_key: str,
    ) -> None:
        # REGRESSION: client and server must agree on the exact 3/6/10 minute
        # boundaries so an upload can never dispatch with an under-reservation.
        quote = pricing.video_credit_quote(duration_seconds)

        assert quote.credits == expected_credits
        assert quote.key == expected_key
        assert pricing.credits_for_video_duration(duration_seconds) == expected_credits

    @pytest.mark.parametrize("duration_seconds", [0, -1, float("nan"), float("inf"), 600.001])
    def test_video_credit_brackets_reject_unpriced_durations(
        self,
        duration_seconds: float,
    ) -> None:
        with pytest.raises(ValueError, match="duration"):
            pricing.video_credit_quote(duration_seconds)

    def test_public_video_credit_catalog_is_immutable_copy(self) -> None:
        catalog = pricing.video_credit_catalog()
        catalog[0]["credits"] = 999

        assert pricing.video_credit_catalog()[0]["credits"] == 25

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

class TestCostEstimation:
    """Test cost estimation functions."""

    def test_stt_cost_usd_standard(self) -> None:
        cost = pricing.stt_cost_usd(tier="standard", duration_seconds=180.0)
        # Groq turbo: 3 minutes at $0.04/hour = $0.002
        assert cost == pytest.approx(0.002)

    def test_stt_cost_usd_pro(self) -> None:
        cost = pricing.stt_cost_usd(tier="pro", duration_seconds=180.0)
        # Groq large-v3: 3 minutes at $0.111/hour = $0.00555
        assert cost == pytest.approx(0.00555)

    def test_provider_specific_stt_costs(self) -> None:
        assert pricing.stt_provider_cost_usd(
            tier="standard",
            duration_seconds=3600,
            provider="groq",
            model="whisper-large-v3-turbo",
        ) == pytest.approx(0.04)
        assert pricing.stt_provider_cost_usd(
            tier="pro",
            duration_seconds=3600,
            provider="groq",
            model="whisper-large-v3",
        ) == pytest.approx(0.111)
        assert pricing.stt_provider_cost_usd(
            tier="standard",
            duration_seconds=3600,
            provider="local",
            model="large-v3-turbo",
        ) == 0.0
        assert pricing.stt_provider_cost_usd(
            tier="pro",
            duration_seconds=3600,
            provider="elevenlabs",
            model="scribe_v2",
        ) == pytest.approx(0.22)
