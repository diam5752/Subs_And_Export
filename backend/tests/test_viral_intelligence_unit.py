import json
from unittest.mock import MagicMock, patch

import pytest

from backend.app.services.subtitles import ViralMetadata, generate_viral_metadata


@patch("backend.app.services.subtitles._load_openai_client")
def test_generate_viral_metadata_success(mock_load_client):
    # Mock OpenAI client response
    mock_client = MagicMock()
    mock_choice = MagicMock()

    expected_response = {
        "hooks": ["Hook 1", "Hook 2", "Hook 3"],
        "caption_hook": "Caption Hook",
        "caption_body": "Body content",
        "cta": "Click here",
        "hashtags": ["#greek", "#viral"]
    }

    mock_choice.message.content = json.dumps(expected_response)
    mock_client.chat.completions.create.return_value.choices = [mock_choice]
    mock_load_client.return_value = mock_client

    # Run function
    result = generate_viral_metadata("Sample transcript text", api_key="fake-key")

    # Verify
    assert isinstance(result, ViralMetadata)
    assert result.hooks == expected_response["hooks"]
    assert result.caption_hook == expected_response["caption_hook"]
    assert result.hashtags == expected_response["hashtags"]

    # Verify prompt structure (partial check)
    call_args = mock_client.chat.completions.create.call_args
    assert call_args is not None
    messages = call_args.kwargs['messages']
    assert len(messages) == 2
    assert "Sample transcript text" in messages[1]['content']
    assert "Greek Social Media Manager" in messages[0]['content']

@patch("backend.app.services.subtitles._load_openai_client")
def test_generate_viral_metadata_retry_success(mock_load_client):
    """Test that it retries on invalid JSON"""
    mock_client = MagicMock()

    bad_choice = MagicMock()
    bad_choice.message.content = "Not JSON"

    good_choice = MagicMock()
    expected_response = {
        "hooks": ["H1"], "caption_hook": "C1", "caption_body": "B1", "cta": "CTA", "hashtags": ["#h"]
    }
    good_choice.message.content = json.dumps(expected_response)

    # First call returns bad, second returns good
    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[bad_choice]),
        MagicMock(choices=[good_choice])
    ]
    mock_load_client.return_value = mock_client

    result = generate_viral_metadata("test", api_key="fake")
    assert result.hooks == ["H1"]

@patch("backend.app.services.subtitles._load_openai_client")
def test_generate_viral_metadata_failure(mock_load_client):
    """Test that it raises ValueError after retries"""
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = ValueError("API Error")
    mock_load_client.return_value = mock_client

    with pytest.raises(ValueError, match="Failed to generate viral metadata"):
        generate_viral_metadata("test", api_key="fake")
