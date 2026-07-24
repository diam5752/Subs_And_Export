"""LLM Client Management and Utilities."""

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
            with secrets_path.open("rb") as f:
                secrets = tomllib.load(f)
                value = secrets.get(env_name)
                return value if isinstance(value, str) and value else None
        except Exception as exc:
            logger.warning("Failed to read provider secrets for %s: %s", env_name, exc)

    return None


def resolve_openai_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve the OpenAI API key from arguments, environment, or secrets."""
    return _resolve_provider_api_key("OPENAI_API_KEY", explicit_key)


def resolve_groq_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve the Groq API key from arguments, environment, or secrets."""
    return _resolve_provider_api_key("GROQ_API_KEY", explicit_key)


def resolve_elevenlabs_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve the ElevenLabs API key without activating the provider."""
    return _resolve_provider_api_key("ELEVENLABS_API_KEY", explicit_key)


def load_openai_client(
    api_key: str, base_url: str | None = None, timeout: float = 60.0
) -> Any:
    """
    Load OpenAI client with secure API key.

    Args:
        api_key: OpenAI API key for authentication
        base_url: Optional base URL (e.g. for Groq)
        timeout: Default timeout in seconds (default: 60.0)

    Returns:
        Configured OpenAI client instance

    Raises:
        RuntimeError: If openai package is not installed
    """
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI package is not installed. Please run 'pip install openai'."
        ) from exc

    # Security: Enforce default timeout to prevent indefinite hanging (DoS)
    # Consumers can override this per-request if needed (e.g. for long transcriptions)
    return OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        max_retries=0,
    )


def clean_json_response(content: str) -> str:
    """
    Strip markdown code fences from LLM response to ensure valid JSON.
    """
    content = content.replace("```json", "").replace("```", "").strip()
    return content


def extract_chat_completion_text(response: Any) -> tuple[str | None, str | None]:
    """
    Extract text content from an OpenAI Chat Completions response.

    Returns:
        (content, refusal)
    """
    try:
        choice = response.choices[0]
        message = choice.message

        # Check for refusal first (new API feature)
        refusal = getattr(message, "refusal", None)
        if refusal:
            return None, refusal

        content = message.content

        # Handle list content (e.g. from vision models)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
            content = "".join(text_parts)

        if content:
            return content.strip(), None

        # Fallback to tool calls if content is empty
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls and len(tool_calls) > 0:
            # For simplicity, return the arguments of the first function call
            # This mimics behavior expected by existing tests for structured output fallback
            return tool_calls[0].function.arguments, None

        return None, None
    except (AttributeError, IndexError) as e:
        logger.error(f"Failed to extract content from response: {e}")
        return None, "Invalid response format"
    except Exception as e:
        logger.error(f"Unexpected error extracting content: {e}")
        return None, str(e)


def chat_completion_debug(response: Any | None) -> None:
    if not response:
        logger.debug("ChatCompletion response is None")
        return

    try:
        usage = getattr(response, "usage", None)
        if usage:
            logger.debug(
                "Token usage - Prompt: %d, Completion: %d, Total: %d",
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
            )
    except (AttributeError, TypeError) as exc:
        logger.debug("ChatCompletion usage metadata was unavailable: %s", exc)
