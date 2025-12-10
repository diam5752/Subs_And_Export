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
            return [
                StubSegment(
                    0.0,
                    1.5,
                    "Γεια σου",
                    [StubWord(0.0, 0.7, "Γεια"), StubWord(0.7, 1.5, "σου")],
                )
            ], None

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
    assert "\\k" in ass_content


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
            return [], None

    monkeypatch.setattr(subtitles, "_get_whisper_model", lambda *a, **k: StubModel())
    subtitles.generate_subtitles_from_audio(audio_path, language="auto", output_dir=tmp_path)


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

            return [Seg()], None

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
