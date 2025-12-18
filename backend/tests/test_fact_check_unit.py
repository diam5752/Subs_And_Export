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
                "truth_score": 85,
                "supported_claims_pct": 90,
                "claims_checked": 10,
                "items": [
                    {
                        "mistake": "Wrong date",
                        "correction": "Correct date",
                        "explanation": "It was 1999 not 1998",
                        "severity": "minor",
                        "confidence": 95,
                        "real_life_example": "If you check any newspaper from that time, you'll see it was 1999",
                        "scientific_evidence": "Historical records and official documents confirm the date was 1999"
                    }
                ]
            }
            return FakeResponse(json.dumps(payload))

    class FakeChat:
        def __init__(self) -> None:
            self.completions = FakeChatCompletions()

    class FakeClient:
        def __init__(self) -> None:
            self.chat = FakeChat()

    return FakeClient()

def test_generate_fact_check_uses_correct_model_and_params(monkeypatch) -> None:
    calls = {}
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: _fake_openai_client(calls))

    result = subtitles.generate_fact_check("some text")

    assert calls["kwargs"]["model"] == subtitles.config.FACTCHECK_LLM_MODEL  # defaulting to config.FACTCHECK_LLM_MODEL
    # Temperature is not set in generate_fact_check, so we shouldn't assert it unless we change the code.
    # assert calls["kwargs"]["temperature"] == 0
    assert calls["kwargs"]["max_completion_tokens"] == 800

    assert result.truth_score == 85
    assert len(result.items) == 1
    assert result.items[0].mistake == "Wrong date"
    assert result.items[0].severity == "minor"
    assert result.items[0].confidence == 95
    assert result.items[0].real_life_example != ""
    assert result.items[0].scientific_evidence != ""

def test_generate_fact_check_retries_on_invalid_json(monkeypatch) -> None:
    class FlakyChatCompletions:
        def __init__(self):
            self.attempts = 0

        def create(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": "Not JSON"})})]})()

            payload = {
                "truth_score": 100,
                "supported_claims_pct": 100,
                "claims_checked": 5,
                "items": []
            }
            return type("Response", (), {"choices": [type("Choice", (), {"message": type("Message", (), {"content": json.dumps(payload)})})]})()

    class FlakyClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FlakyChatCompletions()})()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = FlakyClient()
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: client)

    result = subtitles.generate_fact_check("transcript")

    assert client.chat.completions.attempts == 2
    assert result.truth_score == 100
    assert result.items == []

def test_generate_fact_check_raises_on_failure(monkeypatch) -> None:
    class BrokenClient:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise ValueError("API Error")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: BrokenClient())

    with pytest.raises(ValueError):
        subtitles.generate_fact_check("transcript")


def test_generate_fact_check_retries_on_empty_response(monkeypatch) -> None:
    # REGRESSION: OpenAI can occasionally return empty message.content; we must retry instead of 500'ing.
    class FlakyChatCompletions:
        def __init__(self):
            self.attempts = 0

        def create(self, **kwargs):
            self.attempts += 1
            if self.attempts == 1:
                return type(
                    "Response",
                    (),
                    {"choices": [type("Choice", (), {"message": type("Message", (), {"content": ""})})]},
                )()

            payload = {
                "truth_score": 100,
                "supported_claims_pct": 100,
                "claims_checked": 5,
                "items": [],
            }
            fenced = f"```json\n{json.dumps(payload)}\n```"
            return type(
                "Response",
                (),
                {"choices": [type("Choice", (), {"message": type("Message", (), {"content": fenced})})]},
            )()

    class FlakyClient:
        def __init__(self):
            self.chat = type("Chat", (), {"completions": FlakyChatCompletions()})()

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = FlakyClient()
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: client)

    result = subtitles.generate_fact_check("transcript")

    assert client.chat.completions.attempts == 2
    assert result.truth_score == 100
    assert result.items == []


def test_extract_chat_completion_text_supports_list_and_tool_calls() -> None:
    response_list = type(
        "Response",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {"message": type("Message", (), {"content": [{"text": " hello "}]}), "finish_reason": "stop"},
                )
            ]
        },
    )()
    assert subtitles._extract_chat_completion_text(response_list) == ("hello", None)

    tool_call = type("ToolCall", (), {"function": type("Fn", (), {"arguments": "{\"a\":1}"})})()
    response_tool = type(
        "Response",
        (),
        {
            "choices": [
                type(
                    "Choice",
                    (),
                    {"message": type("Message", (), {"content": None, "tool_calls": [tool_call]}), "finish_reason": "stop"},
                )
            ]
        },
    )()
    assert subtitles._extract_chat_completion_text(response_tool) == ('{"a":1}', None)
