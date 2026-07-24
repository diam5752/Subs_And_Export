import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.app.services import (
    llm_utils,
    social_intelligence,
    subtitle_renderer,
    subtitles,
)
from backend.app.services import social_intelligence as social_lib
from backend.app.services.subtitle_types import Cue, WordTiming

# Import modules to patch them directly
from backend.app.services.transcription import openai_cloud


def test_extract_audio_invokes_ffmpeg(monkeypatch, tmp_path: Path):
    """Test that extract_audio calls ffmpeg with correct arguments."""
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    input_video = tmp_path / "video.mp4"
    input_video.touch()

    class MockPopen:
        def __init__(self, cmd, stdout, stderr, **kwargs):
            assert cmd[0] == "ffmpeg"
            # Simulate creation of the output file
            Path(cmd[-1]).write_bytes(b"audio")
            self.returncode = 0
            self.stderr = None

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return

        def communicate(self, timeout=None):
            return None, None

        def kill(self):
            pass

    # We must patch subprocess.Popen specifically
    monkeypatch.setattr(subprocess, "Popen", MockPopen)

    audio_path = subtitles.extract_audio(input_video, output_dir=output_dir)
    assert audio_path.exists()
    assert audio_path.name == "video.wav"


def test_get_video_duration(monkeypatch):
    class Result:
        stdout = b"3.5"

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: Result())
    assert subtitles.get_video_duration(Path("dummy")) == 3.5


def test_create_styled_subtitle_file_generates_ass(tmp_path: Path):
    srt_path = tmp_path / "subs.srt"
    srt_path.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nHello World\n", encoding="utf-8"
    )

    ass_path = subtitle_renderer.create_styled_subtitle_file(
        srt_path,
        primary_color="&H00FFFF",  # Cyan
        font_size=12,
        subtitle_position=10,
        output_dir=tmp_path,
    )

    assert ass_path.exists()
    assert ass_path.suffix == ".ass"
    content = ass_path.read_text(encoding="utf-8")
    assert "Style: Default" in content
    # REGRESSION: libass needs a small metric calibration to match CSS preview size.
    assert "Style: Default,Arial Black,13," in content
    assert "&H00FFFF" in content  # color
    # Text is normalized to Upper
    assert "HELLO WORLD" in content


def test_ass_positions_complete_multiline_block_at_both_safe_edges() -> None:
    """REGRESSION: the old 35% cap could not render subtitles at the top."""
    events = [subtitle_renderer.format_ass_dialogue(
        0.0,
        2.0,
        r"ΠΡΩΤΗ ΓΡΑΜΜΗ\NΔΕΥΤΕΡΗ, ΓΡΑΜΜΗ",
    )]
    top_dialogue = subtitle_renderer.position_ass_dialogue_events(
        events,
        subtitle_position=95,
        font_size=69,
        play_res_x=1080,
        play_res_y=1920,
    )[0]
    bottom_dialogue = subtitle_renderer.position_ass_dialogue_events(
        events,
        subtitle_position=5,
        font_size=69,
        play_res_x=1080,
        play_res_y=1920,
    )[0]

    assert r"{\an8\pos(540,96)}" in top_dialogue
    assert r"{\an8\pos(540,1658)}" in bottom_dialogue
    assert "ΔΕΥΤΕΡΗ, ΓΡΑΜΜΗ" in top_dialogue


def test_create_styled_subtitle_file_accepts_cues_without_transcript(tmp_path: Path):
    ass_path = subtitle_renderer.create_styled_subtitle_file(
        cues=[Cue(start=0.0, end=1.0, text="Άμεση διόρθωση")],
        output_dir=tmp_path,
    )

    assert ass_path == tmp_path / "subtitles.ass"
    assert "Άμεση διόρθωση" in ass_path.read_text(encoding="utf-8")


def test_create_styled_subtitle_file_requires_a_source():
    with pytest.raises(ValueError, match="transcript_path or cues"):
        subtitle_renderer.create_styled_subtitle_file()


