from backend.app.services.subtitles import _write_srt_from_segments


def test_srt_injection_sanitization(tmp_path):
    """
    Test that newlines in cue text are sanitized to prevent SRT format injection.
    Double newlines in SRT typically indicate the end of a cue block.
    """
    dest = tmp_path / "test.srt"

    # Payload attempting to inject a fake cue
    injection_payload = "Legit text\n\n999\n00:00:05,000 --> 00:00:06,000\nINJECTED CUE"

    segments = [
        (1.0, 4.0, injection_payload)
    ]

    _write_srt_from_segments(segments, dest)

    content = dest.read_text(encoding="utf-8")

    # Split by blank lines (standard SRT delimiter)
    blocks = [b for b in content.strip().split("\n\n") if b.strip()]

    # Expected: 1 block containing the sanitized text
    assert len(blocks) == 1, f"SRT injection successful: found {len(blocks)} blocks"

    # Verify the double newline was collapsed
    # Note: different operating systems might handle newlines differently, but our regex handles \r\n
    assert "Legit text\n999" in content.replace("\r\n", "\n")
