
import pytest
from backend.app.core.errors import sanitize_message

def test_sanitize_message_scrubs_api_keys():
    """Test that sanitize_message scrubs OpenAI/Groq API keys."""
    # Test cases with potential keys
    # Note: Keys must be at least 10 chars long (after prefix) to match the regex
    test_cases = [
        ("Error with key sk-proj-1234567890abcdef1234567890abcdef", "Error with key [API_KEY_REDACTED]"),
        ("sk-svc-abcdef1234567890abcdef12345678 failed", "[API_KEY_REDACTED] failed"),
        ("gsk_1234567890abcdef1234567890abcdef1234567890abcdef12 invalid", "[API_KEY_REDACTED] invalid"),
        # Updated test case to use keys long enough to trigger the regex
        ("Multiple keys sk-proj-1234567890 and sk-proj-0987654321", "Multiple keys [API_KEY_REDACTED] and [API_KEY_REDACTED]"),
        ("No keys here", "No keys here"),
        ("File path /var/www/html/app.py", "File path [INTERNAL_PATH]"),
        ("Mixed /var/log/syslog and sk-proj-1234567890", "Mixed [INTERNAL_PATH] and [API_KEY_REDACTED]"),
    ]

    for input_msg, expected_msg in test_cases:
        assert sanitize_message(input_msg) == expected_msg
