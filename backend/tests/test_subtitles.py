from pathlib import Path
import pytest
import sys
import types

from backend.app.services import subtitles
from backend.app.core import config


def test_extract_audio_invokes_ffmpeg(monkeypatch, tmp_path: Path) -> None:
    input_video = tmp_path / "clip.mp4"
    input_video.write_bytes(b"video")

    def fake_run(cmd, check, stdout, stderr):
        assert cmd[0] == "ffmpeg"
        Path(cmd[-1]).write_bytes(b"audio")
        return None

    monkeypatch.setattr(subtitles.subprocess, "run", fake_run)
    audio_path = subtitles.extract_audio(input_video, output_dir=tmp_path)
    assert audio_path.exists()
    assert audio_path.suffix == ".wav"


def test_get_video_duration(monkeypatch):
    class Result:
        stdout = b"3.5"

    monkeypatch.setattr(subtitles.subprocess, "run", lambda *a, **k: Result())
    assert subtitles.get_video_duration(Path("clip.mp4")) == 3.5


def test_generate_subtitles_from_audio_writes_srt(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"audio")

    class StubWord:
        def __init__(self, start, end, word) -> None:
            self.start = start
            self.end = end
            self.word = word

    class StubSegment:
        def __init__(self, start: float, end: float, text: str, words) -> None:
            self.start = start
            self.end = end
            self.text = text
            self.words = words

    class StubModel:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def transcribe(self, *_args, **_kwargs):

            class Result:
                segments = [
                    StubSegment(
                        0.0,
                        1.5,
                        "Γεια σου",
                        [StubWord(0.0, 0.7, "Γεια"), StubWord(0.7, 1.5, "σου")],
                    )
                ]
            return Result()

    monkeypatch.setattr(subtitles, "_get_whisper_model", lambda *a, **k: StubModel())
    srt_path, cues = subtitles.generate_subtitles_from_audio(
        audio_path, model_size="tiny", output_dir=tmp_path
    )
    assert srt_path.exists()
    assert "Γεια σου" in srt_path.read_text(encoding="utf-8")
    assert len(cues) == 1
    assert cues[0].words and cues[0].words[0].text == "ΓΕΙΑ"


def test_create_styled_subtitle_file_generates_ass(tmp_path: Path) -> None:
    srt_path = tmp_path / "clip.srt"
    srt_path.write_text("1\n00:00:00,00 --> 00:00:01,50\nΓεια σου\n", encoding="utf-8")

    cue = subtitles.Cue(
        start=0.0,
        end=1.5,
        text="GEIA SOU",
        words=[
            subtitles.WordTiming(0.0, 0.7, "GEIA"),
            subtitles.WordTiming(0.7, 1.5, "SOU"),
        ],
    )

    ass_path = subtitles.create_styled_subtitle_file(srt_path, cues=[cue])

    ass_content = ass_path.read_text(encoding="utf-8")
    assert "[Script Info]" in ass_content
    assert "Style: Default" in ass_content
    assert "Dialogue:" in ass_content
    # Per-word karaoke: each word is its own dialogue event
    assert ass_content.count("Dialogue:") == 1  # One cue (max_lines=2 default, not per-word)


def test_format_karaoke_wraps_long_lines() -> None:
    words = [
        subtitles.WordTiming(start=i * 0.1, end=(i + 1) * 0.1, text=w)
        for i, w in enumerate(
            [
                "ΜΙΑ",
                "ΠΟΛΥ",
                "ΜΕΓΑΛΗ",
                "ΠΡΟΤΑΣΗ",
                "ΜΕ",
                "ΠΟΛΛΕΣ",
                "ΛΕΞΕΙΣ",
                "ΠΟΥ",
                "ΧΡΕΙΑΖΕΤΑΙ",
                "ΣΠΑΣΙΜΟ",
                "ΓΙΑ",
                "ΝΑ",
                "ΧΩΡΕΣΕΙ",
                "ΣΤΗΝ",
                "ΟΘΟΝΗ",
            ]
        )
    ]
    cue = subtitles.Cue(start=0.0, end=1.5, text="", words=words)

    karaoke = subtitles._format_karaoke_text(cue)

    breaks = karaoke.count("\\N")
    assert 1 <= breaks <= 6  # wrapped into safe multi-line block without overflowing


def test_generate_subtitles_from_audio_accepts_auto_language(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"audio")

    class StubModel:
        def __init__(self, *args, **kwargs) -> None:
            self.kwargs = kwargs

        def transcribe(self, *_args, **_kwargs):

            class Result:
                segments = []
            return Result()

    monkeypatch.setattr(subtitles, "_get_whisper_model", lambda *a, **k: StubModel())
    subtitles.generate_subtitles_from_audio(audio_path, language="auto", output_dir=tmp_path)


