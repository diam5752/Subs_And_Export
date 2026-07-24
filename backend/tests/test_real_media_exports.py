from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from backend.app.core.config import settings
from backend.app.services import video_processing

pytestmark = pytest.mark.media_export

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
        (
            stream
            for stream in streams
            if isinstance(stream, dict) and stream.get("codec_type") == codec_type
        ),
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


@pytest.fixture(autouse=True)
def deterministic_media_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    assert not missing, f"Real media export gate requires installed tools: {', '.join(missing)}"
    monkeypatch.setattr(settings, "default_video_preset", "ultrafast")
    monkeypatch.setattr(settings, "default_video_crf", 30)
    monkeypatch.setattr(settings, "default_audio_bitrate", "96k")
    monkeypatch.setattr(settings, "use_hw_accel", False)


@pytest.fixture(scope="module")
def source_media(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    source_dir = tmp_path_factory.mktemp("real-media-sources")
    color_input = f"color=c=0x101820:s=180x320:r=24:d={TEST_DURATION_SECONDS}"
    landscape_input = f"color=c=0x101820:s=320x180:r=24:d={TEST_DURATION_SECONDS}"

    h264_aac = source_dir / "h264_aac.mp4"
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", color_input,
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={TEST_DURATION_SECONDS}",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k", str(h264_aac),
        ]
    )

    mpeg4_pcm = source_dir / "mpeg4_pcm.mov"
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", color_input,
            "-f", "lavfi", "-i", f"sine=frequency=660:duration={TEST_DURATION_SECONDS}",
            "-shortest", "-c:v", "mpeg4", "-q:v", "5",
            "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(mpeg4_pcm),
        ]
    )

    ffv1_silent = source_dir / "ffv1_silent.mkv"
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", color_input,
            "-an", "-c:v", "ffv1", "-level", "3", "-pix_fmt", "yuv420p", str(ffv1_silent),
        ]
    )

    h264_vfr = source_dir / "h264_vfr.mkv"
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", color_input,
            "-vf", "select='if(lt(n,12),not(mod(n,2)),not(mod(n,3)))'",
            "-fps_mode", "vfr", "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(h264_vfr),
        ]
    )

    hevc_hdr10 = source_dir / "hevc_hdr10.mov"
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", color_input,
            "-vf", "format=yuv420p10le,setparams=color_primaries=bt2020:"
            "color_trc=smpte2084:colorspace=bt2020nc",
            "-an", "-c:v", "libx265", "-preset", "ultrafast",
            "-x265-params", "pools=1:frame-threads=1:log-level=error:"
            "colorprim=bt2020:transfer=smpte2084:colormatrix=bt2020nc",
            "-pix_fmt", "yuv420p10le",
            "-tag:v", "hvc1", str(hevc_hdr10),
        ]
    )

    rotation_base = source_dir / "rotation_base.mp4"
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", landscape_input,
            "-an", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(rotation_base),
        ]
    )
    rotated_h264 = source_dir / "rotated_h264.mov"
    _run(
        [
            "ffmpeg", "-y", "-v", "error", "-display_rotation:v:0", "90",
            "-i", str(rotation_base), "-c", "copy", str(rotated_h264),
        ]
    )

    return {
        path.name: path
        for path in (h264_aac, mpeg4_pcm, ffv1_silent, h264_vfr, hevc_hdr10, rotated_h264)
    }


def _assert_source_contract(case: MediaCase, source: Path, payload: dict[str, Any]) -> None:
    video_stream = _stream(payload, "video")
    assert video_stream is not None
    assert video_stream.get("codec_name") == case.source_video_codec

    audio_stream = _stream(payload, "audio")
    if case.source_audio_codec is None:
        assert audio_stream is None
    else:
        assert audio_stream is not None
        assert audio_stream.get("codec_name") == case.source_audio_codec

    if case.name == "h264-vfr-mkv":
        timestamps = _video_frame_timestamps(source)
        deltas = {
            round(later - earlier, 3)
            for earlier, later in zip(timestamps, timestamps[1:])
            if later > earlier
        }
        assert len(deltas) >= 2, f"VFR fixture is not variable-frame-rate: {sorted(deltas)}"

    if case.name == "hevc-hdr10-mov":
        assert video_stream.get("pix_fmt") == "yuv420p10le"
        assert video_stream.get("color_primaries") == "bt2020"
        assert video_stream.get("color_transfer") == "smpte2084"

    if case.name == "rotated-h264-mov":
        side_data = video_stream.get("side_data_list", [])
        rotations = [
            abs(int(item["rotation"]))
            for item in side_data
            if isinstance(item, dict) and item.get("rotation") is not None
        ]
        assert 90 in rotations, f"Rotated fixture has no 90-degree display matrix: {side_data}"


