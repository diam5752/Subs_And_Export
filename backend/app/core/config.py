"""Configuration for the Greek subtitle publisher using pydantic-settings."""

from __future__ import annotations

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Annotated

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
GOOGLE_PUBLIC_OAUTH_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
GOOGLE_INTERNAL_OAUTH_CERTS_URL = "http://edge:8081/oauth2/v1/certs"
APPROVED_GOOGLE_OAUTH_CERTS_URLS = frozenset(
    {
        GOOGLE_PUBLIC_OAUTH_CERTS_URL,
        GOOGLE_INTERNAL_OAUTH_CERTS_URL,
    }
)
STRIPE_PUBLIC_API_BASE = "https://api.stripe.com"
STRIPE_INTERNAL_API_BASE = "http://edge:8081/stripe"
APPROVED_STRIPE_API_BASES = frozenset(
    {
        STRIPE_PUBLIC_API_BASE,
        STRIPE_INTERNAL_API_BASE,
    }
)
ELEVENLABS_PUBLIC_API_BASE = "https://api.elevenlabs.io"
ELEVENLABS_INTERNAL_API_BASE = "http://edge:8081/elevenlabs"
APPROVED_ELEVENLABS_API_BASES = frozenset(
    {
        ELEVENLABS_PUBLIC_API_BASE,
        ELEVENLABS_INTERNAL_API_BASE,
    }
)


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

    @field_validator("google_oauth_certs_url", mode="before")
    @classmethod
    def validate_google_oauth_certs_url(cls, value: object) -> str:
        normalized = str(value).strip()
        if normalized not in APPROVED_GOOGLE_OAUTH_CERTS_URLS:
            raise ValueError("GSP_GOOGLE_OAUTH_CERTS_URL must use an approved Google OAuth certificate endpoint")
        return normalized

    @field_validator("stripe_api_base", mode="before")
    @classmethod
    def validate_stripe_api_base(cls, value: object) -> str:
        normalized = str(value).strip().rstrip("/")
        if normalized not in APPROVED_STRIPE_API_BASES:
            raise ValueError("GSP_STRIPE_API_BASE must use an approved Stripe API endpoint")
        return normalized

    @field_validator("elevenlabs_api_base", mode="before")
    @classmethod
    def validate_elevenlabs_api_base(cls, value: object) -> str:
        normalized = str(value).strip().rstrip("/")
        if normalized not in APPROVED_ELEVENLABS_API_BASES:
            raise ValueError("GSP_ELEVENLABS_API_BASE must use an approved ElevenLabs API endpoint")
        return normalized

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

    @field_validator("erasure_journal_continuity_id", mode="before")
    @classmethod
    def validate_erasure_journal_continuity_id(cls, value: object) -> str:
        """Accept only an opaque deployment-generated continuity identifier."""
        normalized = str(value or "").strip().lower()
        if normalized and re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
            raise ValueError(
                "GSP_ERASURE_JOURNAL_CONTINUITY_ID must be a 64-character hex value",
            )
        return normalized

    @property
    def is_dev(self) -> bool:
        return self.app_env == AppEnv.DEV

    # --- Project Paths ---
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    watermark_path: Path = PROJECT_ROOT / "gsubs-logo.png"

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
    google_auth_nonce_ttl_seconds: int = Field(
        default=600,
        ge=60,
        le=900,
        validation_alias="GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS",
    )
    google_oauth_certs_url: str = Field(
        default=GOOGLE_PUBLIC_OAUTH_CERTS_URL,
        validation_alias="GSP_GOOGLE_OAUTH_CERTS_URL",
    )

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
    elevenlabs_api_base: str = Field(
        default="https://api.elevenlabs.io",
        min_length=1,
        validation_alias="GSP_ELEVENLABS_API_BASE",
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
    consumer_policy_approved: bool = Field(
        default=False,
        validation_alias="GSP_CONSUMER_POLICY_APPROVED",
    )
    durable_confirmation_channel_ready: bool = Field(
        default=False,
        validation_alias="GSP_DURABLE_CONFIRMATION_CHANNEL_READY",
    )
    adjustment_workflow_ready: bool = Field(
        default=False,
        validation_alias="GSP_ADJUSTMENT_WORKFLOW_READY",
    )
    stripe_api_base: str = Field(
        default=STRIPE_PUBLIC_API_BASE,
        validation_alias="GSP_STRIPE_API_BASE",
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
    max_upload_mb: int = Field(default=500, gt=0, validation_alias="GSP_MAX_UPLOAD_MB")
    workspace_retention_hours: int = Field(
        default=24,
        gt=0,
        validation_alias="GSP_WORKSPACE_RETENTION_HOURS",
    )
    stale_job_retention_hours: int = Field(
        default=6,
        gt=0,
        validation_alias="GSP_STALE_JOB_RETENTION_HOURS",
    )
    orphan_retention_hours: int = Field(
        default=1,
        gt=0,
        validation_alias="GSP_ORPHAN_RETENTION_HOURS",
    )
    cleanup_interval_minutes: int = Field(
        default=15,
        gt=0,
        validation_alias="GSP_CLEANUP_INTERVAL_MINUTES",
    )
    storage_min_free_mb: int = Field(
        default=2048,
        gt=0,
        validation_alias="GSP_STORAGE_MIN_FREE_MB",
    )
    retention_cleanup_enabled: bool = Field(
        default=True,
        validation_alias="GSP_RETENTION_CLEANUP_ENABLED",
    )
    erasure_journal_dir: Path = Field(
        default=PROJECT_ROOT / ".runtime" / "erasure-journal",
        validation_alias="GSP_ERASURE_JOURNAL_DIR",
    )
    erasure_journal_retention_days: int = Field(
        default=30,
        ge=14,
        le=365,
        validation_alias="GSP_ERASURE_JOURNAL_RETENTION_DAYS",
    )
    erasure_journal_continuity_id: str = Field(
        default="",
        validation_alias="GSP_ERASURE_JOURNAL_CONTINUITY_ID",
    )
    signup_limit_per_ip_per_day: int = 5
    static_rate_limit: int = 60
    static_rate_limit_window: int = 60

    # --- Runtime defaults ---
    use_llm_by_default: bool = Field(default=False, validation_alias="GSP_USE_LLM_BY_DEFAULT")
    llm_model: str = Field(default="gpt-5-mini", validation_alias="GSP_LLM_MODEL")
    llm_temperature: float = Field(default=0.6, validation_alias="GSP_LLM_TEMPERATURE")

    def assert_paid_credits_configuration(self) -> None:
        """Fail closed before a runtime can create real Checkout Sessions."""
        if not self.paid_credits_enabled:
            return
        missing_launch_gates = [
            gate
            for gate, ready in (
                ("consumer policy approval", self.consumer_policy_approved),
                (
                    "durable contract-confirmation channel",
                    self.durable_confirmation_channel_ready,
                ),
                ("approved manual adjustment workflow", self.adjustment_workflow_ready),
            )
            if not ready
        ]
        if missing_launch_gates:
            raise RuntimeError(
                "Paid credit Checkout remains fail closed until these independent "
                f"launch gates are ready: {', '.join(missing_launch_gates)}."
            )
        if self.stripe_automatic_tax_enabled:
            raise RuntimeError(
                "Stripe Automatic Tax is owner-gated until active tax registrations "
                "and the tax-inclusive catalog are reviewed."
            )

        if not self.assert_stripe_stage_configuration():
            raise RuntimeError(
                "A Stripe restricted key, webhook signing secret and all three "
                "Stripe credit Price IDs are required."
            )

    def assert_stripe_stage_configuration(self) -> bool:
        """Validate an all-or-nothing Stripe bundle without enabling Checkout."""
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
        price_ids = (
            self.stripe_price_starter.strip(),
            self.stripe_price_core.strip(),
            self.stripe_price_pro.strip(),
        )
        if not any((restricted_key, webhook_secret, *price_ids)):
            return False
        if not restricted_key:
            raise RuntimeError(
                "Stripe staging configuration must be complete or entirely absent; "
                "a Stripe restricted key is required."
            )
        if not webhook_secret:
            raise RuntimeError(
                "Stripe staging configuration must be complete or entirely absent; "
                "a Stripe webhook signing secret is required."
            )
        if not all(price_id.startswith("price_") for price_id in price_ids):
            raise RuntimeError(
                "Stripe staging configuration must be complete or entirely absent; "
                "all three Stripe credit Price IDs are required."
            )
        if self.stripe_automatic_tax_enabled:
            raise RuntimeError(
                "Stripe Automatic Tax is owner-gated until active tax registrations "
                "and the tax-inclusive catalog are reviewed."
            )

        self.assert_stripe_gateway_configuration()
        if "{CHECKOUT_SESSION_ID}" not in self.stripe_success_url:
            raise RuntimeError("Stripe success URL must include {CHECKOUT_SESSION_ID}.")
        if not self.is_dev and (
            not self.stripe_success_url.startswith("https://")
            or not self.stripe_cancel_url.startswith("https://")
        ):
            raise RuntimeError("Stripe return URLs must use HTTPS outside development.")
        return True

    def assert_stripe_gateway_configuration(self) -> None:
        """Require mode-matched, non-empty secrets before any Stripe SDK use."""
        restricted_key = (
            self.stripe_restricted_key.get_secret_value().strip() if self.stripe_restricted_key is not None else ""
        )
        webhook_secret = (
            self.stripe_webhook_secret.get_secret_value().strip() if self.stripe_webhook_secret is not None else ""
        )
        expected_key_prefix = "rk_test_" if self.is_dev else "rk_live_"
        if not restricted_key.startswith(expected_key_prefix):
            raise RuntimeError(
                "A Stripe restricted key with an "
                f"{expected_key_prefix} prefix is required for paid credits "
                "in this runtime environment."
            )
        if not webhook_secret.startswith("whsec_"):
            raise RuntimeError("A Stripe webhook signing secret is required for paid credits.")

    @property
    def paid_credit_checkout_enabled(self) -> bool:
        """Expose the complete launch gate without activating any side effect."""
        return (
            self.paid_credits_enabled
            and self.consumer_policy_approved
            and self.durable_confirmation_channel_ready
            and self.adjustment_workflow_ready
        )


settings = Settings()
