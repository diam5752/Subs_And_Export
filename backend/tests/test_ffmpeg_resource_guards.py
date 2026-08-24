from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from backend.app.core.config import settings
from backend.app.services import ffmpeg_utils, subtitles


class HangingProcess:
    def __init__(self) -> None:
        self.stderr = object()
        self.returncode: int | None = None
        self.pid = None
        self.killed = False

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


class CompletedProcess(HangingProcess):
    def __init__(self) -> None:
        super().__init__()
        self.stderr = None
        self.returncode = 0


def test_ffmpeg_thread_count_caps_shared_host_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: each render previously requested every visible CPU core.
    monkeypatch.setattr(ffmpeg_utils.os, "cpu_count", lambda: 32)
    assert ffmpeg_utils.resolve_ffmpeg_thread_count() == 2
    assert ffmpeg_utils.resolve_ffmpeg_thread_count(1) == 1
    assert ffmpeg_utils.resolve_ffmpeg_thread_count(32) == 2


def test_run_ffmpeg_timeout_kills_hung_process_group(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = HangingProcess()
    popen_kwargs: dict[str, Any] = {}

    def fake_popen(*_args, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    ticks = iter([0.0, 0.0, 0.02, 0.02])
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(ffmpeg_utils.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ffmpeg_utils.select, "select", lambda *_args: ([], [], []))
    monkeypatch.setattr(ffmpeg_utils.time, "monotonic", lambda: next(ticks, 0.02))

    with pytest.raises(TimeoutError, match="exceeded timeout"):
        ffmpeg_utils.run_ffmpeg_with_subs(
            Path("input.mp4"),
            Path("captions.ass"),
            Path("output.mp4"),
            video_crf=20,
            video_preset="veryfast",
            audio_bitrate="128k",
            audio_copy=False,
            timeout_seconds=0.01,
        )

    assert process.killed is True
    assert popen_kwargs["start_new_session"] is True


def test_run_ffmpeg_command_bounds_decode_filter_and_encode_threads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = CompletedProcess()
    command: list[str] = []

    def fake_popen(cmd, **_kwargs):
        command.extend(cmd)
        return process

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(ffmpeg_utils.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(ffmpeg_utils.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ffmpeg_utils.time, "sleep", lambda _seconds: None)

    ffmpeg_utils.run_ffmpeg_with_subs(
        Path("input.mp4"),
        Path("captions.ass"),
        Path("output.mp4"),
        video_crf=20,
        video_preset="veryfast",
        audio_bitrate="128k",
        audio_copy=False,
        timeout_seconds=1.0,
    )

    thread_values = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "-threads"
    ]
    progress_index = command.index("-progress")
    filter_index = command.index("-filter_threads")
    complex_filter_index = command.index("-filter_complex_threads")
    assert thread_values == ["2", "2"]
    assert command[filter_index + 1] == "2"
    assert command[complex_filter_index + 1] == "2"
    assert command[progress_index + 1] == "pipe:2"
    assert "-nostats" in command
    assert "-nostdin" in command


def test_run_ffmpeg_lowers_encoder_priority_on_shared_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The encoder may use idle CPU, but interactive services must preempt it."""
    process = CompletedProcess()
    process.pid = 4242
    priority_calls: list[tuple[int, int, int]] = []

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(ffmpeg_utils.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(ffmpeg_utils.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        ffmpeg_utils.os,
        "setpriority",
        lambda which, who, priority: priority_calls.append((which, who, priority)),
    )

    ffmpeg_utils.run_ffmpeg_with_subs(
        Path("input.mp4"),
        Path("captions.ass"),
        Path("output.mp4"),
        video_crf=20,
        video_preset="veryfast",
        audio_bitrate="128k",
        audio_copy=False,
        timeout_seconds=1.0,
    )

    assert priority_calls == [(os.PRIO_PROCESS, 4242, 10)]


def test_extract_audio_timeout_kills_hung_process_and_bounds_decoder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    process = HangingProcess()
    command: list[str] = []
    ticks = iter([0.0, 0.0, 0.02, 0.02])

    def fake_popen(cmd, **_kwargs):
        command.extend(cmd)
        return process

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(ffmpeg_utils.os, "cpu_count", lambda: 64)
    monkeypatch.setattr(subtitles.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(subtitles.select, "select", lambda *_args: ([], [], []))
    monkeypatch.setattr(subtitles.time, "monotonic", lambda: next(ticks, 0.02))

    with pytest.raises(TimeoutError, match="Audio extraction exceeded"):
        subtitles.extract_audio(
            Path("input.mp4"),
            output_dir=tmp_path,
            timeout_seconds=0.01,
        )

    progress_index = command.index("-progress")
    thread_index = command.index("-threads")
    assert process.killed is True
    assert command[thread_index + 1] == "2"
    assert command[progress_index + 1] == "pipe:2"
    assert "-nostats" in command
    assert "-nostdin" in command


def test_programmatic_progress_timestamps_are_parsed() -> None:
    line = "out_time=00:00:05.123456"
    ffmpeg_match = ffmpeg_utils.TIME_PATTERN.search(line)
    extraction_match = subtitles.TIME_PATTERN.search(line)
    assert ffmpeg_match is not None
    assert extraction_match is not None
    assert ffmpeg_match.groups() == ("00", "00", "05.123456")
    assert extraction_match.groups() == ("00", "00", "05.123456")


def test_timeout_resolvers_reject_invalid_values() -> None:
    with pytest.raises(ValueError, match="positive finite"):
        ffmpeg_utils.resolve_ffmpeg_timeout_seconds(
            total_duration=None,
            timeout_seconds=float("nan"),
        )
    with pytest.raises(ValueError, match="positive finite"):
        subtitles.resolve_audio_extraction_timeout_seconds(
            total_duration=None,
            timeout_seconds=0,
        )
