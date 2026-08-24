from __future__ import annotations

from pathlib import Path

from backend.app.core.config import settings
from backend.app.services.video_export_cache import build_video_export_signature


def _signature(
    input_video: Path,
    artifact_dir: Path,
    *,
    watermark_enabled: bool = False,
) -> str:
    return build_video_export_signature(
        input_video=input_video,
        artifact_dir=artifact_dir,
        resolution="1080x1920",
        subtitle_settings={
            "subtitle_size": 85,
            "watermark_enabled": watermark_enabled,
        },
        result_data={"subtitle_size": 100, "watermark_enabled": False},
        video_crf=20,
    )


def test_export_signature_is_stable_and_tracks_render_inputs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    input_video = tmp_path / "source.mp4"
    input_video.write_bytes(b"video")
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    transcript = artifact_dir / "source.srt"
    transcript.write_text("hello", encoding="utf-8")
    transcription = artifact_dir / "transcription.json"
    transcription.write_text('[{"text":"hello"}]', encoding="utf-8")

    initial = _signature(input_video, artifact_dir)
    assert _signature(input_video, artifact_dir) == initial

    transcription.write_text('[{"text":"changed"}]', encoding="utf-8")
    assert _signature(input_video, artifact_dir) != initial

    transcript.unlink()
    fallback = artifact_dir / "fallback.srt"
    fallback.write_text("changed", encoding="utf-8")
    fallback_signature = _signature(input_video, artifact_dir)
    assert fallback_signature != initial

    ass_path = artifact_dir / "source.ass"
    ass_path.write_text("styled captions", encoding="utf-8")
    ass_signature = _signature(input_video, artifact_dir)
    assert ass_signature != fallback_signature

    ass_path.write_text("changed style", encoding="utf-8")
    assert _signature(input_video, artifact_dir) != ass_signature

    fallback.unlink()
    transcription.unlink()
    missing_transcript_signature = _signature(input_video, artifact_dir)
    assert missing_transcript_signature != fallback_signature

    watermark = tmp_path / "watermark.png"
    watermark.write_bytes(b"watermark")
    monkeypatch.setattr(settings, "watermark_path", watermark)
    assert _signature(input_video, artifact_dir, watermark_enabled=True) != missing_transcript_signature