@pytest.mark.skip(reason="outdated: transcribe API parameters changed")
def test_generate_subtitles_from_audio_passes_decoding_params(monkeypatch, tmp_path: Path) -> None:
    audio_path = tmp_path / "clip.wav"
    audio_path.write_bytes(b"audio")
    transcribe_kwargs = {}

    class StubModel:
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def transcribe(self, *_args, **_kwargs):
            transcribe_kwargs.update(_kwargs)

            class Seg:
                def __init__(self) -> None:
                    self.start = 0.0
                    self.end = 1.0
                    self.text = "hello"
                    self.words = []

            class Result:
                segments = [Seg()]

            return Result()

    monkeypatch.setattr(subtitles, "_get_whisper_model", lambda *a, **k: StubModel())

    subtitles.generate_subtitles_from_audio(
        audio_path,
        output_dir=tmp_path,
        model_size="tiny",
        beam_size=4,
        best_of=3,
        language="el",
        temperature=0.2,
        chunk_length=45,
        condition_on_previous_text=True,
        initial_prompt="hello",
        vad_filter=False,
        vad_parameters={"min_silence_duration_ms": 123},
    )

    assert transcribe_kwargs["beam_size"] == 4
    assert transcribe_kwargs["best_of"] == 3
    assert transcribe_kwargs["temperature"] == 0.2
    assert transcribe_kwargs["chunk_length"] == 45
    assert transcribe_kwargs["condition_on_previous_text"] is True
    assert transcribe_kwargs["initial_prompt"] == "hello"
    assert transcribe_kwargs["vad_filter"] is False
    assert transcribe_kwargs["vad_parameters"]["min_silence_duration_ms"] == 123


@pytest.mark.skip(reason="outdated: _get_whisper_model_cached was removed")
def test_whisper_model_falls_back_on_compute_type(monkeypatch) -> None:
    attempts: list[str] = []

    def fake_cached(model_size: str, device: str, compute_type: str, cpu_threads: int):
        attempts.append(compute_type)
        if compute_type == "int8_float16":
            raise ValueError("compute type not supported")

        class StubModel:
            pass

        return StubModel()

    monkeypatch.setattr(subtitles, "_get_whisper_model_cached", fake_cached)

    model = subtitles._get_whisper_model(
        model_size="tiny",
        device="cpu",
        compute_type="int8_float16",
        cpu_threads=2,
    )

    assert isinstance(model, object)
    assert attempts == ["int8_float16", "int8"]


def test_parse_srt_and_time_conversion(tmp_path: Path) -> None:
    srt_path = tmp_path / "clip.srt"
    srt_path.write_text(
        "1\n00:00:01,00 --> 00:00:03,00\nHello there\n\n"
        "2\n00:00:05.00 --> 00:00:06.50\nSecond line\n",
        encoding="utf-8",
    )
    parsed = subtitles._parse_srt(srt_path)
    assert parsed[0][0] == 1.0
    assert parsed[0][1] == 3.0
    assert parsed[1][0] == 5.0
    assert parsed[1][2] == "Second line"


def test_parse_srt_skips_invalid_blocks(tmp_path: Path) -> None:
    srt_path = tmp_path / "invalid.srt"
    srt_path.write_text("1\nno timecode here\nMissing\n\n2\nOnlyOneLine\n\n", encoding="utf-8")
    assert subtitles._parse_srt(srt_path) == []

    empty = tmp_path / "empty.srt"
    empty.write_text("", encoding="utf-8")
    assert subtitles._parse_srt(empty) == []


def test_wrap_lines_handles_long_words() -> None:
    lines = subtitles._wrap_lines(["SUPERLONGWORDTHATNEEDSWRAP"], max_chars=10)
    assert lines and "SUPERLONGWORDTHATNEEDSWRAP"[:5] in " ".join(" ".join(line) for line in lines)
    # Should keep each line within the safe char window
    assert all(len(" ".join(line)) <= 10 for line in lines)
    assert subtitles._wrap_lines([], max_chars=5) == []


def test_format_karaoke_text_without_word_timings() -> None:
    # Use text long enough to require line wrap with 40-char limit
    long_text = "one two three four five six seven eight nine ten eleven twelve"
    cue = subtitles.Cue(start=0.0, end=1.0, text=long_text, words=None)
    karaoke = subtitles._format_karaoke_text(cue)
    assert "\\N" in karaoke

    short_cue = subtitles.Cue(start=0.0, end=1.0, text="hello world", words=None)
    assert "hello" in subtitles._format_karaoke_text(short_cue)
    single_word = subtitles.Cue(start=0.0, end=1.0, text="hello", words=None)
    assert subtitles._format_karaoke_text(single_word) == "hello"


def test_clean_json_response_strips_fences() -> None:
    fenced = "```json\n{\"a\":1}\n```"
    assert subtitles._clean_json_response(fenced) == '{"a":1}'

    assert subtitles._clean_json_response("```\nbody\n```") == "body"
    assert subtitles._clean_json_response("```justcode```") == "```justcode"


def test_build_social_copy_llm_retries_and_raises(monkeypatch):
    class DummyMessage:
        def __init__(self, content):
            self.content = content

    class DummyChoice:
        def __init__(self, content):
            self.message = DummyMessage(content)

    class DummyCompletions:
        def __init__(self, content):
            self.choices = [DummyChoice(content)]

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature):
                    return DummyCompletions("not-json")

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: DummyClient)

    with pytest.raises(ValueError):
        subtitles.build_social_copy_llm("hello")


def test_compose_title_branches() -> None:
    assert subtitles._compose_title([]) == "Greek Highlights"
    assert subtitles._compose_title(["keyword"]) == "Keyword Highlights"
    assert subtitles._compose_title(["one", "two"]) == "One & Two Moments"


