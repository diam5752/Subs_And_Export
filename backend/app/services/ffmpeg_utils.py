"""FFMPEG wrappers and media probing utilities."""

from __future__ import annotations

import json
import logging
import math
import os
import platform
import re
import signal
import subprocess
import time
from collections import deque
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.app.core.config import settings
from backend.app.core.media_capacity import lock_media_render, render_slot_weight
from backend.app.services.media_process_monitor import monitor_media_process
from backend.app.services.media_process_monitor import select as select

logger = logging.getLogger(__name__)

# Support both legacy human-readable stats and FFmpeg's newline-delimited
# programmatic progress output. The latter uses microsecond precision.
TIME_PATTERN = re.compile(
    r"(?:time|out_time)=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)",
)
_FFMPEG_MAX_THREADS = 2
_MEDIA_PROCESS_NICE = 10


@dataclass(frozen=True)
class MediaProbe:
    duration_s: float | None
    audio_codec: str | None
    has_video: bool = False

    @property
    def audio_is_aac(self) -> bool:
        return (self.audio_codec or "").lower() == "aac"


class FFmpegRenderError(subprocess.CalledProcessError):
    """Preserve FFmpeg diagnostics internally without exposing the command."""

    def __init__(self, returncode: int, cmd: list[str], stderr: str) -> None:
        super().__init__(returncode, cmd, output=None, stderr=stderr)

    def __str__(self) -> str:
        return "Video rendering failed."


def _probe_media_command(source: str, *, inspect_all_streams: bool = False) -> list[str]:
    command = [
        "ffprobe",
        "-v",
        "error",
    ]
    if not inspect_all_streams:
        command.extend(["-select_streams", "a:0"])
    stream_entries = "codec_name,codec_type" if inspect_all_streams else "codec_name"
    command.extend(
        [
            "-show_entries",
            f"format=duration:stream={stream_entries}",
            "-of",
            "json",
            source,
        ],
    )
    return command


def _probe_duration(probe_payload: dict[object, object]) -> float | None:
    try:
        format_payload = probe_payload.get("format")
        duration_raw = format_payload.get("duration") if isinstance(format_payload, dict) else None
        if duration_raw is not None:
            return float(duration_raw)
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def _probe_streams(probe_payload: dict[object, object]) -> list[dict[object, object]]:
    streams = probe_payload.get("streams") or []
    if not isinstance(streams, list):
        return []
    return [stream for stream in streams if isinstance(stream, dict)]


def _probe_codec_name(stream: dict[object, object] | None) -> str | None:
    codec_name = stream.get("codec_name") if stream is not None else None
    if isinstance(codec_name, str) and codec_name.strip():
        return codec_name.strip().lower()
    return None


def _probe_audio_codec(probe_payload: dict[object, object]) -> str | None:
    streams = _probe_streams(probe_payload)
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )
    # Preserve compatibility with older/mock payloads that omitted codec_type.
    return _probe_codec_name(audio_stream or (streams[0] if streams else None))


def _probe_has_video(probe_payload: dict[object, object]) -> bool:
    return any(stream.get("codec_type") == "video" for stream in _probe_streams(probe_payload))


def _media_probe_from_payload(probe_payload: object) -> MediaProbe:
    if not isinstance(probe_payload, dict):
        return MediaProbe(duration_s=None, audio_codec=None)
    return MediaProbe(
        duration_s=_probe_duration(probe_payload),
        audio_codec=_probe_audio_codec(probe_payload),
        has_video=_probe_has_video(probe_payload),
    )


def probe_media(input_path: Path) -> MediaProbe:
    result = subprocess.run(
        _probe_media_command(str(input_path)),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30.0,  # Security: Prevent infinite hang if ffprobe stalls
    )
    return _media_probe_from_payload(json.loads(result.stdout or "{}"))


def probe_media_bytes(media_bytes: bytes) -> MediaProbe:
    """Probe bounded media held in memory without creating a server-side file."""
    if not media_bytes:
        raise ValueError("Audio body is empty")
    result = subprocess.run(
        _probe_media_command("pipe:0", inspect_all_streams=True),
        input=media_bytes,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30.0,
    )
    payload = json.loads(result.stdout.decode("utf-8") or "{}")
    return _media_probe_from_payload(payload)


def input_audio_is_aac(input_path: Path) -> bool:
    try:
        return probe_media(input_path).audio_is_aac
    except Exception as exc:
        logger.warning("Failed to probe audio codec: %s", exc)
        return False


