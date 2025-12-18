import json

import pytest

from backend.app.services import subtitles


def _fake_openai_client(calls: dict | None = None):
    """OpenAI-compatible stub that records completion kwargs."""
    if calls is None:
        calls = {}

    class FakeMessage:
        def __init__(self, content: str) -> None:
            self.content = content

    class FakeChoice:
        def __init__(self, content: str) -> None:
            self.message = FakeMessage(content)

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.choices = [FakeChoice(content)]

    class FakeChatCompletions:
        def create(self, **kwargs):
            calls["kwargs"] = kwargs
            payload = {
                "title": "Generic Title",
                "description": "Generic Description",
                "hashtags": ["#generic", "#test"],
            }
            return FakeResponse(json.dumps(payload))

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeChatCompletions()

    class FakeClient:
        def __init__(self) -> None:
            self.chat = FakeChat()

    return FakeClient()


def test_build_social_copy_returns_generic_strings() -> None:
    transcript = "Coding tips coding flow python python testing coffee rituals for focus."

    social = subtitles.build_social_copy(transcript)

    assert social.generic.title.startswith("Coding & Python")
    assert "#coding" in social.generic.hashtags
    assert "#python" in social.generic.hashtags
    assert "#trending" in social.generic.hashtags
    assert "Coding tips" in social.generic.description
    assert "#viral" in social.generic.description


def test_build_social_copy_llm_uses_client(monkeypatch) -> None:
    calls = {}

    # Mock the OpenAI client
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: _fake_openai_client(calls))

    social = subtitles.build_social_copy_llm("hello world", model="gpt-test", temperature=0.7)

    assert calls["kwargs"]["model"] == "gpt-test"
    assert calls["kwargs"]["temperature"] == 0.7
    assert social.generic.title == "Generic Title"
    assert social.generic.description == "Generic Description"
    assert "#generic" in social.generic.hashtags


def test_build_social_copy_llm_prefers_explicit_key(monkeypatch) -> None:
    calls = {}
    captured_keys: list[str] = []

    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(
        subtitles,
        "_load_openai_client",
        lambda api_key: captured_keys.append(api_key) or _fake_openai_client(calls),
    )

    subtitles.build_social_copy_llm("hello world", api_key="explicit-key")

    assert captured_keys == ["explicit-key"]


def test_build_social_copy_llm_requires_key(monkeypatch) -> None:
    """Verify that API key is required for LLM social copy generation."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OpenAI API key is required"):
        subtitles.build_social_copy_llm("hi there")


def test_clean_json_response_strips_markdown() -> None:
    """Verify that markdown code fences are removed from JSON response."""
    raw = "```json\n{\"title\": \"T\", \"description\": \"D\", \"hashtags\": [\"#t\"]}\n```"
    cleaned = subtitles._clean_json_response(raw)
    assert cleaned.startswith("{")
    assert cleaned.endswith("}")
    assert "```" not in cleaned


def test_build_social_copy_llm_retries_on_failure(monkeypatch) -> None:
    """Verify that the function retries on invalid JSON."""

    class FlakyChatCompletions:
        def __init__(self):
            self.attempts = 0

        def create(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                # First attempt returns invalid JSON
                return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": "Not JSON"})})]})()
            # Second attempt returns valid JSON
            payload = {
                "title": "Retried Title",
                "description": "Retried Description",
                "hashtags": ["#retry"],
            }
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": json.dumps(payload)})})]})()

    class FlakyClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FlakyChatCompletions()})()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = FlakyClient()
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: client)

    social = subtitles.build_social_copy_llm("transcript")

    assert client.chat.completions.attempts == 2
    assert social.generic.title == "Retried Title"