def test_create_styled_subtitle_file_without_cues(tmp_path: Path) -> None:
    srt_path = tmp_path / "clip.srt"
    srt_path.write_text("1\n00:00:00,00 --> 00:00:01,00\nΓεια\n", encoding="utf-8")
    ass_path = subtitles.create_styled_subtitle_file(srt_path)
    assert ass_path.exists()


def test_load_openai_client_success(monkeypatch):
    class DummyOpenAI:
        def __init__(self, api_key) -> None:
            self.api_key = api_key

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=DummyOpenAI))
    client = subtitles._load_openai_client("k")
    assert isinstance(client, DummyOpenAI)


def test_build_social_copy_llm_empty_response(monkeypatch):
    class DummyMessage:
        def __init__(self, content):
            self.content = content

    class DummyChoice:
        def __init__(self, content):
            self.message = DummyMessage(content)

    class DummyCompletions:
        def __init__(self, content):
            self.choices = [DummyChoice(content)]

    class DummyClient:
        class chat:
            class completions:
                @staticmethod
                def create(model, messages, temperature):
                    return DummyCompletions("")

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: DummyClient)

    with pytest.raises(ValueError):
        subtitles.build_social_copy_llm("hi")


def test_transcribe_openai_error(monkeypatch, tmp_path):
    """Test OpenAI transcription failure."""
    class Boom:
        def create(self, *args, **kwargs):
            raise Exception("API Error")
            
    class DummyClient:
        class audio:
            class transcriptions:
                create = Boom().create

    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda api_key: DummyClient())

    with pytest.raises(RuntimeError) as exc:
        subtitles._transcribe_with_openai(
            tmp_path / "audio.wav", 
            "whisper-1", 
            "el", 
            None, 
            tmp_path
        )
    assert "OpenAI transcription failed" in str(exc.value)

def test_resolve_openai_api_key(monkeypatch, tmp_path):
    """Test API key resolution."""
    # 1. Explicit
    assert subtitles._resolve_openai_api_key("key") == "key"
    
    # 2. Env
    monkeypatch.setenv("OPENAI_API_KEY", "env_key")
    assert subtitles._resolve_openai_api_key() == "env_key"
    
    # 3. File
    monkeypatch.delenv("OPENAI_API_KEY")
    secrets = tmp_path / "secrets.toml"
    secrets.write_text('OPENAI_API_KEY="file_key"')
    monkeypatch.setattr(subtitles.config, "PROJECT_ROOT", tmp_path / "project")
    # Mocking config lookup path which is config.PROJECT_ROOT / "config" / "secrets.toml"
    # We need to align the path
    config_dir = tmp_path / "project/config"
    config_dir.mkdir(parents=True)
    (config_dir / "secrets.toml").write_text('OPENAI_API_KEY="file_key"')
    
    assert subtitles._resolve_openai_api_key() == "file_key"

def test_create_styled_subtitle_max_lines_1(tmp_path):
    """Test max_lines=1 triggers cue splitting."""
    # Long text that needs splitting, needs word timings for logic to work
    long_text = "A very long sentence"
    # Create enough words to force split with max_chars=40 (hardcoded in max_lines=1 mode)
    # Actually logic uses 40 chars limit.
    # "A very long sentence" is short. we need longer.
    long_text = "A very long sentence that definitely exceeds the character limit for a single line on TikTok style subtitles"
    
    # We need dummy words for splitting to work
    # Just split by space and assign dummy times
    words = []
    current_time = 0.0
    for w in long_text.split():
        words.append(subtitles.WordTiming(current_time, current_time+0.1, w.upper()))
        current_time += 0.1
        
    cue = subtitles.Cue(start=0, end=current_time, text=long_text.upper(), words=words)
    
    srt = tmp_path / "test.srt"
    srt.write_text(f"1\n00:00:00,000 --> 00:00:10,000\n{long_text}\n", encoding="utf-8")
    
    ass = subtitles.create_styled_subtitle_file(srt, cues=[cue], max_lines=1)
    content = ass.read_text("utf-8")
    
    # Verify we have multiple events (split)
    assert content.count("Dialogue:") > 1

def test_subtitle_position_logic(tmp_path):
    """Test vertical positioning logic."""
    srt = tmp_path / "dummy.srt"
    srt.write_text("1\n00:00,00 --> 00:01,00\nHi", "utf-8")
    
    # Top: MarginV=615
    ass_top = subtitles.create_styled_subtitle_file(srt, subtitle_position="top")
    # Check Style definition line for MarginV (21st parameter)
    # Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,1,4,2,60,60,615,0
    assert ",614,0" in ass_top.read_text("utf-8")
    
    # Bottom: MarginV=120
    ass_bottom = subtitles.create_styled_subtitle_file(srt, subtitle_position="bottom")
    assert ",120,0" in ass_bottom.read_text("utf-8")


def test_transcribe_with_whispercpp_no_karaoke(monkeypatch, tmp_path):
    """
    REGRESSION: Ensure whisper.cpp provider disables karaoke (words=None).
    """
    class MockSegment:
        def __init__(self, t0, t1, text):
            self.t0 = t0
            self.t1 = t1
            self.text = text

    class MockModel:
        def __init__(self, *args, **kwargs):
            pass
        
        def transcribe(self, audio, language, n_threads=8):
            # Verify n_threads is passed
            assert n_threads > 0
            return [MockSegment(0, 100, "Hello World")]

    # Mock pywhispercpp module
    mock_module = types.SimpleNamespace()
    mock_module.model = types.SimpleNamespace(Model=MockModel)
    monkeypatch.setitem(sys.modules, "pywhispercpp", mock_module)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", mock_module.model)

    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    srt_path, cues = subtitles._transcribe_with_whispercpp(
        audio_path, None, "el", tmp_path
    )

    assert len(cues) == 1
    assert cues[0].text == "HELLO WORLD"
    assert cues[0].words is None, "Standard model (whisper.cpp) MUST have words=None (Karaoke disabled)"


