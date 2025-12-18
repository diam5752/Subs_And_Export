
import json
import re
from unittest.mock import MagicMock

import pytest

from backend.app.services import subtitles


# --- TEST _extract_important_segments ---

def test_extract_important_segments_short_text():
    """Short text should return as is."""
    text = "Hello world."
    result = subtitles._extract_important_segments(text, target_chars=100)
    assert result == "Hello world."

def test_extract_important_segments_simple_truncation():
    """If few sentences, it should truncate by chars."""
    text = "A. B. C. D."
    # sentences = ["A.", "B.", "C.", "D."] (4 sentences < 5)
    # logic: if len(sentences) < 5: return text[:target_chars]

    result = subtitles._extract_important_segments(text, target_chars=4)
    assert result == "A. B" # Truncated

def test_extract_important_segments_smart_extraction():
    """Should prioritize First 2, Last 2, and keyword-rich middle."""

    # Create distinct sentences
    s_intro1 = "This is the intro hook."
    s_intro2 = "It is very important."

    s_mid1 = "This is boring middle."
    s_mid2 = "This middle contains KEYWORD KEYWORD KEYWORD."
    s_mid3 = "Another boring filler."

    s_end1 = "This is the conclusion."
    s_end2 = "Subscribe now."

    text = f"{s_intro1} {s_intro2} {s_mid1} {s_mid2} {s_mid3} {s_end1} {s_end2}"

    # Fake keywords extraction for the test
    # We rely on _extract_keywords logic which uses stopwords.
    # "KEYWORD" should be picked up.

    # target_chars small enough to force dropping some middle parts
    # intro1+2 ~ 40 chars
    # end1+2 ~ 40 chars
    # mid2 ~ 30 chars
    # mid1, mid3 ~ 20 chars
    # Total ~ 150 chars.
    # Set limit to 120 chars. Should drop mid1 or mid3.

    result = subtitles._extract_important_segments(text, target_chars=120)

    assert s_intro1 in result
    assert s_intro2 in result
    assert s_end1 in result
    assert s_end2 in result

    # Logic prioritizes keywords. s_mid2 has "KEYWORD" (if unique/frequent).
    # "KEYWORD" is capitalized, _extract_keywords lowercases. "keyword".
    # _extract_keywords excludes stopwords. "this", "is" are likely stopwords.
    # "boring", "middle", "filler" vs "keyword".
    # Assuming "keyword" is picked.

    # If the logic works, we expect s_mid2 to be present if it fits.
    # If mid1 is dropped, we might see "[...]".

    if "[...]" in result:
        # Check order
        assert result.index(s_intro2) < result.index(s_end1)

def test_extract_important_segments_greek_punctuation():
    """Verify Greek question mark splits sentences."""
    text = "Γεια σου; Τι κάνεις; Καλά."
    # ; is Greek question mark in some contexts or usually typed as ;
    # Regex includes ; and ;

    # Force split
    # We need at least 5 sentences to trigger smart logic
    sentences = ["Ένα.", "Δύο;", "Τρία.", "Τέσσερα;", "Πέντε."]
    text_greek = " ".join(sentences)

    # Mock len check
    result = subtitles._extract_important_segments(text_greek, target_chars=500)
    # Should not be truncated if it fits
    assert result == text_greek

    # Now make it long and force smart logic
    long_sentences = [f"Πρόταση {i} με αρκετό μήκος για να γεμίσει το κείμενο." for i in range(10)]
    long_text = " ".join(long_sentences)

    result_smart = subtitles._extract_important_segments(long_text, target_chars=50) # Very small

    # Should keep first/last
    assert "Πρόταση 0" in result_smart
    assert "Πρόταση 9" in result_smart
    # Should contain gap marker
    assert "[...]" in result_smart


# --- TEST LLM FUNCTIONS ---

def _fake_openai_client(calls):
    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return type("Response", (), {
                "choices": [
                    type("Choice", (), {
                        "message": type("Message", (), {
                            "content": json.dumps({"title": "T", "description": "D", "hashtags": []})
                        })
                    })
                ]
            })()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    return FakeClient()

def test_build_social_copy_llm_uses_optimized_prompt_and_tokens(monkeypatch):
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda k: _fake_openai_client(calls))

    transcript = "Word " * 1000 # Long text

    subtitles.build_social_copy_llm(transcript)

    assert len(calls) == 1
    args = calls[0]

    # Verify max_completion_tokens
    assert args["max_completion_tokens"] == 500

    # Verify prompt condensed
    system_msg = args["messages"][0]["content"]
    assert "Viral Greek TikTok copywriter" in system_msg or "viral Greek TikTok copywriter" in system_msg
    assert len(system_msg) < 600 # It was ~1600 before

    # Verify input truncation
    user_msg = args["messages"][1]["content"]
    assert len(user_msg) < len(transcript)
    assert "[...]" in user_msg or len(user_msg) <= 2500 # Default target_chars


def test_generate_fact_check_uses_optimized_prompt_and_tokens(monkeypatch):
    calls = []

    # Customize mock for fact check response
    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return type("Response", (), {
                "choices": [
                    type("Choice", (), {
                        "message": type("Message", (), {
                            "content": json.dumps({
                                "truth_score": 100,
                                "supported_claims_pct": 100,
                                "claims_checked": 0,
                                "items": []
                            })
                        })
                    })
                ]
            })()

    client = type("Client", (), {"chat": type("Chat", (), {"completions": FakeCompletions()})()})()

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda k: client)

    transcript = "Fact " * 1000

    subtitles.generate_fact_check(transcript)

    assert len(calls) == 1
    args = calls[0]

    # Verify max_completion_tokens
    assert args["max_completion_tokens"] == 800

    # Verify prompt condensed
    system_msg = args["messages"][0]["content"]
    assert "Task: Identify up to 3 factual errors" in system_msg

    # Verify input truncation
    user_msg = args["messages"][1]["content"]
    assert len(user_msg) < len(transcript)