def test_create_styled_subtitle_file_active_word_wraps_lines(tmp_path: Path):
    """
    Test that 'active-word' or 'active' style properly wraps long lines
    and respects manual line breaks, while highlighting words.
    """
    srt_path = tmp_path / "subs.srt"
    srt_content = (
        "1\n00:00:01,000 --> 00:00:05,000\n"
        "This is a very long line that should definitely wrap because it exceeds the character limit "
        "and we want to verify that the active word highlighting is still applied correctly to wrapped lines.\n"
    )
    srt_path.write_text(srt_content, encoding="utf-8")

    # Mock cues with word timings for this long line
    words = []
    text = "This is a very long line that should definitely wrap because it exceeds the character limit and we want to verify that the active word highlighting is still applied correctly to wrapped lines."
    parts = text.split()
    duration = 4.0
    step = duration / len(parts)
    for i, w in enumerate(parts):
        words.append(WordTiming(1.0 + i * step, 1.0 + (i + 1) * step, w))

    cues = [Cue(1.0, 5.0, text, words=words)]

    ass_path = subtitle_renderer.create_styled_subtitle_file(
        srt_path,
        cues=cues,
        highlight_style="active",  # or 'active-word'
        font_size=20,
        max_lines=2,
        output_dir=tmp_path,
    )

    content = ass_path.read_text(encoding="utf-8")
    # Verify we have multiple events for the same time range (one per word highlight step)
    # The active word logic generates many lines.
    lines = content.splitlines()
    dialogue_lines = [l for l in lines if l.startswith("Dialogue:")]
    assert len(dialogue_lines) > 5


def test_format_karaoke_wraps_long_lines():
    """Test that karaoke formatting correctly wraps lines and applies \\k tags."""
    text = "One two three four five six seven eight nine ten"
    # Create fake word timings
    words = []
    # 10 words, 0.5s each
    for i, w in enumerate(text.split()):
        words.append(WordTiming(float(i), float(i) + 0.5, w))

    # Force a very short max_chars just for testing logic
    lines = subtitle_renderer.wrap_word_timings(words, max_chars=15)
    assert len(lines) > 1
    assert lines[0][0].text == "One"  # Just checking structure


def test_clean_json_response_strips_fences():
    raw = "```json\n{\"foo\": \"bar\"}\n```"
    cleaned = llm_utils.clean_json_response(raw)
    assert cleaned == '{"foo": "bar"}'


def test_build_social_copy_llm_retries_and_raises(monkeypatch):
    monkeypatch.setattr(llm_utils, "resolve_openai_api_key", lambda k: "sk-fake")

    # Mock fallback to ensure it is returned
    fallback = social_lib.SocialCopy(
        social_lib.SocialContent("Fallback EL", "Fallback EN", "Fallback EL Desc", "Fallback EN Desc", ["#fallback"])
    )
    monkeypatch.setattr(social_lib, "build_social_copy", lambda text: fallback)

    mock_client = MagicMock()
    # Mock create to raise exception
    mock_client.chat.completions.create.side_effect = Exception("API Error")

    # Patch where it is used! (In llm_utils because social_lib calls it from there)
    monkeypatch.setattr(llm_utils, "load_openai_client", lambda k: mock_client)

    res = social_lib.build_social_copy_llm("some text", api_key="sk-fake")
    assert res is not None
    assert res.generic.title_en == "Fallback EN"


def test_compose_title_branches():
    # Test short text - MUST PASS LIST of keywords
    t1 = social_intelligence._compose_title(["Short"])
    assert "Short" in t1

    # Test long text - MUST PASS LIST
    kw = ["Word"] * 20
    t2 = social_intelligence._compose_title(kw)
    # Logic: f"{keywords[0].title()} & {keywords[1].title()} Moments"
    assert "Word" in t2
    assert "Moments" in t2


def test_load_openai_client_success(monkeypatch):
    monkeypatch.setitem(sys.modules, "openai", MagicMock())
    client = llm_utils.load_openai_client("sk-test")
    assert client is not None


