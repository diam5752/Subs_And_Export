from pathlib import Path

from greek_sub_publisher import video_processing


def test_normalize_and_stub_subtitles_runs_pipeline(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_extract(input_video: Path, output_dir=None) -> Path:
        calls.append(("extract", input_video))
        audio = tmp_path / "audio.wav"
        audio.write_text("audio")
        return audio

    def fake_generate(audio_path: Path, **kwargs):
        calls.append(("transcribe", audio_path, kwargs))
        srt = tmp_path / "subs.srt"
        srt.write_text("1\n00:00:00,00 --> 00:00:01,00\nΓεια\n", encoding="utf-8")
        cues = [
            video_processing.subtitles.Cue(
                start=0.0,
                end=1.0,
                text="Γεια",
                words=[video_processing.subtitles.WordTiming(0.0, 1.0, "Γεια")],
            )
        ]
        return srt, cues

    def fake_style(transcript_path: Path, **kwargs) -> Path:
        calls.append(("style", transcript_path))
        ass = tmp_path / "subs.ass"
        ass.write_text("[Script Info]\n")
        return ass

    def fake_burn(
        input_path: Path,
        ass_path: Path,
        output_path: Path,
        *,
        video_crf,
        video_preset,
        audio_bitrate,
        audio_copy,
    ) -> None:
        calls.append(
            (
                "burn",
                input_path,
                ass_path,
                output_path,
                video_crf,
                video_preset,
                audio_bitrate,
                audio_copy,
            )
        )
        output_path.write_bytes(b"video")

    monkeypatch.setattr(video_processing.subtitles, "extract_audio", fake_extract)
    monkeypatch.setattr(
        video_processing.subtitles, "generate_subtitles_from_audio", fake_generate
    )
    monkeypatch.setattr(
        video_processing.subtitles, "create_styled_subtitle_file", fake_style
    )
    monkeypatch.setattr(video_processing, "_run_ffmpeg_with_subs", fake_burn)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    destination = tmp_path / "dest.mp4"

    result_path = video_processing.normalize_and_stub_subtitles(
        source, destination, language="el", video_crf=18
    )

    assert result_path == destination.resolve()
    assert destination.read_bytes() == b"video"
    assert [c[0] for c in calls] == ["extract", "transcribe", "style", "burn"]


def test_build_filtergraph_quotes_ass_path() -> None:
    ass_path = Path("/tmp/my subs's file.ass")

    filtergraph = video_processing._build_filtergraph(ass_path)

    assert filtergraph.endswith("ass='/tmp/my subs\\'s file.ass'")