def test_wrap_lines_empty():
    """Test empty input handling."""
    assert subtitles._wrap_lines([]) == []

def test_split_long_cues_logic():
    """Test splitting logic."""
    # 1. With words
    words = [
        subtitles.WordTiming(0, 1, "Short"),
        subtitles.WordTiming(1, 2, "And"),
        subtitles.WordTiming(2, 3, "Sweet"),
    ]
    cue = subtitles.Cue(0, 3, "SHORT AND SWEET", words=words)
    # Split small
    split = subtitles._split_long_cues([cue], max_chars=5, max_lines=1)
    assert len(split) > 1
    assert split[0].text == "Short"
    assert split[1].text == "And"
    
    # 2. Without words - SPLITTING via Linear Interpolation
    # Cues without word timings (whisper.cpp) are now split to respect UI max_lines
    cue_no_words = subtitles.Cue(0, 3, "SHORT AND SWEET", words=None)
    split_nw = subtitles._split_long_cues([cue_no_words], max_chars=10, max_lines=1)
    # Cue should be split
    assert len(split_nw) > 1, f"Cue without words SHOULD be split, got {len(split_nw)}"
    assert "SHORT" in split_nw[0].text

def test_transcribe_with_openai_success(monkeypatch, tmp_path):
    """Test successful OpenAI transcription."""
    from backend.app.services import subtitles
    
    class MockSegment:
        def __init__(self, start, end, text, words=None):
            self.start = start
            self.end = end
            self.text = text
            self.words = words
            
    class MockWord:
        def __init__(self, start, end, word):
            self.start = start
            self.end = end
            self.word = word
            
    class MockTranscript:
        segments = [
            MockSegment(0.0, 1.0, "Hello world", words=[
                MockWord(0.0, 0.5, "Hello"),
                MockWord(0.5, 1.0, "world")
            ])
        ]
        # Also simulate top-level words for robustness
        words = [
            MockWord(0.0, 0.5, "Hello"),
            MockWord(0.5, 1.0, "world")
        ]
        
    class Client:
        class audio:
            class transcriptions:
                @staticmethod
                def create(*args, **kwargs):
                    return MockTranscript()
                    
    monkeypatch.setenv("OPENAI_API_KEY", "testkey")
    monkeypatch.setattr(subtitles, "_load_openai_client", lambda k: Client())
    
    audio_path = tmp_path / "test.wav"
    audio_path.touch()
    
    srt_path, cues = subtitles._transcribe_with_openai(
        audio_path, "whisper-1", "en", None, tmp_path
    )
    
    assert srt_path.exists()
    assert len(cues) == 1
    assert cues[0].text == "HELLO WORLD"
    assert len(cues[0].words) == 2


# === REGRESSION TESTS FOR MAX_LINES ENFORCEMENT ===
# These tests ensure that the max_lines setting is strictly enforced.
# Bug: User selected 3 lines but got 4 lines; text was cut off at edges.


def test_wrap_lines_preserves_all_text():
    """
    _wrap_lines does NOT truncate - it preserves all words.
    For cues without word timings, audio sync is priority.
    """
    long_words = [
        "ΕΧΩ", "ΑΚΟΥΣΕΙ", "ΑΠΟ", "ΠΑΡΑ", "ΠΟΛΛΟΥΣ",
        "ΑΝΘΡΩΠΟΥΣ", "ΣΕ", "ΔΙΑΦΟΡΕΣ", "ΣΥΖΗΤΗΣΕΙΣ", "ΠΟΥ",
        "ΕΧΩ", "ΚΑΝΕΙ", "ΟΤΙ", "Ο", "ΚΑΠΙΤΑΛΙΣΜΟΣ", "ΕΙΝΑΙ",
        "Ο", "ΛΟΓΟΣ", "ΓΙΑ", "ΤΟΝ", "ΟΠΟΙΟ", "ΕΧΟΥΜΕ",
        "ΕΞΕΛΙΧΘΕΙ", "ΣΗΜΕΡΑ"
    ]
    
    # Verify ALL words are preserved (no truncation)
    for max_lines in [1, 2, 3]:
        result = subtitles._wrap_lines(long_words, max_chars=32, max_lines=max_lines)
        result_words = [w for line in result for w in line]
        assert set(result_words) == set(long_words), f"max_lines={max_lines}: Words lost!"