def build_filtergraph(
    ass_path: Path,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
    watermark_enabled: bool = False,
) -> str:
    ass_file = ass_path.as_posix().replace("'", r"\'")
    ass_filter = f"ass='{ass_file}'"

    logger.debug(
        "FFmpeg filtergraph target dimensions: width=%s height=%s",
        target_width,
        target_height,
    )

    # If no target dimensions, skip scaling - keep original resolution
    if target_width is None and target_height is None:
        return f"format=yuv420p,{ass_filter}"

    width = target_width or settings.default_width
    height = target_height or settings.default_height
    # Constrain both axes. Width-only scaling makes extra-tall phone videos
    # taller than the requested canvas, so the following pad filter fails.
    scale = f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2"
    pad = f"pad={width}:{height}:({width}-iw)/2:({height}-ih)/2"
    graph = ",".join([scale, pad, "format=yuv420p"])

    if watermark_enabled and settings.watermark_path.exists():
        # Clean path for FFmpeg
        wm_path = settings.watermark_path.as_posix().replace("'", r"\'")
        # Dynamic watermark sizing (15% of video width)
        wm_w = int(width * 0.15)
        wm_overlay = (
            f"movie='{wm_path}',scale={wm_w}:-1:flags=lanczos,format=rgba[wm];"
            f"[base][wm]overlay=main_w-overlay_w-40:main_h-overlay_h-40"
        )
        graph = f"{graph} [base]; {wm_overlay}, {ass_filter}"
    else:
        graph = f"{graph}, {ass_filter}"

    return graph


def resolve_ffmpeg_thread_count(requested_threads: int | None = None) -> int:
    """Bound each FFmpeg decode/filter/encode pool on the shared VM."""
    available_threads = max(1, os.cpu_count() or 1)
    if requested_threads is None:
        return min(available_threads, _FFMPEG_MAX_THREADS)
    if isinstance(requested_threads, bool) or not isinstance(requested_threads, int) or requested_threads <= 0:
        raise ValueError("FFmpeg thread count must be a positive integer")
    return min(
        requested_threads,
        available_threads,
        _FFMPEG_MAX_THREADS,
    )


