from backend.app.services.transcription.catalog import (
    find_transcription_engine,
    list_transcription_engines,
)


def test_caption_ready_catalog_prioritizes_zero_cost_mock_mode() -> None:
    engines = list_transcription_engines(caption_ready_only=True)

    assert [engine.id for engine in engines] == [
        "mock-studio",
        "groq-accurate",
        "groq-fast",
        "local-private",
    ]
    assert all(engine.supports_word_timestamps for engine in engines)
    assert all(engine.caption_ready for engine in engines)
    assert engines[0].recommended is True
    assert engines[0].model == "mock-caption-v1"
    assert engines[0].cost_usd_per_hour == 0.0


def test_catalog_keeps_text_only_and_diarization_models_out_of_caption_flow() -> None:
    engines = list_transcription_engines(caption_ready_only=False)
    precision = find_transcription_engine(engines, provider="openai", model="gpt-4o-transcribe")
    diarized = find_transcription_engine(
        engines,
        provider="openai",
        model="gpt-4o-transcribe-diarize",
    )

    assert precision is not None
    assert precision.caption_ready is False
    assert precision.supports_word_timestamps is False
    assert diarized is not None
    assert diarized.supports_diarization is True
    assert diarized.supports_word_timestamps is False