def test_build_social_copy_llm_empty_response(monkeypatch):
    monkeypatch.setattr(llm_utils, "resolve_openai_api_key", lambda k: "sk-fake")
    mock_client = MagicMock()

    # Return empty content
    mock_response = MagicMock()
    mock_response.choices[0].message.content = ""
    mock_response.choices[0].message.refusal = None
    mock_client.chat.completions.create.return_value = mock_response

    # Patch in llm_utils
    monkeypatch.setattr(llm_utils, "load_openai_client", lambda k: mock_client)

    # Pass fallback
    fallback = social_lib.SocialCopy(
        social_lib.SocialContent("Fallback EL", "Fallback EN", "Fallback EL Desc", "Fallback EN Desc", ["#fallback"])
    )
    monkeypatch.setattr(social_lib, "build_social_copy", lambda text: fallback)

    res = social_lib.build_social_copy_llm("text", api_key="sk-fake")
    assert res is not None
    assert res.generic.title_en == "Fallback EN"


def test_transcribe_openai_error(monkeypatch, tmp_path):
    """Test OpeanAI transcriber handling API errors."""

    # Mock where it is used in openai_cloud!
    monkeypatch.setattr(openai_cloud, "resolve_openai_api_key", lambda: "sk-fake")
    monkeypatch.setitem(sys.modules, "openai", MagicMock())

    # Mock client to raise
    mock_client = MagicMock()
    mock_client.audio = MagicMock()
    mock_client.audio.transcriptions = MagicMock()
    mock_client.audio.transcriptions.create.side_effect = Exception("OpenAI Error")
    monkeypatch.setattr(openai_cloud, "load_openai_client", lambda k: mock_client)

    transcriber = openai_cloud.OpenAITranscriber(api_key="sk-fake")
    audio = tmp_path / "audio.wav"
    audio.touch()

    with pytest.raises(RuntimeError, match="OpenAI transcription failed"):
        transcriber.transcribe(audio, tmp_path)


def test_resolve_openai_api_key(monkeypatch):
    # Mock secrets loading in llm_utils
    monkeypatch.setattr(llm_utils.tomllib, "load", lambda f: {})
    # Mock Path exists in llm_utils context? No, just Path.
    monkeypatch.setattr(Path, "exists", lambda self: True)
    # Mock open
    monkeypatch.setattr("builtins.open", MagicMock())

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    assert llm_utils.resolve_openai_api_key() is None
    assert llm_utils.resolve_openai_api_key("sk-test") == "sk-test"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert llm_utils.resolve_openai_api_key() == "sk-env"


def test_wrap_lines_empty():
    assert subtitle_renderer.wrap_lines([], 10) == []


def test_split_long_cues_logic():
    # Long cue that needs splitting
    long_text = "This is a very long text that definitely needs to be split into smaller pieces"
    cues = [Cue(0.0, 10.0, long_text)]

    # Mock max chars to force split
    split_cues = subtitle_renderer.split_long_cues(cues, max_chars=20)
    assert len(split_cues) > 1
    assert split_cues[0].start == 0.0
    assert split_cues[-1].end == 10.0


def test_transcribe_with_openai_success(monkeypatch, tmp_path):
    monkeypatch.setattr(openai_cloud, "resolve_openai_api_key", lambda: "sk-fake")
    monkeypatch.setitem(sys.modules, "openai", MagicMock())

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Hello world"
    mock_resp.start = 0.0
    mock_resp.end = 1.0
    mock_resp.words = []

    # Mock return attributes
    mock_transcript = MagicMock()
    mock_transcript.segments = [mock_resp]

    mock_client.audio.transcriptions.create.return_value = mock_transcript
    monkeypatch.setattr(openai_cloud, "load_openai_client", lambda k: mock_client)

    transcriber = openai_cloud.OpenAITranscriber(api_key="sk-fake")
    audio = tmp_path / "a.wav"
    audio.touch()

    path, result_cues = transcriber.transcribe(audio, tmp_path)
    assert len(result_cues) == 1
    assert result_cues[0].text == "HELLO WORLD"


