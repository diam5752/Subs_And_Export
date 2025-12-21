"""Configuration for the Greek subtitle publisher using pydantic-settings."""

from __future__ import annotations

import os
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import AliasChoices, Field, field_validator, validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class AppEnv(StrEnum):
    DEV = "dev"
    PRODUCTION = "production"


class LegacyTomlSettingsSource(PydanticBaseSettingsSource):
    def __init__(self, settings_cls: type[BaseSettings], toml_file: str | Path):
        super().__init__(settings_cls)
        self.toml_file = Path(toml_file)

    def get_field_value(self, field_name: str, field_data: Any) -> tuple[Any, str, bool]:
        # Not used in this source style
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        if not self.toml_file.exists():
            return {}

        import tomllib

        try:
            with open(self.toml_file, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            return {}

        if not isinstance(data, dict):
            return {}

        # Flatten nested keys for legacy compatibility
        flattened = {}
        
        # [ai] section
        ai = data.get("ai", {})
        if isinstance(ai, dict):
            if "enable_by_default" in ai:
                flattened["use_llm_by_default"] = ai["enable_by_default"]
            if "model" in ai:
                flattened["llm_model"] = ai["model"]
            if "temperature" in ai:
                flattened["llm_temperature"] = ai["temperature"]

        # [uploads] section
        uploads = data.get("uploads", {})
        if isinstance(uploads, dict):
            if "max_upload_mb" in uploads:
                flattened["max_upload_mb"] = uploads["max_upload_mb"]

        # Top level keys
        for k, v in data.items():
            if k not in {"ai", "uploads"}:
                flattened[k] = v

        return flattened


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
    def normalize_env(cls, v: Any) -> AppEnv:
        if v is None:
            return AppEnv.PRODUCTION
        if isinstance(v, str):
            lowered = v.strip().lower()
            if lowered in {"dev", "development", "local", "localhost"}:
                return AppEnv.DEV
            return AppEnv.PRODUCTION

    @field_validator("allowed_origins", "trusted_hosts", "proxy_trusted_hosts", mode="before")
    @classmethod
    def parse_list(cls, v: Any) -> list[str]:
        if isinstance(v, str):
            v_stripped = v.strip()
            if not v_stripped:
                return []
            if v_stripped.startswith("[") and v_stripped.endswith("]"):
                import json
                try:
                    return json.loads(v_stripped)
                except Exception:
                    pass
            return [x.strip() for x in v_stripped.split(",") if x.strip()]
        return v or []

    @property
    def is_dev(self) -> bool:
        return self.app_env == AppEnv.DEV

    # --- Project Paths ---
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    watermark_path: Path = PROJECT_ROOT / "Ascentia_Logo.png"

    # --- API & Security ---
    allowed_origins: Any = Field(default_factory=list, validation_alias="GSP_ALLOWED_ORIGINS")
    trusted_hosts: Any = Field(default_factory=list, validation_alias="GSP_TRUSTED_HOSTS")
    proxy_trusted_hosts: Any = Field(
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
    max_video_duration_seconds: int = 210
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
    max_sub_line_chars: int = 28
    default_output_suffix: str = "_subbed"
    default_highlight_color: str = "&H0000FFFF"

    # --- STT (Local) ---
    whisper_model: str = "medium"
    whisper_language: str = "el"
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    whisper_chunk_length: int = 90
    whisper_batch_size: int = 16
    whispercpp_model: str = "medium"
    whispercpp_language: str = "el"

    # --- STT (Cloud) ---
    openai_transcribe_model: str = "whisper-1"
    groq_transcribe_model: str = "whisper-large-v3"
    groq_model_enhanced: str = "whisper-large-v3-turbo"
    groq_model_ultimate: str = "whisper-large-v3"

    # --- LLM ---
    social_llm_model: str = "gpt-5.1-mini"
    factcheck_llm_model: str = "gpt-5.1-mini"
    extraction_llm_model: str = "gpt-5.1-mini"

    # --- Pricing & Credits ---
    default_transcribe_tier: str = "standard"
    transcribe_tier_provider: Any = {"standard": "groq", "pro": "groq"}
    transcribe_tier_model: Any = {
        "standard": "whisper-large-v3-turbo",
        "pro": "whisper-large-v3",
    }
    credits_per_1k_tokens: Any = {"standard": 2, "pro": 7}
    credits_per_minute_transcribe: Any = {"standard": 10, "pro": 20}
    credits_min_transcribe: Any = {"standard": 25, "pro": 50}
    credits_min_social_copy: Any = {"standard": 10, "pro": 20}
    credits_min_fact_check: Any = {"standard": 20, "pro": 40}

    # --- Pricing (USD) ---
    stt_price_per_minute: dict[str, float] = {
        "standard": 0.003,
        "pro": 0.006,
    }
    # Pricing per 1M tokens
    llm_pricing: dict[str, dict[str, float]] = {
        "gpt-4o": {"input": 5.00, "output": 15.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-5.1-mini": {"input": 0.25, "output": 2.00},
    }
    default_llm_input_price: float = 0.25
    default_llm_output_price: float = 2.00

    # --- Safety Limits ---
    max_llm_input_chars: int = 15000
    max_llm_output_tokens_social: int = 3000
    max_llm_output_tokens_factcheck: int = 6000
    max_upload_mb: int = Field(default=1024, validation_alias="GSP_MAX_UPLOAD_MB")
    signup_limit_per_ip_per_day: int = 5
    static_rate_limit: int = 60
    static_rate_limit_window: int = 60

    # --- App Settings (Legacy from settings.py) ---
    use_llm_by_default: bool = Field(default=False, validation_alias="GSP_USE_LLM_BY_DEFAULT")
    llm_model: str = Field(default="gpt-5.1-mini", validation_alias="GSP_LLM_MODEL")
    llm_temperature: float = Field(default=0.6, validation_alias="GSP_LLM_TEMPERATURE")

    def __init__(self, **values: Any) -> None:
        super().__init__(**values)
        # Apply secure defaults for production if origins/hosts are missing
        if not self.is_dev:
            if not self.trusted_hosts:
                self.trusted_hosts = ["*.run.app", "*.a.run.app"]

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Order of precedence:
        # 1. Constructor arguments
        # 2. Environment variables
        # 3. .env file
        # 4. config/app_settings.toml (Legacy support)
        # 5. Secrets
        
        # Determine TOML path
        toml_path = os.getenv("GSP_APP_SETTINGS_FILE")
        if not toml_path:
            toml_path = str(PROJECT_ROOT / "config" / "app_settings.toml")
            
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            LegacyTomlSettingsSource(settings_cls, toml_file=toml_path),
            file_secret_settings,
        )


settings = Settings()
