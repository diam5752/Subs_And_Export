"""Tests for the provider-free CLI social-copy helper."""

from backend.app.services import social_intelligence


def test_build_social_copy_returns_deterministic_strings() -> None:
    transcript = "Coding tips coding flow python python testing coffee rituals for focus."

    social = social_intelligence.build_social_copy(transcript)

    assert social.generic.title_en.startswith("Coding & Python")
    assert "#coding" in social.generic.hashtags
    assert "#python" in social.generic.hashtags
    assert "#trending" in social.generic.hashtags
    assert "Coding tips" in social.generic.description_en
    assert "#viral" in social.generic.description_en


def test_build_social_copy_handles_empty_transcript_without_provider_call() -> None:
    social = social_intelligence.build_social_copy("")

    assert social.generic.title_el == "Greek Highlights"
    assert social.generic.description_el.startswith("#greek")
