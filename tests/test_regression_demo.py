from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from greek_sub_publisher import subtitles


DEMO_VIDEO = Path("tests/data/demo.mp4")
GOLDEN_DIR = Path("tests/data/demo_artifacts")


@pytest.mark.slow
def test_demo_video_transcription_matches_golden(tmp_path: Path) -> None:
    audio_path = subtitles.extract_audio(DEMO_VIDEO, output_dir=tmp_path)
    try:
        srt_path, cues = subtitles.generate_subtitles_from_audio(
            audio_path,
            model_size="large-v2",
            language="el",
            beam_size=5,
            best_of=1,
            compute_type="int8",  # keep stable output for regression golden
            vad_filter=False,  # avoid VAD shifts that move timestamps
            chunk_length=None,  # use library default to match golden
            output_dir=tmp_path,
        )
    except httpx.HTTPError as exc:  # pragma: no cover - network dependent
        pytest.skip(f"Model download not available in test environment: {exc}")

    expected_srt = (GOLDEN_DIR / "demo.srt").read_text(encoding="utf-8").strip()
    actual_srt = srt_path.read_text(encoding="utf-8").strip()
    assert actual_srt == expected_srt

    transcript_text = subtitles.cues_to_text(cues)
    expected_transcript = (GOLDEN_DIR / "transcript.txt").read_text(encoding="utf-8").strip()
    assert transcript_text == expected_transcript

    expected_social = json.loads((GOLDEN_DIR / "social_copy.json").read_text(encoding="utf-8"))
    social = subtitles.build_social_copy(transcript_text)

    assert social.tiktok.title == expected_social["tiktok"]["title"]
    assert social.tiktok.description.strip() == expected_social["tiktok"]["description"].strip()
    assert social.youtube_shorts.title == expected_social["youtube_shorts"]["title"]
    assert (
        social.youtube_shorts.description.strip()
        == expected_social["youtube_shorts"]["description"].strip()
    )
    assert social.instagram.title == expected_social["instagram"]["title"]
    assert social.instagram.description.strip() == expected_social["instagram"]["description"].strip()
