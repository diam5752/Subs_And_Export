"""Credential and client helpers for cloud speech-to-text providers."""

from __future__ import annotations

import logging
import os
import tomllib
from typing import Any

from backend.app.core.config import settings

logger = logging.getLogger(__name__)


def _resolve_provider_api_key(
    env_name: str,
    explicit_key: str | None = None,
) -> str | None:
    """Resolve one provider key without logging or exposing its value."""
    if explicit_key:
        return explicit_key

    env_key = os.getenv(env_name)
    if env_key:
        return env_key

    secrets_path = settings.project_root / "config" / "secrets.toml"
    if secrets_path.exists():
        try:
            with secrets_path.open("rb") as secrets_file:
                secrets = tomllib.load(secrets_file)
                value = secrets.get(env_name)
                return value if isinstance(value, str) and value else None
        except Exception as exc:
            logger.warning("Failed to read provider secrets for %s: %s", env_name, exc)

    return None


def resolve_openai_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve an OpenAI speech-to-text API key."""
    return _resolve_provider_api_key("OPENAI_API_KEY", explicit_key)


def resolve_groq_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve a Groq speech-to-text API key."""
    return _resolve_provider_api_key("GROQ_API_KEY", explicit_key)


def resolve_elevenlabs_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve an ElevenLabs speech-to-text API key."""
    return _resolve_provider_api_key("ELEVENLABS_API_KEY", explicit_key)


def load_openai_compatible_client(
    api_key: str,
    base_url: str | None = None,
    timeout: float = 60.0,
) -> Any:
    """Create the SDK client used by OpenAI-compatible transcription APIs."""
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI SDK is not installed. Please run 'pip install openai'.") from exc

    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )
