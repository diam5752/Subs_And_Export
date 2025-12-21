
from backend.app.services.llm_utils import load_openai_client


def test_load_openai_client_default_timeout(monkeypatch):
    """Verify that load_openai_client enforces a default timeout."""

    # Mock openai.OpenAI to capture arguments
    captured_kwargs = {}

    class MockOpenAI:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            self.timeout = kwargs.get("timeout")

    import openai
    monkeypatch.setattr(openai, "OpenAI", MockOpenAI)

    client = load_openai_client("test-key")

    assert captured_kwargs.get("timeout") == 60.0
    assert client.timeout == 60.0
