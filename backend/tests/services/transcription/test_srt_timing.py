from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from backend.app.services.transcription.utils import write_srt_from_segments


def test_transcription_srt_keeps_milliseconds_and_rolls_over_seconds(tmp_path: Path) -> None:
    output = write_srt_from_segments(
        [(7.92, 11.62, "Caption"), (59.9996, 61.001, "Next caption")],
        tmp_path / "transcript.srt",
    )

    assert output.read_text(encoding="utf-8") == (
        "1\n00:00:07,920 --> 00:00:11,620\nCaption\n\n2\n00:01:00,000 --> 00:01:01,001\nNext caption\n"
    )


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="FFprobe is required for SRT playback verification")
def test_transcription_srt_is_parsed_at_the_recorded_cue_times(tmp_path: Path) -> None:
    # REGRESSION: the old centisecond writer made 7.92s play as 7.092s.
    output = write_srt_from_segments([(7.92, 11.62, "Caption")], tmp_path / "transcript.srt")
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "json",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )

    packet = json.loads(result.stdout)["packets"][0]
    assert float(packet["pts_time"]) == pytest.approx(7.92)
    assert float(packet["duration_time"]) == pytest.approx(3.7)
