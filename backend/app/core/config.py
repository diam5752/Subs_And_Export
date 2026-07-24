"""Configuration for the Greek subtitle publisher using pydantic-settings."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class AppEnv(StrEnum):
    DEV = "dev"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- Environment ---
    app_env: AppEnv = Field(
        default=AppEnv.PRODUCTION,
        validation_alias=AliasChoices("GSP_APP_ENV", "APP_ENV", "ENV"),
    )

    @field_validator("app_env", mode="before")
    @classmethod
    def normalize_env(cls, v: object) -> AppEnv:
        if isinstance(v, AppEnv):
            return v
        if v is None:
            return AppEnv.PRODUCTION
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered in {"dev", "development", "local", "localhost"}:
                return AppEnv.DEV
        return AppEnv.PRODUCTION

    @field_validator("allowed_origins", "trusted_hosts", "proxy_trusted_hosts", mode="before")
    @classmethod
    def parse_list(cls, v: object) -> list[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return []
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                try:
                    parsed = json.loads(v_stripped)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            return [x.strip() for x in v_stripped.split(",") if x.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(item).strip() for item in v if str(item).strip()]
        return []

    @property
    def is_dev(self) -> bool:
        return self.app_env == AppEnv.DEV

    # --- Project Paths ---
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    watermark_path: Path = PROJECT_ROOT / "Ascentia_Logo.png"

    # --- API & Security ---
    allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias="GSP_ALLOWED_ORIGINS",
    )
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias="GSP_TRUSTED_HOSTS",
    )
    proxy_trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["127.0.0.1", "::1", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"],
        validation_alias="GSP_PROXY_TRUSTED_HOSTS",
    )
    force_https: bool = Field(default=False, validation_alias="GSP_FORCE_HTTPS")

    # --- Database ---
    database_url: str = Field(
        default="postgresql://localhost/gsp_dev",
        validation_alias=AliasChoices("GSP_DATABASE_URL", "DATABASE_URL"),
    )

    # --- Video & Audio Processing ---
    default_width: int = 1080
    default_height: int = 1920
    default_fps: int = 30
    max_resolution_dimension: int = 4096
    max_video_duration_seconds: int = Field(
        default=600,
        gt=0,
        validation_alias="GSP_MAX_VIDEO_DURATION_SECONDS",
    )
    max_concurrent_jobs: int = 2
    audio_sample_rate: int = 16000
    audio_channels: int = 1
    audio_codec: str = "pcm_s16le"
    default_video_crf: int = 23
    default_video_preset: str = "veryfast"
    default_audio_bitrate: str = "256k"
    use_hw_accel: bool = True

    # --- Subtitles ---
    default_sub_font: str = "Arial Black"
    default_sub_font_size: int = 62
    default_sub_color: str = "&H0000FFFF"
    default_sub_secondary_color: str = "&H00FFFFFF"
    default_sub_outline_color: str = "&H7F000000"
    default_sub_back_color: str = "&H96000000"
    default_sub_stroke_width: int = 3
    default_sub_alignment: int = 2
    default_sub_margin_v: int = 320
    default_sub_margin_l: int = 80
    default_sub_margin_r: int = 80
    max_sub_line_chars: int = 26
    default_output_suffix: str = "_subbed"
    default_highlight_color: str = "&H0000FFFF"

    # --- STT (Local) ---
    mock_external_services: bool = Field(
        default=True,
        validation_alias="GSP_MOCK_EXTERNAL_SERVICES",
    )
    whisper_model: str = "large-v3-turbo"
    whisper_language: str = "el"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_chunk_length: int = 90
    whisper_batch_size: int = 16
    whispercpp_model: str = "medium"
    whispercpp_language: str = "el"

    # --- STT (Cloud) ---
    # The caption renderer requires word timings. OpenAI's newer transcription
    # models are kept in the discovery catalog for text-only workflows, while
    # whisper-1 remains the caption-compatible OpenAI engine.
    openai_transcribe_model: str = "whisper-1"
    groq_transcribe_model: str = "whisper-large-v3"
    groq_model_enhanced: str = "whisper-large-v3-turbo"
    groq_model_ultimate: str = "whisper-large-v3"
    elevenlabs_enabled: bool = Field(
        default=False,
        validation_alias="GSP_ELEVENLABS_ENABLED",
    )
    elevenlabs_transcribe_model: str = "scribe_v2"

    # --- LLM ---
    social_llm_model: str = "gpt-5-mini"
    factcheck_llm_model: str = "gpt-5-mini"
    extraction_llm_model: str = "gpt-5-mini"

    # --- Pricing & Credits ---
    default_transcribe_tier: str = "standard"
    transcribe_tier_provider: dict[str, str] = {"standard": "groq", "pro": "groq"}
    transcribe_tier_model: dict[str, str] = {
        "standard": "whisper-large-v3-turbo",
        "pro": "whisper-large-v3",
    }
    credits_per_1k_tokens: dict[str, int] = {"standard": 2, "pro": 7}
    credits_per_minute_transcribe: dict[str, int] = {"standard": 10, "pro": 20}
    credits_min_transcribe: dict[str, int] = {"standard": 25, "pro": 50}
    credits_min_social_copy: dict[str, int] = {"standard": 10, "pro": 20}
    credits_min_fact_check: dict[str, int] = {"standard": 20, "pro": 40}

    # --- Prepaid credit Checkout (owner-gated; disabled until Stripe setup) ---
    paid_credits_enabled: bool = Field(
        default=False,
        validation_alias="GSP_PAID_CREDITS_ENABLED",
    )
    stripe_restricted_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GSP_STRIPE_RESTRICTED_KEY", "STRIPE_SECRET_KEY"),
    )
    stripe_webhook_secret: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("GSP_STRIPE_WEBHOOK_SECRET", "STRIPE_WEBHOOK_SECRET"),
    )
    stripe_price_starter: str = Field(default="", validation_alias="GSP_STRIPE_PRICE_STARTER")
    stripe_price_core: str = Field(default="", validation_alias="GSP_STRIPE_PRICE_CORE")
    stripe_price_pro: str = Field(default="", validation_alias="GSP_STRIPE_PRICE_PRO")
    stripe_success_url: str = Field(
        default="http://localhost:3000/?checkout=success&session_id={CHECKOUT_SESSION_ID}",
        validation_alias="GSP_STRIPE_SUCCESS_URL",
    )
    stripe_cancel_url: str = Field(
        default="http://localhost:3000/?checkout=cancelled",
        validation_alias="GSP_STRIPE_CANCEL_URL",
    )
    stripe_automatic_tax_enabled: bool = Field(
        default=False,
        validation_alias="GSP_STRIPE_AUTOMATIC_TAX_ENABLED",
    )
    stripe_webhook_tolerance_seconds: int = Field(
        default=300,
        ge=60,
        le=900,
        validation_alias="GSP_STRIPE_WEBHOOK_TOLERANCE_SECONDS",
    )

    # --- Pricing (USD) ---
    stt_price_per_minute: dict[str, float] = {
        # Groq list prices: $0.04/hour (turbo), $0.111/hour (large-v3).
        "standard": 0.04 / 60,
        "pro": 0.111 / 60,
    }
    # Pricing per 1M tokens
    llm_pricing: dict[str, dict[str, float]] = {
        "gpt-4o": {"input": 5.00, "output": 15.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-5-mini": {"input": 0.25, "output": 2.00},
    }
    default_llm_input_price: float = 0.25
    default_llm_output_price: float = 2.00

    # --- Safety Limits ---
    external_provider_monthly_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD",
    )
    external_provider_daily_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD",
    )
    external_provider_per_request_budget_usd: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD",
    )
    external_provider_price_safety_multiplier: float = Field(
        default=1.25,
        ge=1.0,
        le=2.0,
        validation_alias="GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER",
    )
    max_llm_input_chars: int = 15000
    max_llm_output_tokens_extraction: int = 1000
    max_llm_output_tokens_social: int = 3000
    max_llm_output_tokens_factcheck: int = 6000
    max_upload_mb: int = Field(default=1024, validation_alias="GSP_MAX_UPLOAD_MB")
    signup_limit_per_ip_per_day: int = 5
    static_rate_limit: int = 60
    static_rate_limit_window: int = 60

    # --- Runtime defaults ---
    use_llm_by_default: bool = Field(default=False, validation_alias="GSP_USE_LLM_BY_DEFAULT")
    llm_model: str = Field(default="gpt-5-mini", validation_alias="GSP_LLM_MODEL")
    llm_temperature: float = Field(default=0.6, validation_alias="GSP_LLM_TEMPERATURE")

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        # Apply secure defaults for production if origins/hosts are missing
        if not self.is_dev:
            if not self.trusted_hosts:
                self.trusted_hosts = ["*.run.app", "*.a.run.app"]

    def assert_paid_credits_configuration(self) -> None:
        """Fail closed before a runtime can create real Checkout Sessions."""
        if not self.paid_credits_enabled:
            return
        if self.stripe_automatic_tax_enabled:
            raise RuntimeError(
                "Stripe Automatic Tax is owner-gated until active tax registrations "
                "and the tax-inclusive catalog are reviewed."
            )

        restricted_key = (
            self.stripe_restricted_key.get_secret_value().strip()
            if self.stripe_restricted_key is not None
            else ""
        )
        webhook_secret = (
            self.stripe_webhook_secret.get_secret_value().strip()
            if self.stripe_webhook_secret is not None
            else ""
        )
        if not restricted_key.startswith(("rk_test_", "rk_live_")):
            raise RuntimeError("A Stripe restricted key is required for paid credits.")
        if not webhook_secret.startswith("whsec_"):
            raise RuntimeError("A Stripe webhook signing secret is required for paid credits.")
        for price_id in (
            self.stripe_price_starter,
            self.stripe_price_core,
            self.stripe_price_pro,
        ):
            if not price_id.strip().startswith("price_"):
                raise RuntimeError("All three Stripe credit Price IDs are required.")
        if "{CHECKOUT_SESSION_ID}" not in self.stripe_success_url:
            raise RuntimeError("Stripe success URL must include {CHECKOUT_SESSION_ID}.")
        if not self.is_dev and (
            not self.stripe_success_url.startswith("https://")
            or not self.stripe_cancel_url.startswith("https://")
        ):
            raise RuntimeError("Stripe return URLs must use HTTPS outside development.")

settings = Settings()