@pytest.mark.parametrize("case", MEDIA_CASES, ids=lambda case: case.name)
def test_real_export_compatibility_matrix(
    case: MediaCase,
    source_media: dict[str, Path],
    tmp_path: Path,
) -> None:
    source = source_media[case.source_name]
    source_probe = _probe(source)
    _assert_source_contract(case, source, source_probe)

    output = _render_variant(
        source,
        tmp_path / case.name,
        resolution=case.resolution,
        subtitle_settings={
            "subtitle_position": 16,
            "subtitle_size": 100,
            "max_subtitle_lines": 2,
            "subtitle_color": "&H0000FFFF",
            "shadow_strength": 3,
            "karaoke_enabled": False,
            "highlight_style": "static",
        },
    )

    assert output.exists()
    assert output.stat().st_size > 1_000
    output_probe = _probe(output)
    output_video = _stream(output_probe, "video")
    assert output_video is not None
    expected_width, expected_height = (int(value) for value in case.resolution.split("x"))
    assert output_video.get("codec_name") == "h264"
    assert output_video.get("pix_fmt") == "yuv420p"
    assert output_video.get("width") == expected_width
    assert output_video.get("height") == expected_height

    output_audio = _stream(output_probe, "audio")
    if case.source_audio_codec is None:
        assert output_audio is None
    else:
        assert output_audio is not None
        assert output_audio.get("codec_name") == "aac"

    assert abs(_duration(output_probe) - _duration(source_probe)) <= 0.35
    _decode_entire_export(output)

    preview = _extract_frame(
        output,
        tmp_path / f"{case.name}.png",
        video_filter="scale=270:480",
    )
    assert _color_pixel_count(preview, "yellow") > 25


def test_export_visual_controls_change_real_rendered_frames(
    source_media: dict[str, Path],
    tmp_path: Path,
) -> None:
    source = source_media["h264_aac.mp4"]
    source_frame = _extract_frame(
        source,
        tmp_path / "style-source.png",
        video_filter="scale=360:-2:force_original_aspect_ratio=decrease,"
        "pad=360:640:(360-iw)/2:(640-ih)/2,format=rgb24",
    )
    style_cases = (
        ("low-small-yellow", 6, 60, "&H0000FFFF", "yellow"),
        ("middle-medium-white", 16, 100, "&H00FFFFFF", "white"),
        ("high-large-cyan", 32, 140, "&H00FFFF00", "cyan"),
        ("safe-top-medium-yellow", 95, 100, "&H0000FFFF", "yellow"),
    )
    signatures: dict[str, VisualSignature] = {}

    for name, position, size, ass_color, expected_color in style_cases:
        output = _render_variant(
            source,
            tmp_path / name,
            resolution="360x640",
            subtitle_settings={
                "subtitle_position": position,
                "subtitle_size": size,
                "max_subtitle_lines": 2,
                "subtitle_color": ass_color,
                "shadow_strength": 2,
                "karaoke_enabled": False,
                "highlight_style": "static",
            },
        )
        frame = _extract_frame(output, tmp_path / f"{name}.png")
        signatures[name] = _visual_signature(frame, source_frame)
        assert _color_pixel_count(frame, expected_color) > 20

    low = signatures["low-small-yellow"]
    middle = signatures["middle-medium-white"]
    high = signatures["high-large-cyan"]
    safe_top = signatures["safe-top-medium-yellow"]
    assert safe_top.centroid_y < high.centroid_y < middle.centroid_y < low.centroid_y
    assert 20 <= safe_top.bounding_box[1] < 70
    assert low.pixel_count < middle.pixel_count < high.pixel_count


