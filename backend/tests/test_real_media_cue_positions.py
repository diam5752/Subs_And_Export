from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from backend.app.core.config import settings
from backend.app.services import video_processing
from backend.tests.real_media_test_support import (
    DEMO_VIDEO,
    ExportJobStore,
    _decode_entire_export,
    _write_srt,
)

pytestmark = pytest.mark.media_export


@pytest.fixture(autouse=True)
def deterministic_media_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "default_video_preset", "ultrafast")
    monkeypatch.setattr(settings, "default_video_crf", 30)
    monkeypatch.setattr(settings, "default_audio_bitrate", "96k")
    monkeypatch.setattr(settings, "use_hw_accel", False)


def test_real_export_decodes_with_one_phrase_at_a_custom_position(
    tmp_path: Path,
) -> None:
    artifact_dir = tmp_path / "per-cue-position"
    _write_srt(artifact_dir, DEMO_VIDEO.stem, "FALLBACK")
    (artifact_dir / "transcription.json").write_text(
        json.dumps(
            [
                {"start": 0.1, "end": 0.55, "text": "CUSTOM", "position": 80},
                {"start": 0.6, "end": 1.05, "text": "SHARED"},
            ]
        ),
        encoding="utf-8",
    )

    output = video_processing.generate_video_variant(
        "per-cue-position-real-export",
        DEMO_VIDEO,
        artifact_dir,
        "360x640",
        ExportJobStore("media-test-user"),
        "media-test-user",
        subtitle_settings={
            "subtitle_position": 20,
            "subtitle_size": 100,
            "max_subtitle_lines": 2,
            "subtitle_color": "&H0000FFFF",
            "shadow_strength": 2,
            "karaoke_enabled": False,
            "highlight_style": "static",
        },
    )

    ass_text = (artifact_dir / f"{DEMO_VIDEO.stem}.ass").read_text(encoding="utf-8")
    custom_line = next(line for line in ass_text.splitlines() if "CUSTOM" in line)
    shared_line = next(line for line in ass_text.splitlines() if "SHARED" in line)
    custom_position = re.search(r"\\pos\(\d+,(\d+)\)", custom_line)
    shared_position = re.search(r"\\pos\(\d+,(\d+)\)", shared_line)
    assert custom_position is not None
    assert shared_position is not None
    assert int(custom_position.group(1)) < int(shared_position.group(1))
    assert output.stat().st_size > 1_000
    _decode_entire_export(output)
