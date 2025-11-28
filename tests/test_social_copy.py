import json
import sys
import types
import pytest

from greek_sub_publisher import subtitles


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
                "tiktok": {"title": "TT", "description": "DESC TT"},
                "youtube_shorts": {"title": "YT", "description": "DESC YT"},
                "instagram": {"title": "IG", "description": "DESC IG"},
            }
            return FakeResponse(json.dumps(payload))

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeChatCompletions()

    class FakeClient:
        def __init__(self) -> None:
            self.chat = FakeChat()

    return FakeClient()


def test_build_social_copy_returns_platform_specific_strings() -> None:
    transcript = "Coding tips coding flow python python testing coffee rituals for focus."

    social = subtitles.build_social_copy(transcript)

    assert social.tiktok.title.startswith("Coding & Python")
    assert "Follow for daily Greek clips." in social.tiktok.description
    assert "#coding" in social.youtube_shorts.description
    assert social.instagram.title.endswith("Instagram Reels")
    assert "#reels" in social.instagram.description


def test_build_social_copy_llm_uses_client(monkeypatch) -> None:
    calls = {}

    # Mock the OpenAI client
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: _fake_openai_client(calls))

    social = subtitles.build_social_copy_llm("hello world", model="gpt-test", temperature=0.7)

    assert calls["kwargs"]["model"] == "gpt-test"
    assert calls["kwargs"]["temperature"] == 0.7
    assert social.tiktok.title == "TT"
    assert social.instagram.description == "DESC IG"


def test_build_social_copy_llm_prefers_explicit_key(monkeypatch) -> None:
    calls = {}
    captured_keys: list[str] = []

    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        types.SimpleNamespace(secrets={"OPENAI_API_KEY": "secret-key"}),
    )
    monkeypatch.setattr(
        subtitles,
        "_load_openai_client",
        lambda api_key: captured_keys.append(api_key) or _fake_openai_client(calls),
    )

    subtitles.build_social_copy_llm("hello world", api_key="explicit-key")

    assert captured_keys == ["explicit-key"]


def test_build_social_copy_llm_uses_streamlit_secrets(monkeypatch) -> None:
    calls = {}
    captured_keys: list[str] = []

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "streamlit",
        types.SimpleNamespace(secrets={"OPENAI_API_KEY": "secret-key"}),
    )
    monkeypatch.setattr(
        subtitles,
        "_load_openai_client",
        lambda api_key: captured_keys.append(api_key) or _fake_openai_client(calls),
    )

    subtitles.build_social_copy_llm("hello world")

    assert captured_keys == ["secret-key"]


def test_build_social_copy_llm_requires_key(monkeypatch) -> None:
    """Verify that API key is required for LLM social copy generation."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OpenAI API key is required"):
        subtitles.build_social_copy_llm("hi there")