def resolve_ffmpeg_timeout_seconds(
    *,
    total_duration: float | None,
    timeout_seconds: float | None = None,
) -> float:
    """Return a strict render deadline with a generous slow-host allowance."""
    if timeout_seconds is not None:
        resolved = float(timeout_seconds)
        if not math.isfinite(resolved) or resolved <= 0:
            raise ValueError("FFmpeg timeout must be a positive finite number")
        return resolved
    if total_duration is not None:
        duration = float(total_duration)
        if math.isfinite(duration) and duration > 0:
            return max(1800.0, duration * 20.0)
    return 3600.0


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Kill the isolated FFmpeg process group without touching unrelated work."""
    if process.poll() is not None:
        return
    pid = getattr(process, "pid", None)
    if isinstance(pid, int) and pid > 0 and platform.system() != "Windows":
        try:
            os.killpg(pid, signal.SIGKILL)
            return
        except OSError:
            pass
    process.kill()


def lower_media_process_priority(process: subprocess.Popen[str]) -> None:
    """Let interactive web/database work preempt an idle-time encoder."""
    process_id = getattr(process, "pid", None)
    if process_id is None or not hasattr(os, "setpriority") or not hasattr(os, "PRIO_PROCESS"):
        return
    try:
        os.setpriority(os.PRIO_PROCESS, process_id, _MEDIA_PROCESS_NICE)
    except OSError as exc:
        logger.debug("Could not lower FFmpeg process priority: %s", exc)


def _wait_after_termination(process: subprocess.Popen[str]) -> None:
    # A completed process has already crossed the monitored poll boundary, so
    # a plain wait is immediate and also keeps lightweight test doubles valid.
    if process.poll() is not None:
        process.wait()
        return
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _base_render_command(*, input_path: Path, filtergraph: str, threads: int) -> list[str]:
    return [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-nostats",
        "-progress",
        "pipe:2",
        "-filter_threads",
        str(threads),
        "-filter_complex_threads",
        str(threads),
        "-threads",
        str(threads),
        "-i",
        str(input_path),
        "-vf",
        filtergraph,
    ]


def _video_encoder_arguments(
    *,
    threads: int,
    video_crf: int,
    video_preset: str,
    use_hw_accel: bool,
) -> list[str]:
    if use_hw_accel and platform.system() == "Darwin":
        quality = max(40, min(90, int(100 - (video_crf * 2))))
        return ["-c:v", "h264_videotoolbox", "-q:v", str(quality)]
    return [
        "-c:v",
        "libx264",
        "-preset",
        video_preset,
        "-crf",
        str(video_crf),
        "-threads",
        str(threads),
        "-tune",
        "film",
    ]


def _audio_encoder_arguments(*, audio_copy: bool, audio_bitrate: str) -> list[str]:
    if audio_copy:
        return ["-c:a", "copy"]
    return ["-c:a", "aac", "-b:a", audio_bitrate]


def _build_render_command(
    *,
    input_path: Path,
    output_path: Path,
    filtergraph: str,
    threads: int,
    video_crf: int,
    video_preset: str,
    audio_bitrate: str,
    audio_copy: bool,
    use_hw_accel: bool,
) -> list[str]:
    return [
        *_base_render_command(input_path=input_path, filtergraph=filtergraph, threads=threads),
        *_video_encoder_arguments(
            threads=threads,
            video_crf=video_crf,
            video_preset=video_preset,
            use_hw_accel=use_hw_accel,
        ),
        *_audio_encoder_arguments(audio_copy=audio_copy, audio_bitrate=audio_bitrate),
        "-movflags",
        "+faststart",
        str(output_path),
    ]


def _validate_held_render_slots(
    held_render_slots: tuple[int, ...] | None,
    *,
    slots_required: int,
) -> None:
    if held_render_slots is None:
        return
    if len(held_render_slots) < slots_required:
        raise ValueError("Held render capacity does not satisfy this render")
    if len(set(held_render_slots)) != len(held_render_slots):
        raise ValueError("Held render capacity does not satisfy this render")
    for slot_index in held_render_slots:
        if (
            isinstance(slot_index, bool)
            or not isinstance(slot_index, int)
            or slot_index < 0
            or slot_index >= settings.media_render_slots
        ):
            raise ValueError("Held render capacity does not satisfy this render")


def _run_render_process(
    *,
    command: list[str],
    resolved_timeout: float,
    check_cancelled: Callable[[], None] | None,
    progress_callback: Callable[[float], None] | None,
    total_duration: float | None,
) -> str:
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
        start_new_session=True,
    )
    lower_media_process_priority(process)
    stderr_lines: deque[str] = deque(maxlen=200)
    try:
        monitor_media_process(
            process,
            deadline=time.monotonic() + resolved_timeout,
            timeout_message=(f"FFmpeg process exceeded timeout of {resolved_timeout:.1f}s"),
            progress_pattern=TIME_PATTERN,
            check_cancelled=check_cancelled,
            progress_callback=progress_callback,
            total_duration=total_duration,
            capture_line=stderr_lines.append,
        )
        process.wait()
        if process.returncode != 0:
            logger.error(
                "FFmpeg render failed with exit code %s",
                process.returncode,
            )
            raise FFmpegRenderError(
                process.returncode,
                command,
                "".join(stderr_lines),
            )
        return "".join(stderr_lines)
    except Exception:
        terminate_process_tree(process)
        _wait_after_termination(process)
        raise


def run_ffmpeg_with_subs(
    input_path: Path,
    ass_path: Path,
    output_path: Path,
    *,
    video_crf: int,
    video_preset: str,
    audio_bitrate: str,
    audio_copy: bool,
    use_hw_accel: bool = False,
    progress_callback: Callable[[float], None] | None = None,
    total_duration: float | None = None,
    output_width: int | None = None,
    output_height: int | None = None,
    watermark_enabled: bool = False,
    check_cancelled: Callable[[], None] | None = None,
    timeout_seconds: float | None = None,
    thread_count: int | None = None,
    held_render_slots: tuple[int, ...] | None = None,
) -> str:
    resolved_timeout = resolve_ffmpeg_timeout_seconds(
        total_duration=total_duration,
        timeout_seconds=timeout_seconds,
    )
    slots_required = render_slot_weight(
        output_width,
        output_height,
        capacity=settings.media_render_slots,
    )
    requested_threads = (
        thread_count if thread_count is not None else settings.media_render_threads_per_slot * slots_required
    )
    threads = resolve_ffmpeg_thread_count(requested_threads)
    filtergraph = build_filtergraph(
        ass_path,
        target_width=output_width,
        target_height=output_height,
        watermark_enabled=watermark_enabled,
    )
    command = _build_render_command(
        input_path=input_path,
        output_path=output_path,
        filtergraph=filtergraph,
        threads=threads,
        video_crf=video_crf,
        video_preset=video_preset,
        audio_bitrate=audio_bitrate,
        audio_copy=audio_copy,
        use_hw_accel=use_hw_accel,
    )
    _validate_held_render_slots(
        held_render_slots,
        slots_required=slots_required,
    )
    render_capacity = (
        nullcontext(held_render_slots)
        if held_render_slots is not None
        else lock_media_render(slots_required=slots_required)
    )

    # Two bounded launch lanes keep normal exports moving concurrently. Each
    # normal lane may use both worker threads; the production cgroup owns the
    # aggregate CPU ceiling and niceness lets interactive API work preempt the
    # encoders. A 4K render reserves both lanes but remains capped at two total
    # threads. Export callers can hold the same lease around their atomic disk
    # reservation.
    with render_capacity:
        return _run_render_process(
            command=command,
            resolved_timeout=resolved_timeout,
            check_cancelled=check_cancelled,
            progress_callback=progress_callback,
            total_duration=total_duration,
        )