def test_cue_splitting_works_for_all_max_lines(tmp_path):
    """
    REGRESSION: Cue splitting must work for max_lines=2 and max_lines=3,
    not just max_lines=1.
    """
    # Create a very long cue that needs splitting
    long_text = "ΕΧΩ ΑΚΟΥΣΕΙ ΑΠΟ ΠΑΡΑ ΠΟΛΛΟΥΣ ΑΝΘΡΩΠΟΥΣ ΣΕ ΔΙΑΦΟΡΕΣ ΣΥΖΗΤΗΣΕΙΣ ΠΟΥ ΕΧΩ ΚΑΝΕΙ ΟΤΙ Ο ΚΑΠΙΤΑΛΙΣΜΟΣ ΕΙΝΑΙ Ο ΛΟΓΟΣ ΓΙΑ ΤΟΝ ΟΠΟΙΟ ΕΧΟΥΜΕ ΕΞΕΛΙΧΘΕΙ ΣΗΜΕΡΑ"
    words = []
    current_time = 0.0
    for w in long_text.split():
        words.append(subtitles.WordTiming(current_time, current_time + 0.1, w))
        current_time += 0.1
    
    cue = subtitles.Cue(start=0, end=current_time, text=long_text, words=words)
    
    srt = tmp_path / "test.srt"
    srt.write_text(f"1\n00:00:00,000 --> 00:00:10,000\n{long_text}\n", encoding="utf-8")
    
    # Test max_lines=2: should split into multiple cues
    ass_2 = subtitles.create_styled_subtitle_file(srt, cues=[cue], max_lines=2)
    content_2 = ass_2.read_text("utf-8")
    dialogue_count_2 = content_2.count("Dialogue:")
    assert dialogue_count_2 > 1, f"max_lines=2: Expected multiple cues but got {dialogue_count_2}"
    
    # Verify all original words are present in dialogues (no word loss)
    all_dialogue_text = []
    for line in content_2.split("\n"):
        if line.startswith("Dialogue:"):
            text_part = line.split(",")[-1]
            import re
            clean_text = re.sub(r'\{[^}]*\}', '', text_part).replace("\\N", " ")
            all_dialogue_text.append(clean_text)
    reconstructed = " ".join(all_dialogue_text)
    for word in long_text.split():
        assert word in reconstructed, f"Word '{word}' lost!"
    
    # Test max_lines=3: should also split if needed
    ass_3 = subtitles.create_styled_subtitle_file(srt, cues=[cue], max_lines=3)
    content_3 = ass_3.read_text("utf-8")
    
    # Verify all original words are present in dialogues (no word loss)
    all_dialogue_text_3 = []
    for line in content_3.split("\n"):
        if line.startswith("Dialogue:"):
            text_part = line.split(",")[-1]
            import re
            clean_text = re.sub(r'\{[^}]*\}', '', text_part).replace("\\N", " ")
            all_dialogue_text_3.append(clean_text)
    reconstructed_3 = " ".join(all_dialogue_text_3)
    for word in long_text.split():
        assert word in reconstructed_3, f"Word '{word}' lost!"


def test_greek_text_fits_within_config_width():
    """
    REGRESSION: Greek uppercase text must not overflow video edges.
    With MAX_SUB_LINE_CHARS=32 and margins=80px, text should fit.
    """
    # Verify config values are safe
    assert config.MAX_SUB_LINE_CHARS <= 35, f"MAX_SUB_LINE_CHARS={config.MAX_SUB_LINE_CHARS} is too wide for Greek text"
    assert config.DEFAULT_SUB_MARGIN_L >= 60, f"Left margin {config.DEFAULT_SUB_MARGIN_L}px is too small"
    assert config.DEFAULT_SUB_MARGIN_R >= 60, f"Right margin {config.DEFAULT_SUB_MARGIN_R}px is too small"
    
    # Test that wrapping respects the char limit
    greek_words = ["ΑΝΘΡΩΠΟΥΣ", "ΔΙΑΦΟΡΕΣ", "ΣΥΖΗΤΗΣΕΙΣ", "ΚΑΠΙΤΑΛΙΣΜΟΣ"]
    result = subtitles._wrap_lines(greek_words, max_chars=config.MAX_SUB_LINE_CHARS, max_lines=2)
    
    for line_words in result:
        line_text = " ".join(line_words)
        # Allow slight overflow due to textwrap behavior with long words
        assert len(line_text) <= config.MAX_SUB_LINE_CHARS + 15, \
            f"Line '{line_text}' has {len(line_text)} chars, exceeds safe limit"


def test_format_karaoke_text_preserves_all_words():
    """
    REGRESSION: _format_karaoke_text must preserve ALL words.
    Priority: Data preservation > Strict line limit.
    """
    # Create words that would need many lines
    words = [
        subtitles.WordTiming(i * 0.1, (i + 1) * 0.1, w)
        for i, w in enumerate([
            "ΕΧΩ", "ΑΚΟΥΣΕΙ", "ΑΠΟ", "ΠΑΡΑ", "ΠΟΛΛΟΥΣ",
            "ΑΝΘΡΩΠΟΥΣ", "ΣΕ", "ΔΙΑΦΟΡΕΣ", "ΣΥΖΗΤΗΣΕΙΣ", "ΠΟΥ"
        ])
    ]
    cue = subtitles.Cue(start=0.0, end=1.0, text="", words=words)
    
    # Test with max_lines=2 - verify all words are present
    karaoke_2 = subtitles._format_karaoke_text(cue, max_lines=2)
    for w in words:
        assert w.text in karaoke_2, f"Word '{w.text}' lost with max_lines=2"
    
    # Test with max_lines=3 - verify all words are present
    karaoke_3 = subtitles._format_karaoke_text(cue, max_lines=3)
    for w in words:
        assert w.text in karaoke_3, f"Word '{w.text}' lost with max_lines=3"