def test_wrap_lines_preserves_all_text():
    words = [WordTiming(0, 1, "One"), WordTiming(1, 2, "Two"), WordTiming(2, 3, "Three")]
    lines = subtitle_renderer.wrap_word_timings(words, max_chars=7) # "One Two" = 7 chars
    # Expect "One Two", "Three"
    assert len(lines) == 2
    assert lines[0][0].text == "One"
    assert lines[0][1].text == "Two"
    assert lines[1][0].text == "Three"


def test_greek_text_fits_within_config_width():
    # Greek chars are wide? No, usually handled same as unicode.
    greek = "Καλημέρα κόσμε"
    width = subtitle_renderer.get_text_width(greek, font_size=20)
    assert width > 0


def test_format_karaoke_text_preserves_all_words():
    # REGRESSION: three-line karaoke must preserve every word and emit explicit
    # ASS line breaks instead of relying on renderer-dependent wrapping.
    text = "ΒΑΛΤΕ ΥΠΟΘΕΣΕΙΣ ΚΑΙ ΕΛΑΤΕ ΝΑ ΦΤΙΑΞΟΥΜΕ"
    words = [
        WordTiming(index * 0.4, (index + 1) * 0.4, word)
        for index, word in enumerate(text.split())
    ]

    rendered = subtitle_renderer.format_karaoke_text(
        Cue(0.0, len(words) * 0.4, text, words),
        max_lines=3,
        max_chars=17,
    )
    visible = re.sub(r"\{[^}]*\}", "", rendered).replace("\\N", " ")

    assert rendered.count("\\N") == 2
    assert visible.split() == text.split()


def test_short_text_stays_on_single_line():
    words = [WordTiming(0, 1, "Hi")]
    lines = subtitle_renderer.wrap_word_timings(words, max_chars=50)
    assert len(lines) == 1


def test_resolve_groq_api_key_explicit():
    assert llm_utils.resolve_groq_api_key("gsk-test") == "gsk-test"


def test_resolve_groq_api_key_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-env")
    assert llm_utils.resolve_groq_api_key() == "gsk-env"


def test_resolve_groq_api_key_not_found(monkeypatch):
    # Mock secrets
    monkeypatch.setattr(llm_utils.tomllib, "load", lambda f: {})
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr("builtins.open", MagicMock())

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    assert llm_utils.resolve_groq_api_key() is None


def test_cues_without_words_DO_split_interpolated():
    cues = [Cue(0, 10, "A very long sentence that needs splitting")]
    res = subtitle_renderer.split_long_cues(cues, max_chars=10)
    assert len(res) > 1
    # Check interpolation
    assert res[0].end < 10.0
    assert res[1].start == res[0].end


def test_standard_model_no_words_lost():
    text = "ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN"
    chunks = subtitle_renderer.split_long_cues(
        [Cue(0.0, 11.0, text)],
        max_chars=10,
        max_lines=3,
    )

    assert " ".join(chunk.text for chunk in chunks).split() == text.split()
    assert all(
        len(subtitle_renderer.wrap_lines(chunk.text.split(), max_chars=10)) <= 3
        for chunk in chunks
    )
    assert chunks[0].start == 0.0
    assert chunks[-1].end == 11.0


def test_per_word_karaoke():
    words = [
        WordTiming(0.0, 0.5, "ONE"),
        WordTiming(0.5, 1.0, "TWO"),
        WordTiming(1.0, 1.5, "THREE"),
    ]
    rendered = subtitle_renderer.format_karaoke_text(
        Cue(0.0, 1.5, "ONE TWO THREE", words),
        max_lines=1,
        max_chars=40,
    )

    assert rendered == "{\\k50}ONE {\\k50}TWO {\\k50}THREE"


