import pytest
from pydantic import ValidationError

from backend.app.api.endpoints.videos import (
    TranscriptionCueRequest,
    TranscriptionWordRequest,
    UpdateTranscriptionRequest,
)


def test_transcription_request_cues_limit():
    """
    Verify that UpdateTranscriptionRequest enforces a limit on the number of cues.
    """
    # 1. Valid request (limit is 5000)
    # Using a smaller number for speed, then manually triggering validation on a larger one if needed,
    # but constructing 5000 items is fast enough in Python.
    limit = 5000
    valid_cues = [
        TranscriptionCueRequest(start=0.0, end=1.0, text=f"cue {i}")
        for i in range(10) # Minimal valid
    ]
    req = UpdateTranscriptionRequest(cues=valid_cues)
    assert len(req.cues) == 10

    # 2. Invalid request (exceeds limit)
    # We cheat a bit to avoid constructing 5001 objects if we can, but Pydantic validates on init.
    # So we must construct them.

    # Let's test boundary around 5000
    # To keep test fast, we might want to assume the field definition is correct,
    # but here we want to verify the model enforces it.

    over_limit_cues = [
        TranscriptionCueRequest(start=0.0, end=1.0, text="cue")
        for _ in range(5001)
    ]

    with pytest.raises(ValidationError) as excinfo:
        UpdateTranscriptionRequest(cues=over_limit_cues)

    # Pydantic error message for max_length
    assert "at most 5000 items" in str(excinfo.value) or "max_length" in str(excinfo.value)

def test_transcription_cue_words_limit():
    """
    Verify that TranscriptionCueRequest enforces a limit on the number of words per cue.
    """
    limit = 100

    # 1. Valid
    valid_words = [
        TranscriptionWordRequest(start=0.0, end=0.1, text="word")
        for _ in range(limit)
    ]
    cue = TranscriptionCueRequest(
        start=0.0, end=1.0, text="text", words=valid_words
    )
    assert len(cue.words) == limit

    # 2. Invalid
    invalid_words = valid_words + [TranscriptionWordRequest(start=0.0, end=0.1, text="overflow")]

    with pytest.raises(ValidationError) as excinfo:
        TranscriptionCueRequest(
            start=0.0, end=1.0, text="text", words=invalid_words
        )

    assert "at most 100 items" in str(excinfo.value) or "max_length" in str(excinfo.value)
