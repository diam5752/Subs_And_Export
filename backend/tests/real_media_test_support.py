"""Reusable FFmpeg and image assertions for real-media export tests."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from backend.app.services import video_processing

TEST_DURATION_SECONDS = 1.2
MAX_DURATION_SECONDS = 600.0
FRAME_TIMESTAMP_SECONDS = 0.55
DEMO_FRAME_TIMESTAMP_SECONDS = 1.2
DEMO_VIDEO = Path(__file__).parent / "data" / "demo.mp4"
DEMO_GOLDEN_VIDEO = Path(__file__).parent / "data" / "demo_output.mp4"
DEMO_ARTIFACTS = Path(__file__).parent / "data" / "demo_artifacts"


@dataclass(frozen=True)
class MediaCase:
    name: str
    source_name: str
    resolution: str
    source_video_codec: str
    source_audio_codec: str | None


@dataclass(frozen=True)
class VisualSignature:
    pixel_count: int
    bounding_box: tuple[int, int, int, int]
    centroid_x: float
    centroid_y: float


@dataclass(frozen=True)
class ExportJob:
    user_id: str
    result_data: dict[str, object]


class ExportJobStore:
    def __init__(self, user_id: str, result_data: dict[str, object] | None = None) -> None:
        self._job = ExportJob(user_id=user_id, result_data=result_data or {})

    def get_job(self, _job_id: str) -> ExportJob:
        return self._job


MEDIA_CASES = (
    MediaCase("h264-aac-fast-export", "h264_aac.mp4", "720x1280", "h264", "aac"),
    MediaCase("h264-aac-mp4", "h264_aac.mp4", "1080x1920", "h264", "aac"),
    MediaCase("mpeg4-pcm-mov", "mpeg4_pcm.mov", "540x960", "mpeg4", "pcm_s16le"),
    MediaCase("ffv1-silent-mkv", "ffv1_silent.mkv", "540x960", "ffv1", None),
    MediaCase("h264-vfr-mkv", "h264_vfr.mkv", "540x960", "h264", None),
    MediaCase("hevc-hdr10-mov", "hevc_hdr10.mov", "540x960", "hevc", None),
    MediaCase("rotated-h264-mov", "rotated_h264.mov", "540x960", "h264", None),
    MediaCase("h264-aac-uhd-export", "h264_aac.mp4", "2160x3840", "h264", "aac"),
)


def _run(command: list[str], *, timeout_seconds: float = 180.0) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    if completed.returncode != 0:
        command_text = " ".join(command)
        pytest.fail(
            f"Media command failed with exit code {completed.returncode}: {command_text}\n"
            f"stderr:\n{completed.stderr[-6000:]}"
        )
    return completed


def _probe(path: Path) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ]
    )
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _stream(payload: dict[str, Any], codec_type: str) -> dict[str, Any] | None:
    streams = payload.get("streams", [])
    assert isinstance(streams, list)
    return next(
        (stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == codec_type),
        None,
    )


def _duration(payload: dict[str, Any]) -> float:
    format_payload = payload.get("format", {})
    assert isinstance(format_payload, dict)
    duration = format_payload.get("duration")
    assert duration is not None
    return float(duration)


def _video_frame_timestamps(path: Path) -> list[float]:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            str(path),
        ]
    )
    payload = json.loads(result.stdout)
    frames = payload.get("frames", [])
    assert isinstance(frames, list)
    return sorted(
        float(frame["best_effort_timestamp_time"])
        for frame in frames
        if isinstance(frame, dict) and frame.get("best_effort_timestamp_time") is not None
    )


def _extract_frame(
    video_path: Path,
    destination: Path,
    *,
    timestamp_seconds: float = FRAME_TIMESTAMP_SECONDS,
    video_filter: str | None = None,
) -> Image.Image:
    command = [
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        str(timestamp_seconds),
        "-i",
        str(video_path),
    ]
    if video_filter:
        command.extend(["-vf", video_filter])
    command.extend(["-frames:v", "1", str(destination)])
    _run(command)
    with Image.open(destination) as image:
        return image.convert("RGB")


def _write_srt(artifact_dir: Path, source_stem: str, text: str = "ΔΟΚΙΜΗ ΕΞΑΓΩΓΗΣ") -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    srt_path = artifact_dir / f"{source_stem}.srt"
    srt_path.write_text(
        f"1\n00:00:00,100 --> 00:00:01,050\n{text}\n",
        encoding="utf-8",
    )
    return srt_path


def _render_variant(
    source: Path,
    artifact_dir: Path,
    *,
    resolution: str,
    subtitle_settings: dict[str, object] | None = None,
) -> Path:
    _write_srt(artifact_dir, source.stem)
    return video_processing.generate_video_variant(
        f"real-media-{artifact_dir.name}",
        source,
        artifact_dir,
        resolution,
        ExportJobStore("media-test-user"),
        "media-test-user",
        subtitle_settings=subtitle_settings,
    )


def _decode_entire_export(path: Path) -> None:
    _run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        timeout_seconds=240.0,
    )


def _color_pixel_count(image: Image.Image, color_name: str) -> int:
    def matches(pixel: tuple[int, int, int]) -> bool:
        red, green, blue = pixel
        if color_name == "yellow":
            return red > 175 and green > 175 and blue < 135
        if color_name == "white":
            return red > 185 and green > 185 and blue > 185
        if color_name == "cyan":
            return red < 135 and green > 175 and blue > 175
        raise ValueError(f"Unsupported color: {color_name}")

    return sum(1 for pixel in _pixel_data(image) if matches(pixel))


def _pixel_data(image: Image.Image) -> list[tuple[int, int, int]]:
    flattened_reader = getattr(image, "get_flattened_data", None)
    if callable(flattened_reader):
        return list(flattened_reader())
    return list(image.getdata())


def _visual_signature(
    rendered: Image.Image,
    baseline: Image.Image,
    *,
    crop: tuple[int, int, int, int] | None = None,
    channel_threshold: int = 42,
    total_threshold: int = 75,
) -> VisualSignature:
    assert rendered.size == baseline.size
    selected_crop = crop or (0, 0, rendered.width, rendered.height)
    rendered_crop = rendered.crop(selected_crop)
    baseline_crop = baseline.crop(selected_crop)
    crop_width = rendered_crop.width
    changed_coordinates: list[tuple[int, int]] = []

    for index, (rendered_pixel, baseline_pixel) in enumerate(
        zip(_pixel_data(rendered_crop), _pixel_data(baseline_crop), strict=True)
    ):
        differences = tuple(
            abs(rendered_channel - baseline_channel)
            for rendered_channel, baseline_channel in zip(
                rendered_pixel,
                baseline_pixel,
                strict=True,
            )
        )
        if max(differences) > channel_threshold and sum(differences) > total_threshold:
            x = selected_crop[0] + (index % crop_width)
            y = selected_crop[1] + (index // crop_width)
            changed_coordinates.append((x, y))

    assert changed_coordinates, "No visible subtitle or overlay pixels were detected"
    xs = [coordinate[0] for coordinate in changed_coordinates]
    ys = [coordinate[1] for coordinate in changed_coordinates]
    return VisualSignature(
        pixel_count=len(changed_coordinates),
        bounding_box=(min(xs), min(ys), max(xs), max(ys)),
        centroid_x=sum(xs) / len(xs),
        centroid_y=sum(ys) / len(ys),
    )


def _mean_absolute_difference(
    first: Image.Image,
    second: Image.Image,
    crop: tuple[int, int, int, int],
) -> float:
    first_pixels = _pixel_data(first.crop(crop))
    second_pixels = _pixel_data(second.crop(crop))
    total = 0
    channel_count = 0
    for first_pixel, second_pixel in zip(first_pixels, second_pixels, strict=True):
        total += sum(abs(a - b) for a, b in zip(first_pixel, second_pixel, strict=True))
        channel_count += 3
    assert channel_count > 0
    return total / channel_count
