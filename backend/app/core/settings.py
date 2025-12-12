"""Application-level settings shared across the backend and CLI."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config

# Defaults for AI + upload settings used across the stack
DEFAULT_USE_LLM = False
DEFAULT_LLM_MODEL = config.SOCIAL_LLM_MODEL
DEFAULT_LLM_TEMPERATURE = 0.6
DEFAULT_MAX_UPLOAD_MB = 2048


@dataclass(frozen=True)
class AppSettings:
    use_llm_by_default: bool = DEFAULT_USE_LLM
    llm_model: str = DEFAULT_LLM_MODEL
    llm_temperature: float = DEFAULT_LLM_TEMPERATURE
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB


def _coerce_bool(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return fallback


def _coerce_int(value: object, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def _coerce_float(value: object, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def load_app_settings(path: str | Path | None = None) -> AppSettings:
    """
    Load app settings from a TOML file, falling back to sensible defaults.

    Order of precedence:
    1. Explicit ``path`` argument
    2. ``GSP_APP_SETTINGS_FILE`` environment variable
    3. ``config/app_settings.toml`` beside the repository root
    """
    candidate = Path(path) if path else None
    if not candidate:
        env_override = os.getenv("GSP_APP_SETTINGS_FILE")
        if env_override:
            candidate = Path(env_override)
        else:
            candidate = config.PROJECT_ROOT / "config" / "app_settings.toml"

    if not candidate.exists():
        return AppSettings()

    try:
        data = tomllib.loads(candidate.read_text())
    except Exception:
        return AppSettings()

    ai = data.get("ai", {}) if isinstance(data, dict) else {}
    uploads = data.get("uploads", {}) if isinstance(data, dict) else {}

    return AppSettings(
        use_llm_by_default=_coerce_bool(ai.get("enable_by_default"), DEFAULT_USE_LLM),
        llm_model=str(ai.get("model", DEFAULT_LLM_MODEL)),
        llm_temperature=_coerce_float(ai.get("temperature"), DEFAULT_LLM_TEMPERATURE),
        max_upload_mb=_coerce_int(uploads.get("max_upload_mb"), DEFAULT_MAX_UPLOAD_MB),
    )