def test_three_line_export_renders_three_bounded_rows(
    source_media: dict[str, Path],
    tmp_path: Path,
) -> None:
    """REGRESSION: the three-line UI choice must survive the real FFmpeg export."""
    source = source_media["h264_aac.mp4"]
    artifact_dir = tmp_path / "three-line-export"
    subtitle_text = "ΒΑΛΤΕ ΥΠΟΘΕΣΕΙΣ ΚΑΙ ΕΛΑΤΕ ΝΑ ΦΤΙΑΞΟΥΜΕ ΜΙΑ ΔΥΝΑΤΗ ΟΜΑΔΑ"
    _write_srt(artifact_dir, source.stem, subtitle_text)

    output = video_processing.generate_video_variant(
        "three-line-real-export",
        source,
        artifact_dir,
        "360x640",
        ExportJobStore("media-test-user"),
        "media-test-user",
        subtitle_settings={
            "subtitle_position": 16,
            "subtitle_size": 100,
            "max_subtitle_lines": 3,
            "subtitle_color": "&H0000FFFF",
            "shadow_strength": 2,
            "karaoke_enabled": False,
            "highlight_style": "static",
        },
    )

    ass_path = artifact_dir / f"{source.stem}.ass"
    dialogue_text = [
        line.rsplit(",,", maxsplit=1)[-1]
        for line in ass_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("Dialogue:")
    ]
    assert dialogue_text
    assert any(text.count("\\N") == 2 for text in dialogue_text)
    assert all(text.count("\\N") <= 2 for text in dialogue_text)
    visible_dialogue_text = [
        re.sub(r"^\{\\an8\\pos\(\d+,\d+\)\}", "", text)
        for text in dialogue_text
    ]
    assert " ".join(
        text.replace("\\N", " ") for text in visible_dialogue_text
    ).split() == subtitle_text.split()

    _decode_entire_export(output)
    baseline = _extract_frame(
        source,
        tmp_path / "three-line-source.png",
        video_filter="scale=360:-2:force_original_aspect_ratio=decrease,"
        "pad=360:640:(360-iw)/2:(640-ih)/2,format=rgb24",
    )
    rendered = _extract_frame(output, tmp_path / "three-line-rendered.png")
    signature = _visual_signature(rendered, baseline)

    assert _color_pixel_count(rendered, "yellow") > 25
    assert signature.bounding_box[3] - signature.bounding_box[1] >= 45
    assert 0 <= signature.bounding_box[0] < signature.bounding_box[2] < 360
    assert 0 <= signature.bounding_box[1] < signature.bounding_box[3] < 640


def test_ten_minute_export_preserves_duration_decode_and_subtitle_position(
    tmp_path: Path,
) -> None:
    """REGRESSION: the ten-minute upload ceiling must be exportable end to end."""
    source = tmp_path / "ten-minute-source.mp4"
    _run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i",
            f"color=c=0x101820:s=180x320:r=1:d={MAX_DURATION_SECONDS}",
            "-f", "lavfi", "-i",
            f"sine=frequency=440:sample_rate=16000:duration={MAX_DURATION_SECONDS}",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "32k", str(source),
        ],
    )

    artifact_dir = tmp_path / "ten-minute-artifacts"
    artifact_dir.mkdir()
    (artifact_dir / f"{source.stem}.srt").write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nΣΤΑΘΕΡΗ ΘΕΣΗ\n\n"
        "2\n00:04:59,000 --> 00:05:02,000\nΣΤΑΘΕΡΗ ΘΕΣΗ\n\n"
        "3\n00:09:58,000 --> 00:10:00,000\nΣΤΑΘΕΡΗ ΘΕΣΗ\n",
        encoding="utf-8",
    )

    output = video_processing.generate_video_variant(
        "ten-minute-real-export",
        source,
        artifact_dir,
        "360x640",
        ExportJobStore("media-test-user"),
        "media-test-user",
        subtitle_settings={
            "subtitle_position": 32,
            "subtitle_size": 100,
            "max_subtitle_lines": 2,
            "subtitle_color": "&H0000FFFF",
            "shadow_strength": 2,
            "karaoke_enabled": False,
            "highlight_style": "static",
        },
    )

    output_probe = _probe(output)
    output_video = _stream(output_probe, "video")
    output_audio = _stream(output_probe, "audio")
    assert output_video is not None
    assert output_video.get("codec_name") == "h264"
    assert output_video.get("pix_fmt") == "yuv420p"
    assert output_video.get("width") == 360
    assert output_video.get("height") == 640
    assert output_audio is not None and output_audio.get("codec_name") == "aac"
    assert abs(_duration(output_probe) - MAX_DURATION_SECONDS) <= 0.35
    _decode_entire_export(output)

    signatures: list[VisualSignature] = []
    for index, timestamp in enumerate((1.0, 300.0, 599.0)):
        baseline = _extract_frame(
            source,
            tmp_path / f"ten-minute-source-{index}.png",
            timestamp_seconds=timestamp,
            video_filter="scale=360:-2:force_original_aspect_ratio=decrease,"
            "pad=360:640:(360-iw)/2:(640-ih)/2,format=rgb24",
        )
        rendered = _extract_frame(
            output,
            tmp_path / f"ten-minute-rendered-{index}.png",
            timestamp_seconds=timestamp,
        )
        signature = _visual_signature(rendered, baseline)
        signatures.append(signature)
        assert _color_pixel_count(rendered, "yellow") > 25
        assert signature.centroid_y < rendered.height * 0.75

    centroid_spread = max(item.centroid_y for item in signatures) - min(
        item.centroid_y for item in signatures
    )
    assert centroid_spread <= 2.0