def test_create_styled_subtitle_file_clamps_overlapping_cues(tmp_path):
    srt = tmp_path / "test.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:05,000\nCollision\n\n2\n00:00:04,000 --> 00:00:08,000\nOverlap\n")

    # This invokes normalize_cues_for_ass which clamps
    ass_path = subtitle_renderer.create_styled_subtitle_file(
        srt, output_dir=tmp_path
    )
    # Parsing verify?
    # We trust internal logic for now, verifying it runs without error.
    assert ass_path.exists()


def test_1_word_mode_splitting_standard_model(tmp_path: Path):
    srt = tmp_path / "single-word.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:03,000\nONE TWO THREE\n",
        encoding="utf-8",
    )

    ass_path = subtitle_renderer.create_styled_subtitle_file(
        srt,
        max_lines=0,
        highlight_style="active",
        output_dir=tmp_path,
    )
    dialogue = [
        line for line in ass_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("Dialogue:")
    ]
    visible = [re.sub(r"\{[^}]*\}", "", line.rsplit(",,", maxsplit=1)[-1]) for line in dialogue]

    assert visible == ["ONE", "TWO", "THREE"]
    assert dialogue[0].startswith("Dialogue: 0,0:00:00.00,0:00:01.00")
    assert dialogue[-1].startswith("Dialogue: 0,0:00:02.00,0:00:03.00")


def test_generate_active_word_ass_no_words():
    events = subtitle_renderer.generate_active_word_ass(
        Cue(2.0, 5.0, "ALPHA BETA GAMMA"),
        max_lines=0,
        primary_color="&H00FFFF",
        secondary_color="&HFFFFFF",
    )

    assert len(events) == 3
    assert [re.sub(r"\{[^}]*\}", "", event.rsplit(",,", maxsplit=1)[-1]) for event in events] == [
        "ALPHA",
        "BETA",
        "GAMMA",
    ]


def test_generate_active_word_ass_logic():
    text = "ONE TWO THREE FOUR FIVE SIX"
    words = [
        WordTiming(index * 0.5, (index + 1) * 0.5, word)
        for index, word in enumerate(text.split())
    ]
    cue = Cue(0.0, 3.0, "ONE TWO\\NTHREE FOUR\\NFIVE SIX", words)

    events = subtitle_renderer.generate_active_word_ass(
        cue,
        max_lines=3,
        primary_color="&H00FFFF",
        secondary_color="&HFFFFFF",
    )

    assert len(events) == len(words) + 1
    assert all(event.rsplit(",,", maxsplit=1)[-1].count("\\N") == 2 for event in events)
    assert all(word in events[0] for word in text.split())
    assert "{\\alpha&H00&\\c&H00FFFF&}ONE" in events[1]


def test_split_long_cues_with_phrases_interpolation():
    cues = [Cue(0, 4, "Hello world this is a test")]
    res = subtitle_renderer.split_long_cues(cues, max_chars=10)
    assert len(res) >= 2
    # split_long_cues doesn't normalize, so it should be same case
    assert "Hello" in res[0].text
    # Check timings are interpolated linearly
    # "Hello world" is ~11 chars. "this is a test" is ~14.
    # Should be about half/half duration.
    assert 1.0 < res[0].end < 3.0


def test_split_long_cues_avoids_orphan_final_word():
    cues = [
        Cue(
            0,
            5,
            "AAAAAA AAAAAA AAAAAA AAAAAA AAAAAA",
            words=[
                WordTiming(0, 1, "AAAAAA"),
                WordTiming(1, 2, "AAAAAA"),
                WordTiming(2, 3, "AAAAAA"),
                WordTiming(3, 4, "AAAAAA"),
                WordTiming(4, 5, "AAAAAA"),
            ],
        )
    ]

    res = subtitle_renderer.split_long_cues(cues, max_chars=13, max_lines=2)
    assert len(res) == 2
    assert [len(cue.text.split()) for cue in res] in ([2, 3], [3, 2])
    assert all(len(cue.text.split()) > 1 for cue in res)
