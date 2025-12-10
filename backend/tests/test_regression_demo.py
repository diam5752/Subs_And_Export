from __future__ import annotations

import json
from pathlib import Path
import shutil

import httpx
import pytest

from backend.app.services import subtitles


DEMO_VIDEO = Path("tests/data/demo.mp4")
GOLDEN_DIR = Path("tests/data/demo_artifacts")
TIMESTAMP_TOLERANCE = 0.05  # 50ms drift allowance between platforms


pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required for demo regression")


def _assert_srt_matches_with_tolerance(actual_path: Path, expected_path: Path, tolerance: float) -> None:
    expected = subtitles._parse_srt(expected_path)
    actual = subtitles._parse_srt(actual_path)
    assert len(actual) == len(expected)
    for (a_start, a_end, a_text), (e_start, e_end, e_text) in zip(actual, expected):
        assert a_text == e_text
        assert abs(a_start - e_start) <= tolerance
        assert abs(a_end - e_end) <= tolerance


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

    _assert_srt_matches_with_tolerance(srt_path, GOLDEN_DIR / "demo.srt", tolerance=TIMESTAMP_TOLERANCE)

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