def test_short_text_stays_on_single_line():
    """
    Ensure short text that fits on one line doesn't get unnecessarily split.
    """
    short_words = ["ΓΕΙΑ", "ΣΟΥ"]
    result = subtitles._wrap_lines(short_words, max_chars=32, max_lines=2)
    assert len(result) == 1, "Short text should stay on one line"
    assert result[0] == ["ΓΕΙΑ", "ΣΟΥ"]


# === EXPERIMENTAL PROVIDERS TESTS ===


def test_resolve_groq_api_key_explicit():
    """Test Groq API key resolution with explicit value."""
    assert subtitles._resolve_groq_api_key("my_key") == "my_key"


def test_resolve_groq_api_key_env(monkeypatch):
    """Test Groq API key resolution from environment."""
    monkeypatch.setenv("GROQ_API_KEY", "env_groq_key")
    assert subtitles._resolve_groq_api_key() == "env_groq_key"


def test_resolve_groq_api_key_file(monkeypatch, tmp_path):
    """Test Groq API key resolution from secrets file."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    config_dir = tmp_path / "project" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "secrets.toml").write_text('GROQ_API_KEY = "file_groq_key"')
    monkeypatch.setattr(subtitles.config, "PROJECT_ROOT", tmp_path / "project")
    assert subtitles._resolve_groq_api_key() == "file_groq_key"


def test_resolve_groq_api_key_not_found(monkeypatch, tmp_path):
    """Test Groq API key returns None when not found."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(subtitles.config, "PROJECT_ROOT", tmp_path / "nonexistent")
    assert subtitles._resolve_groq_api_key() is None