def test_watermark_toggle_changes_only_the_requested_real_export(
    source_media: dict[str, Path],
    tmp_path: Path,
) -> None:
    assert settings.watermark_path.exists(), f"Missing watermark fixture: {settings.watermark_path}"
    source = source_media["h264_aac.mp4"]
    frames: dict[bool, Image.Image] = {}

    for enabled in (False, True):
        output = _render_variant(
            source,
            tmp_path / f"watermark-{enabled}",
            resolution="360x640",
            subtitle_settings={
                "subtitle_position": 32,
                "subtitle_size": 70,
                "subtitle_color": "&H00FFFFFF",
                "karaoke_enabled": False,
                "watermark_enabled": enabled,
            },
        )
        _decode_entire_export(output)
        frames[enabled] = _extract_frame(output, tmp_path / f"watermark-{enabled}.png")

    bottom_right = (250, 500, 340, 630)
    assert _mean_absolute_difference(frames[False], frames[True], bottom_right) > 1.0


def test_demo_export_matches_golden_subtitle_geometry(tmp_path: Path) -> None:
    required = (
        DEMO_VIDEO,
        DEMO_GOLDEN_VIDEO,
        DEMO_ARTIFACTS / "demo.srt",
        DEMO_ARTIFACTS / "demo.ass",
    )
    missing = [path for path in required if not path.exists()]
    assert not missing, f"Golden export fixtures are missing: {missing}"

    artifact_dir = tmp_path / "demo-golden"
    artifact_dir.mkdir()
    shutil.copy2(DEMO_ARTIFACTS / "demo.srt", artifact_dir / "demo.srt")
    shutil.copy2(DEMO_ARTIFACTS / "demo.ass", artifact_dir / "demo.ass")
    candidate = video_processing.generate_video_variant(
        "demo-golden-export",
        DEMO_VIDEO,
        artifact_dir,
        "1080x1920",
        ExportJobStore("media-test-user", {"subtitle_size": 100}),
        "media-test-user",
    )
    _decode_entire_export(candidate)

    source_frame = _extract_frame(
        DEMO_VIDEO,
        tmp_path / "demo-source.png",
        timestamp_seconds=DEMO_FRAME_TIMESTAMP_SECONDS,
        video_filter="scale=1080:-2:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(1080-iw)/2:(1920-ih)/2,format=rgb24",
    )
    golden_frame = _extract_frame(
        DEMO_GOLDEN_VIDEO,
        tmp_path / "demo-golden.png",
        timestamp_seconds=DEMO_FRAME_TIMESTAMP_SECONDS,
    )
    candidate_frame = _extract_frame(
        candidate,
        tmp_path / "demo-candidate.png",
        timestamp_seconds=DEMO_FRAME_TIMESTAMP_SECONDS,
    )

    subtitle_crop = (100, 1150, 980, 1800)
    golden = _visual_signature(golden_frame, source_frame, crop=subtitle_crop)
    actual = _visual_signature(candidate_frame, source_frame, crop=subtitle_crop)
    assert golden.pixel_count > 15_000
    assert actual.pixel_count > 15_000
    assert 0.55 <= actual.pixel_count / golden.pixel_count <= 1.55
    assert all(
        abs(actual_coordinate - golden_coordinate) <= 25
        for actual_coordinate, golden_coordinate in zip(
            actual.bounding_box,
            golden.bounding_box,
            strict=True,
        )
    )
    assert abs(actual.centroid_x - golden.centroid_x) <= 25
    assert abs(actual.centroid_y - golden.centroid_y) <= 25


def test_corrupt_media_fails_without_publishing_an_export(tmp_path: Path) -> None:
    corrupt_source = tmp_path / "corrupt.mov"
    corrupt_source.write_bytes(b"not a media container")
    artifact_dir = tmp_path / "corrupt-artifacts"
    _write_srt(artifact_dir, corrupt_source.stem)

    with pytest.raises(subprocess.CalledProcessError):
        video_processing.generate_video_variant(
            "corrupt-real-media",
            corrupt_source,
            artifact_dir,
            "360x640",
            ExportJobStore("media-test-user"),
            "media-test-user",
            subtitle_settings={"karaoke_enabled": False},
        )

    output = artifact_dir / "processed_360x640.mp4"
    assert not output.exists() or output.stat().st_size == 0
