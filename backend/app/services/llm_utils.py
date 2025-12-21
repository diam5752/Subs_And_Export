"""LLM Client Management and Utilities."""

from __future__ import annotations

import logging
import os
import tomllib
from typing import Any, Tuple

from backend.app.core import config

logger = logging.getLogger(__name__)


def should_use_openai(model_name: str | None) -> bool:
    """Check if the model name implies using OpenAI's API."""
    return model_name is not None and "openai" in model_name.lower()


def model_uses_openai(model_name: str | None) -> bool:
    """Helper for internal use (alias of should_use_openai)."""
    return should_use_openai(model_name)


def resolve_openai_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve OpenAI API key from arguments, env, or secrets file."""
    if explicit_key:
        return explicit_key

    # 1. Environment variable
    env_key = os.getenv("OPENAI_API_KEY")
    if env_key:
        return env_key

    # 2. Config/Secrets file
    secrets_path = config.PROJECT_ROOT / "config" / "secrets.toml"
    if secrets_path.exists():
        try:
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
                return secrets.get("OPENAI_API_KEY")
        except Exception as e:
            logger.warning(f"Failed to read secrets for OPENAI_API_KEY: {e}")

    return None


def resolve_groq_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve Groq API key from arguments, env, or secrets file."""
    if explicit_key:
        return explicit_key

    # 1. Environment variable
    env_key = os.getenv("GROQ_API_KEY")
    if env_key:
        return env_key

    # 2. Config/Secrets file
    secrets_path = config.PROJECT_ROOT / "config" / "secrets.toml"
    if secrets_path.exists():
        try:
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
                return secrets.get("GROQ_API_KEY")
        except Exception as e:
            logger.warning(f"Failed to read secrets for GROQ_API_KEY: {e}")

    return None


def load_openai_client(api_key: str) -> Any:
    """
    Load OpenAI client with secure API key.

    Args:
        api_key: OpenAI API key for authentication

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

    # Security: Enforce a default timeout of 60s to prevent DoS via infinite hangs.
    # Callers can override this by passing a timeout to specific method calls.
    return OpenAI(api_key=api_key, timeout=60.0)


def clean_json_response(content: str) -> str:
    """
    Strip markdown code fences from LLM response to ensure valid JSON.
    """
    content = content.replace("```json", "").replace("```", "").strip()
    return content


def extract_chat_completion_text(response: Any) -> Tuple[str | None, str | None]:
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
    except Exception:
        pass