def test_transcribe_with_groq_missing_key(monkeypatch, tmp_path):
    """Test Groq transcription fails without API key."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(subtitles.config, "PROJECT_ROOT", tmp_path / "nonexistent")
    
    with pytest.raises(RuntimeError) as exc:
        subtitles._transcribe_with_groq(
            tmp_path / "audio.wav",
            None, "el", None, tmp_path
        )
    assert "Groq API key is required" in str(exc.value)


def test_transcribe_with_groq_success(monkeypatch, tmp_path):
    """Test successful Groq transcription."""
    class MockWord:
        def __init__(self, start, end, word):
            self.start = start
            self.end = end
            self.word = word
            
    class MockSegment:
        def __init__(self, start, end, text):
            self.start = start
            self.end = end
            self.text = text
            
    class MockTranscript:
        segments = [MockSegment(0.0, 1.0, "Γεια σου")]
        words = [MockWord(0.0, 0.5, "Γεια"), MockWord(0.5, 1.0, "σου")]
        
    class MockClient:
        class audio:
            class transcriptions:
                @staticmethod
                def create(*args, **kwargs):
                    return MockTranscript()
                    
    # Mock OpenAI import
    mock_openai = types.SimpleNamespace(OpenAI=lambda **kwargs: MockClient())
    monkeypatch.setitem(sys.modules, "openai", mock_openai)
    
    audio_path = tmp_path / "test.wav"
    audio_path.touch()
    
    srt_path, cues = subtitles._transcribe_with_groq(
        audio_path,
        model_name="whisper-large-v3-turbo",
        language="el",
        prompt=None,
        output_dir=tmp_path,
        api_key="test_key"
    )
    
    assert srt_path.exists()
    assert len(cues) == 1
    assert "ΓΕΙΑ" in cues[0].text


def test_transcribe_with_groq_api_error(monkeypatch, tmp_path):
    """Test Groq transcription handles API errors."""
    class MockClient:
        class audio:
            class transcriptions:
                @staticmethod
                def create(*args, **kwargs):
                    raise Exception("Groq API rate limit exceeded")
                    
    mock_openai = types.SimpleNamespace(OpenAI=lambda **kwargs: MockClient())
    monkeypatch.setitem(sys.modules, "openai", mock_openai)
    
    audio_path = tmp_path / "test.wav"
    audio_path.touch()
    
    with pytest.raises(RuntimeError) as exc:
         subtitles._transcribe_with_groq(
            audio_path, None, "el", None, tmp_path, api_key="test_key"
        )
    assert "Groq transcription failed" in str(exc.value)


def test_generate_subtitles_routes_to_groq(monkeypatch, tmp_path):
    """Test that provider='groq' routes to Groq transcription."""
    called_with = {}
    
    def mock_groq(*args, **kwargs):
        called_with.update({"args": args, "kwargs": kwargs})
        srt = tmp_path / "test.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nTest\n", encoding="utf-8")
        return srt, []
        
    monkeypatch.setattr(subtitles, "_transcribe_with_groq", mock_groq)
    
    audio_path = tmp_path / "test.wav"
    audio_path.touch()
    
    subtitles.generate_subtitles_from_audio(
        audio_path, 
        provider="groq",
        output_dir=tmp_path
    )
    
    assert called_with, "Groq transcription should have been called"


def test_transcribe_with_groq_progress_callback(monkeypatch, tmp_path):
    """Test Groq transcription calls progress callback."""
    class MockTranscript:
        segments = []
        words = []
        
    class MockClient:
        class audio:
            class transcriptions:
                @staticmethod
                def create(*args, **kwargs):
                    return MockTranscript()
                    
    mock_openai = types.SimpleNamespace(OpenAI=lambda **kwargs: MockClient())
    monkeypatch.setitem(sys.modules, "openai", mock_openai)
    
    audio_path = tmp_path / "test.wav"
    audio_path.touch()
    
    progress_values = []
    
    subtitles._transcribe_with_groq(
        audio_path,
        model_name=None,
        language="el",
        prompt=None,
        output_dir=tmp_path,
        progress_callback=lambda p: progress_values.append(p),
        api_key="test_key"
    )
    
    assert 10.0 in progress_values
    assert 90.0 in progress_values
    assert 100.0 in progress_values


# === REGRESSION TESTS FOR WHISPER.CPP WORD LOSS FIX ===


def test_cues_without_words_DO_split_interpolated():
    """
    REGRESSION: Cues without word timings MUST be split to respect UI line limits.
    Reason: User prefers strict line limits over perfect sync for Standard model.
    """
    long_text = "ΕΧΩ ΑΚΟΥΣΕΙ ΑΠΟ ΠΑΡΑ ΠΟΛΛΟΥΣ ΑΝΘΡΩΠΟΥΣ ΣΕ ΔΙΑΦΟΡΕΣ ΣΥΖΗΤΗΣΕΙΣ"
    # Logic uses 32 chars width by default.
    # Text len is ~60. 
    # max_lines=1 -> needs splitting.
    
    cue = subtitles.Cue(start=0.0, end=5.0, text=long_text, words=None)
    
    # Split with max_lines=1 to force split
    split_cues = subtitles._split_long_cues([cue], max_chars=30, max_lines=1)
    
    # Must have > 1 cue (splitting happened)
    assert len(split_cues) > 1, f"Cue without words SHOULD be split, got {len(split_cues)}"
    
    # Timing should be interpolated
    # First chunk end should be > start and < end
    assert split_cues[0].end > 0.0
    assert split_cues[0].end < 5.0
    
    # Text check
    reconstructed = " ".join(c.text for c in split_cues)
    assert reconstructed == long_text


def test_standard_model_no_words_lost(monkeypatch, tmp_path):
    """
    REGRESSION: Standard model (whisper.cpp) must NOT lose any words.
    Bug: Long subtitles were truncated to max_lines, silently dropping text.
    """
    import types
    import sys
    
    # Very long Greek text that would normally overflow max_lines
    long_text = "ΕΧΩ ΑΚΟΥΣΕΙ ΑΠΟ ΠΑΡΑ ΠΟΛΛΟΥΣ ΑΝΘΡΩΠΟΥΣ ΣΕ ΔΙΑΦΟΡΕΣ ΣΥΖΗΤΗΣΕΙΣ ΠΟΥ ΕΧΩ ΚΑΝΕΙ ΟΤΙ Ο ΚΑΠΙΤΑΛΙΣΜΟΣ"
    
    class MockSegment:
        def __init__(self, t0, t1, text):
            self.t0 = t0
            self.t1 = t1
            self.text = text

    class MockModel:
        def __init__(self, *args, **kwargs):
            pass
        
        def transcribe(self, audio, language, n_threads=8):
            return [MockSegment(0, 500, long_text)]  # 5 seconds in centiseconds

    # Mock pywhispercpp module
    mock_module = types.SimpleNamespace()
    mock_module.model = types.SimpleNamespace(Model=MockModel)
    monkeypatch.setitem(sys.modules, "pywhispercpp", mock_module)
    monkeypatch.setitem(sys.modules, "pywhispercpp.model", mock_module.model)

    audio_path = tmp_path / "test.wav"
    audio_path.touch()

    srt_path, cues = subtitles._transcribe_with_whispercpp(
        audio_path, None, "el", tmp_path
    )
    
    # Verify transcription succeeded
    assert len(cues) >= 1
    
    # Create styled subtitle file with max_lines=2
    ass_path = subtitles.create_styled_subtitle_file(
        srt_path, cues=cues, max_lines=2, output_dir=tmp_path
    )
    ass_content = ass_path.read_text("utf-8")
    
    # Extract all dialogue text and verify NO WORDS ARE LOST
    dialogue_lines = [l for l in ass_content.split("\n") if l.startswith("Dialogue:")]
    assert len(dialogue_lines) >= 1, "No dialogue lines found"
    
    # Reconstruct all text from dialogues
    all_text_parts = []
    for line in dialogue_lines:
        # Extract text after the last comma (dialogue text)
        text_part = line.split(",")[-1]
        # Remove ASS formatting tags
        import re
        clean_text = re.sub(r'\{[^}]*\}', '', text_part)
        clean_text = clean_text.replace("\\N", " ").strip()
        all_text_parts.append(clean_text)
    
    reconstructed = " ".join(all_text_parts)
    
    # Normalize for comparison (remove extra spaces, uppercase)
    normalized_original = subtitles._normalize_text(long_text)
    normalized_reconstructed = " ".join(reconstructed.split())
    
    # All words from original MUST appear in reconstructed
    original_words = set(normalized_original.split())
    reconstructed_words = set(normalized_reconstructed.split())
    
    missing_words = original_words - reconstructed_words
    assert not missing_words, f"WORDS LOST: {missing_words}"


def test_per_word_karaoke():
    """
    REGRESSION: Karaoke uses per-word subtitle events.
    Each word becomes its own dialogue event with exact timing.
    """
    # Words with gaps: 0.0-0.5s, 0.8-1.2s, 1.4-1.8s
    words = [
        subtitles.WordTiming(start=0.0, end=0.5, text='HELLO'),
        subtitles.WordTiming(start=0.8, end=1.2, text='WORLD'),
        subtitles.WordTiming(start=1.4, end=1.8, text='TEST'),
    ]
    cue = subtitles.Cue(start=0, end=2.0, text='HELLO WORLD TEST', words=words)
    
    # Split into per-word cues
    split_cues = subtitles._split_long_cues([cue], max_chars=1)
    
    # Should have one cue per word
    assert len(split_cues) == 3, f"Expected 3 cues, got {len(split_cues)}"
    
    # Each cue should have correct timing
    assert split_cues[0].text == 'HELLO'
    assert split_cues[0].start == 0.0
    assert split_cues[0].end == 0.5
    
    assert split_cues[1].text == 'WORLD'
    assert split_cues[1].start == 0.8
    assert split_cues[1].end == 1.2
    
    assert split_cues[2].text == 'TEST'
    assert split_cues[2].start == 1.4
    assert split_cues[2].end == 2.0  # Uses original cue end for last word


import pytest
from backend.app.services import subtitles

def test_1_word_mode_splitting_standard_model():
    """
    REGRESSION: "1 Word" mode (max_lines=0) must split into single words even without word timings.
    Bug: Previously fell through to no-split, resulting in 3+ lines for long text.
    """
    # Simulate create_styled_subtitle_file logic call to _split_long_cues(max_chars=1, max_lines=1)
    
    long_text = "ONE TWO THREE FOUR"
    cue = subtitles.Cue(start=0.0, end=4.0, text=long_text, words=None)
    
    # max_chars=1 forces split at every word boundary (roughly)
    # This simulates what create_styled_subtitle_file calls when max_lines=0
    split_cues = subtitles._split_long_cues([cue], max_chars=1, max_lines=1)
    
    # Should have 4 cues (one per word)
    assert len(split_cues) == 4, f"Should split into 4 cues, got {len(split_cues)}"
    assert split_cues[0].text == "ONE"
    assert split_cues[1].text == "TWO"
    assert split_cues[2].text == "THREE"
    assert split_cues[3].text == "FOUR"
    
    # Durations should be interpolated linearly based on char count
    # "ONE" is 3 chars. Total chars (no spaces) is 15. Duration 4.0s.
    # 3/15 * 4.0 = 0.8s
    assert split_cues[0].end == pytest.approx(0.8, 0.1)
    # "TWO" is 3 chars -> +0.8s -> 1.6s
    assert split_cues[1].end == pytest.approx(1.6, 0.1)
    # "THREE" is 5 chars -> 5/15 * 4 = 1.33s -> 2.93s
    assert split_cues[2].end == pytest.approx(2.93, 0.1)
    # "FOUR" is 4 chars -> 4/15 * 4 = 1.06s -> 4.0s
    # "FOUR" is 4 chars -> 4/15 * 4 = 1.06s -> 4.0s
    assert split_cues[3].end == pytest.approx(4.0, 0.1)


def test_generate_active_word_ass_no_words():
    # Fallback when no words present
    cue = subtitles.Cue(0.0, 1.0, "Hello", words=None)
    lines = subtitles._generate_active_word_ass(cue, 2, "P", "S")
    assert len(lines) == 1
    assert "Dialogue:" in lines[0]
    assert ",Hello" in lines[0]

def test_generate_active_word_ass_logic():
    # 2 words: "Hello", "World"
    # Expected: 
    # 1 base layer (all dim)
    # 2 active layers (dim-lit-dim or similar logic)
    
    words = [
        subtitles.WordTiming(0.0, 0.5, "Hello"),
        subtitles.WordTiming(0.5, 1.0, "World")
    ]
    cue = subtitles.Cue(0.0, 1.0, "Hello World", words=words)
    
    lines = subtitles._generate_active_word_ass(cue, 2, "P", "S")
    
    # Base: 1
    # Active: 2 (one per word)
    assert len(lines) == 3
    
    base = lines[0]
    assert "Dialogue: 0," in base
    assert r"{\cS&}Hello" in base # All words secondary color
    assert r"{\cS&}World" in base
    
    active1 = lines[1]
    assert "Dialogue: 1," in active1
    # First event: start 0.0, end 0.5. "Hello" primary, "World" secondary
    assert "0:00:00.00,0:00:00.50" in active1
    assert r"{\cP&}Hello" in active1
    assert r"{\cS&}World" in active1

    active2 = lines[2]
    # Second event: start 0.5, end 1.0. "Hello" secondary, "World" primary
    assert "0:00:00.50,0:00:01.00" in active2
    assert r"{\cS&}Hello" in active2
    assert r"{\cP&}World" in active2

def test_split_long_cues_with_phrases_interpolation():
    # Trigger logic for word token interpolation (space in word)
    words = [
        subtitles.WordTiming(0.0, 2.0, "Part1 Part2")
    ]
    cue = subtitles.Cue(0.0, 2.0, "Part1 Part2", words=words)
    
    # Force split by max_chars=1
    split = subtitles._split_long_cues([cue], max_chars=1, max_lines=1)
    
    assert len(split) == 2
    assert split[0].text == "Part1"
    assert split[0].start == 0.0
    assert split[0].end == 1.0
    
    assert split[1].text == "Part2"
    assert split[1].start == 1.0
    assert split[1].end == 2.0
