from __future__ import annotations

import shutil
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from backend.app.services import ffmpeg_utils


def test_probe_media_bytes_uses_stdin_without_a_temporary_file(monkeypatch) -> None:
    run = MagicMock(
        return_value=SimpleNamespace(
            stdout=(b'{"format":{"duration":"12.5"},"streams":[{"codec_name":"aac","codec_type":"audio"}]}'),
            stderr=b"",
        ),
    )
    monkeypatch.setattr(ffmpeg_utils.subprocess, "run", run)

    probe = ffmpeg_utils.probe_media_bytes(b"bounded-audio")

    assert probe.duration_s == 12.5
    assert probe.audio_codec == "aac"
    command = run.call_args.args[0]
    assert command[-1] == "pipe:0"
    assert "-select_streams" not in command
    assert "codec_type" in command[command.index("-show_entries") + 1]
    assert run.call_args.kwargs["input"] == b"bounded-audio"
    assert "text" not in run.call_args.kwargs
    assert probe.has_video is False


@pytest.mark.parametrize(
    "streams",
    (
        (
            {"codec_name": "h264", "codec_type": "video"},
            {"codec_name": "aac", "codec_type": "audio"},
        ),
        (
            {"codec_name": "aac", "codec_type": "audio"},
            {"codec_name": "h264", "codec_type": "video"},
        ),
    ),
)
def test_probe_payload_detects_video_in_any_stream_order(
    streams: tuple[dict[str, str], dict[str, str]],
) -> None:
    probe = ffmpeg_utils._media_probe_from_payload(
        {
            "format": {"duration": "1.0"},
            "streams": list(streams),
        },
    )

    assert probe.duration_s == 1.0
    assert probe.audio_codec == "aac"
    assert probe.has_video is True


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required for the real media regression",
)
def test_probe_media_bytes_detects_real_h264_aac_video(tmp_path) -> None:
    from backend.app.api.endpoints.mobile_transcriptions import _authoritative_duration

    video_path = tmp_path / "video-with-aac.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=32x32:r=2:d=0.5",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=0.5",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(video_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    video_bytes = video_path.read_bytes()
    probe = ffmpeg_utils.probe_media_bytes(video_bytes)

    assert probe.audio_codec == "aac"
    assert probe.has_video is True
    with pytest.raises(HTTPException) as error:
        _authoritative_duration(video_bytes, authorized_credits=30)
    assert error.value.status_code == 400
    assert error.value.detail == "Mobile audio must not contain video"


def test_probe_media_bytes_rejects_an_empty_body_before_ffprobe(monkeypatch) -> None:
    run = MagicMock()
    monkeypatch.setattr(ffmpeg_utils.subprocess, "run", run)

    with pytest.raises(ValueError, match="empty"):
        ffmpeg_utils.probe_media_bytes(b"")

    run.assert_not_called()
