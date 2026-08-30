"""Successful execution path for one background video-processing worker."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, cast

from ...core.auth import User
from ...core.config import settings as app_settings
from ...services.ffmpeg_utils import MediaProbe
from ...services.history import HistoryStore
from ...services.jobs import JobStore
from ...services.usage_ledger import ChargePlan, UsageLedgerStore
from .processing_state import DeletedJobError, JobCancellationError
from .settings import ProcessingSettings


@dataclass(frozen=True)
class WorkerExecutionContext:
    job_id: str
    input_path: Path
    output_path: Path
    artifact_dir: Path
    settings: ProcessingSettings
    job_store: JobStore
    history_store: HistoryStore | None
    user: User | None
    original_name: str | None
    ledger_store: UsageLedgerStore | None
    charge_plan: ChargePlan | None
    source_probe: MediaProbe | None

    @property
    def display_name(self) -> str:
        return self.original_name or self.input_path.name


@dataclass(frozen=True)
class WorkerRuntime:
    process_pipeline: Callable[..., object]
    resolve_provider: Callable[[str], str]
    resolve_video_crf: Callable[[str], int]
    probe_media: Callable[[Path], MediaProbe]
    relative_path: Callable[[Path, Path], Path]
    data_roots: Callable[[], tuple[Path, Path, Path]]
    raise_for_rejected_write: Callable[..., None]
    record_event: Callable[..., None]


class WorkerGuards:
    """Throttle progress writes and cancellation reads for one worker."""

    def __init__(self, context: WorkerExecutionContext, runtime: WorkerRuntime) -> None:
        self.context = context
        self.runtime = runtime
        self.last_update_time = 0.0
        self.last_check_time = 0.0

    def progress(self, message: str, percent: float) -> None:
        now = time.time()
        should_update = percent <= 0 or percent >= 100 or (now - self.last_update_time) >= 1.0
        if not should_update:
            return
        if not self.context.job_store.update_job_if_status(
            self.context.job_id,
            expected_statuses={"processing"},
            progress=int(percent),
            message=message,
        ):
            self.runtime.raise_for_rejected_write(
                job_store=self.context.job_store,
                job_id=self.context.job_id,
            )
        self.last_update_time = now

    def check_cancelled(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self.last_check_time < 0.5:
            return
        current_job = self.context.job_store.get_job(self.context.job_id)
        self.last_check_time = now
        if current_job is None:
            raise DeletedJobError("Job was deleted")
        if current_job.status in {"cancelling", "cancelled"}:
            raise JobCancellationError("Job cancelled by user")


def _source_probe_and_duration(
    context: WorkerExecutionContext,
    runtime: WorkerRuntime,
) -> tuple[MediaProbe | None, float | None]:
    effective_probe = context.source_probe
    try:
        if effective_probe is None:
            effective_probe = runtime.probe_media(context.input_path)
        duration = effective_probe.duration_s
        if duration is not None and duration > 0:
            return effective_probe, float(duration)
    except Exception:
        pass
    return effective_probe, None


def _processing_result_data(
    context: WorkerExecutionContext,
    *,
    final_path: Path,
    data_dir: Path,
    runtime: WorkerRuntime,
    provider: str,
    video_crf: int,
    source_duration_seconds: float | None,
) -> dict[str, object]:
    public_path = runtime.relative_path(final_path, data_dir).as_posix()
    artifact_public = runtime.relative_path(
        context.artifact_dir,
        data_dir,
    ).as_posix()
    target_width = context.settings.target_width
    target_height = context.settings.target_height
    return {
        "video_path": public_path,
        "artifacts_dir": artifact_public,
        "public_url": f"/static/{public_path}",
        "artifact_url": f"/static/{artifact_public}",
        "transcription_url": f"/static/{artifact_public}/transcription.json",
        "original_filename": context.display_name,
        "video_crf": video_crf,
        "transcribe_tier": context.settings.transcribe_tier,
        "transcribe_provider": provider,
        "output_size": final_path.stat().st_size if final_path.exists() else 0,
        "resolution": (f"{target_width}x{target_height}" if target_width and target_height else ""),
        "duration_seconds": source_duration_seconds,
        "max_subtitle_lines": context.settings.max_subtitle_lines,
        "subtitle_position": context.settings.subtitle_position,
        "subtitle_color": context.settings.subtitle_color,
        "shadow_strength": context.settings.shadow_strength,
        "highlight_style": context.settings.highlight_style,
        "subtitle_size": context.settings.subtitle_size,
        "karaoke_enabled": context.settings.karaoke_enabled,
        "watermark_enabled": context.settings.watermark_enabled,
    }


def _run_pipeline(
    context: WorkerExecutionContext,
    runtime: WorkerRuntime,
    guards: WorkerGuards,
    *,
    provider: str,
    video_crf: int,
    effective_probe: MediaProbe | None,
) -> Path:
    return cast(
        Path,
        runtime.process_pipeline(
            input_path=context.input_path,
            output_path=context.output_path,
            transcribe_tier=context.settings.transcribe_tier,
            artifact_dir=context.artifact_dir,
            video_crf=video_crf,
            initial_prompt=context.settings.context_prompt,
            transcribe_provider=provider,
            provider_model=context.settings.openai_model,
            progress_callback=guards.progress,
            output_width=context.settings.target_width,
            output_height=context.settings.target_height,
            subtitle_position=context.settings.subtitle_position,
            max_subtitle_lines=context.settings.max_subtitle_lines,
            subtitle_color=context.settings.subtitle_color,
            shadow_strength=context.settings.shadow_strength,
            highlight_style=context.settings.highlight_style,
            subtitle_size=context.settings.subtitle_size,
            karaoke_enabled=context.settings.karaoke_enabled,
            watermark_enabled=context.settings.watermark_enabled,
            check_cancelled=guards.check_cancelled,
            transcription_only=True,
            ledger_store=context.ledger_store,
            charge_plan=context.charge_plan,
            media_probe=effective_probe,
        ),
    )


@dataclass(frozen=True)
class _PreparedWorkerRun:
    guards: WorkerGuards
    provider: str
    video_crf: int
    effective_probe: MediaProbe | None
    source_duration_seconds: float | None


def _start_worker_processing(context: WorkerExecutionContext, runtime: WorkerRuntime) -> WorkerGuards:
    if not context.job_store.update_job_if_status(
        context.job_id,
        expected_statuses={"pending"},
        status="processing",
        progress=0,
        message="Starting processing...",
    ):
        runtime.raise_for_rejected_write(job_store=context.job_store, job_id=context.job_id)
    return WorkerGuards(context, runtime)


def _requested_transcription_provider(context: WorkerExecutionContext) -> str:
    return context.settings.transcribe_provider or app_settings.transcribe_tier_provider.get(
        context.settings.transcribe_tier,
        app_settings.transcribe_tier_provider[app_settings.default_transcribe_tier],
    )


def _prepare_worker_run(context: WorkerExecutionContext, runtime: WorkerRuntime) -> _PreparedWorkerRun:
    guards = _start_worker_processing(context, runtime)
    provider = runtime.resolve_provider(_requested_transcription_provider(context))
    video_crf = runtime.resolve_video_crf(context.settings.video_quality)
    effective_probe, source_duration_seconds = _source_probe_and_duration(context, runtime)
    context.artifact_dir.mkdir(parents=True, exist_ok=True)
    context.output_path.parent.mkdir(parents=True, exist_ok=True)
    return _PreparedWorkerRun(
        guards=guards,
        provider=provider,
        video_crf=video_crf,
        effective_probe=effective_probe,
        source_duration_seconds=source_duration_seconds,
    )


def _persist_worker_completion(
    context: WorkerExecutionContext,
    runtime: WorkerRuntime,
    *,
    result_data: dict[str, object],
    provider: str,
    video_crf: int,
) -> None:
    if not context.job_store.update_job_if_status(
        context.job_id,
        expected_statuses={"processing"},
        status="completed",
        progress=100,
        message="Done!",
        result_data=result_data,
    ):
        runtime.raise_for_rejected_write(job_store=context.job_store, job_id=context.job_id)
    if context.job_store.get_job(context.job_id) is None:
        raise DeletedJobError("Job was deleted")
    runtime.record_event(
        context.history_store,
        context.user,
        "process_completed",
        f"Processed {context.display_name}",
        {
            "job_id": context.job_id,
            "transcribe_tier": context.settings.transcribe_tier,
            "provider": provider,
            "video_crf": video_crf,
            "output": result_data.get("public_url"),
            "artifacts": result_data.get("artifact_url"),
        },
    )


def run_processing_success(
    context: WorkerExecutionContext,
    runtime: WorkerRuntime,
) -> None:
    """Transition pending to completed while the caller holds its workspace lock."""
    prepared = _prepare_worker_run(context, runtime)
    final_path = _run_pipeline(
        context,
        runtime,
        prepared.guards,
        provider=prepared.provider,
        video_crf=prepared.video_crf,
        effective_probe=prepared.effective_probe,
    )
    prepared.guards.check_cancelled(force=True)
    result_data = _processing_result_data(
        context,
        final_path=final_path,
        data_dir=runtime.data_roots()[0],
        runtime=runtime,
        provider=prepared.provider,
        video_crf=prepared.video_crf,
        source_duration_seconds=prepared.source_duration_seconds,
    )
    _persist_worker_completion(
        context,
        runtime,
        result_data=result_data,
        provider=prepared.provider,
        video_crf=prepared.video_crf,
    )
