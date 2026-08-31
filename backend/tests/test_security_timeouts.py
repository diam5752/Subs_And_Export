def test_openai_transcribe_timeout(monkeypatch, tmp_path):
    class MockTranscriptions:
        def create(self, *args, **kwargs):
            if "timeout" not in kwargs:
                raise AssertionError("Missing timeout argument in OpenAI transcription")
            assert kwargs["timeout"] >= 60.0
            return type("Resp", (), {"text": "", "segments": []})()

    class MockClient:
        class audio:
            transcriptions = MockTranscriptions()

    # Patch the function where it's used (public name now)
    monkeypatch.setattr(
        "backend.app.services.transcription.openai_cloud.load_openai_compatible_client",
        lambda k: MockClient(),
    )

    from backend.app.services.transcription.openai_cloud import OpenAITranscriber

    audio = tmp_path / "test.wav"
    audio.touch()

    OpenAITranscriber(api_key="k").transcribe(audio, tmp_path)


def test_groq_transcribe_timeout(monkeypatch, tmp_path):
    class MockTranscriptions:
        def create(self, *args, **kwargs):
            if "timeout" not in kwargs:
                raise AssertionError("Missing timeout argument in Groq transcription")
            assert kwargs["timeout"] >= 60.0
            return type("Resp", (), {"text": "", "segments": []})()

    class MockClient:
        def __init__(self, *args, **kwargs):
            pass

        class audio:
            transcriptions = MockTranscriptions()

    def mock_load(api_key, base_url=None, timeout=None):
        return MockClient()

    monkeypatch.setattr(
        "backend.app.services.transcription.groq_cloud.load_openai_compatible_client",
        mock_load,
    )

    from backend.app.services.transcription.groq_cloud import GroqTranscriber

    audio = tmp_path / "test.wav"
    audio.touch()

    GroqTranscriber(api_key="k").transcribe(audio, tmp_path)
