"""Focused execution steps for the video processing pipeline."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from backend.app.core import metrics
from backend.app.core.config import settings
from backend.app.core.errors import ProviderDispatchAlreadyClaimedError
from backend.app.services import (
    artifact_manager,
    ffmpeg_utils,
    pricing,
    social_intelligence,
    subtitle_renderer,
    subtitles,
)
from backend.app.services.social_intelligence import SocialCopy
from backend.app.services.styles import SubtitleHighlightStyle, SubtitleStyle
from backend.app.services.subtitle_types import Cue
from backend.app.services.transcription.base import Transcriber
from backend.app.services.usage_ledger import ChargePlan, UsageLedgerStore

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, float], None]


@dataclass
class PipelineOptions:
    input_path: Path
    destination: Path
    style: SubtitleStyle
    transcriber: Transcriber
    provider_name: str
    selected_model: str
    language: str | None
    openai_api_key: str | None
    generate_social_copy: bool
    artifact_dir: Path | None
    use_hw_accel: bool
    progress_callback: ProgressCallback | None
    check_cancelled: Callable[[], None] | None
    transcription_only: bool
    output_width: int | None
    output_height: int | None
    media_probe: ffmpeg_utils.MediaProbe | None
    best_of: int | None
    temperature: float | None
    chunk_length: int | None
    condition_on_previous_text: bool | None
    initial_prompt: str | None
    vad_filter: bool | None
    vad_parameters: dict[str, Any] | None
    video_crf: int | None
    video_preset: str | None
    audio_bitrate: str | None
    watermark_enabled: bool
    audio_copy: bool | None
    ledger_store: UsageLedgerStore | None
    charge_plan: ChargePlan | None
    persist_preview_asset: Callable[[Path, Path], None]
    resolve_ass_highlight_style: Callable[
        [SubtitleHighlightStyle, list[Cue] | None],
        str,
    ]
    lock_provider_transcription: Callable[..., AbstractContextManager[Any]]
    provider_slot_weight: Callable[[float | None], int]
    timings: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineResult:
    transcript_text: str
    social_copy: SocialCopy | None


def _notify(options: PipelineOptions, message: str, progress: float) -> None:
    if options.progress_callback is not None:
        options.progress_callback(message, progress)


def _check_cancelled(options: PipelineOptions) -> None:
    if options.check_cancelled is not None:
        options.check_cancelled()


def _probe_input(options: PipelineOptions) -> tuple[float, bool]:
    resolved_audio_copy = options.audio_copy if options.audio_copy is not None else False
    if options.progress_callback is None and options.audio_copy is not None:
        return 0.0, resolved_audio_copy
    try:
        probe = options.media_probe or ffmpeg_utils.probe_media(options.input_path)
        duration = probe.duration_s if probe.duration_s is not None and probe.duration_s > 0 else 0.0
        if options.audio_copy is None:
            resolved_audio_copy = probe.audio_is_aac
        return duration, resolved_audio_copy
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("Could not probe input media %s: %s", options.input_path, exc)
        return 0.0, resolved_audio_copy


def _extract_audio(
    options: PipelineOptions,
    *,
    scratch: Path,
    total_duration: float,
) -> Path:
    def report(progress: float) -> None:
        _notify(
            options,
            f"Extracting Audio ({int(progress)}%)...",
            progress * 0.05,
        )

    _notify(options, "Extracting audio...", 0.0)
    _check_cancelled(options)
    with metrics.measure_time(options.timings, "extract_audio_s"):
        return subtitles.extract_audio(
            options.input_path,
            output_dir=scratch,
            check_cancelled=options.check_cancelled,
            progress_callback=report if total_duration else None,
            total_duration=total_duration,
        )


def _transcription_kwargs(
    options: PipelineOptions,
    *,
    total_duration: float,
) -> dict[str, Any]:
    def report(progress: float) -> None:
        _notify(
            options,
            f"Transcribing ({int(progress)}%)...",
            5.0 + (progress * 0.6),
        )

    return {
        "best_of": options.best_of,
        "total_duration": total_duration,
        "openai_api_key": options.openai_api_key,
        "chunk_length": options.chunk_length,
        "condition_on_previous_text": options.condition_on_previous_text,
        "initial_prompt": options.initial_prompt,
        "vad_filter": options.vad_filter if options.vad_filter is not None else True,
        "vad_parameters": options.vad_parameters,
        "temperature": options.temperature,
        "progress_callback": report if total_duration > 0 else None,
        "check_cancelled": options.check_cancelled,
    }


def _claim_paid_dispatch(options: PipelineOptions) -> None:
    ledger_store = options.ledger_store
    charge_plan = options.charge_plan
    if ledger_store is None or charge_plan is None:
        return
    transcription_charge = charge_plan.transcription
    if transcription_charge is None:
        return
    if getattr(transcription_charge, "estimated_cost_usd", 0.0) <= 0:
        return
    if not ledger_store.mark_dispatched(transcription_charge):
        raise ProviderDispatchAlreadyClaimedError(
            "Paid provider dispatch is already in progress",
        )


def _dispatch_transcription(
    options: PipelineOptions,
    *,
    audio_path: Path,
    scratch: Path,
    transcribe_kwargs: dict[str, Any],
) -> tuple[Path, list[Cue]]:
    _claim_paid_dispatch(options)
    return options.transcriber.transcribe(
        audio_path,
        output_dir=scratch,
        language=options.language or settings.whisper_language,
        model=options.selected_model,
        **transcribe_kwargs,
    )


def _transcribe_audio(
    options: PipelineOptions,
    *,
    audio_path: Path,
    scratch: Path,
    total_duration: float,
) -> tuple[Path, list[Cue]]:
    _notify(options, "Transcribing audio...", 5.0)
    _check_cancelled(options)
    kwargs = _transcription_kwargs(options, total_duration=total_duration)
    with metrics.measure_time(options.timings, "transcribe_s"):
        if options.provider_name != "elevenlabs":
            return _dispatch_transcription(
                options,
                audio_path=audio_path,
                scratch=scratch,
                transcribe_kwargs=kwargs,
            )
        _notify(options, "Waiting for transcription capacity...", 5.0)
        with options.lock_provider_transcription(
            slots_required=options.provider_slot_weight(total_duration),
        ):
            return _dispatch_transcription(
                options,
                audio_path=audio_path,
                scratch=scratch,
                transcribe_kwargs=kwargs,
            )


def _finalize_transcription_charge(
    options: PipelineOptions,
    *,
    total_duration: float,
) -> None:
    ledger_store = options.ledger_store
    charge_plan = options.charge_plan
    if ledger_store is None or charge_plan is None:
        return
    transcription_charge = charge_plan.transcription
    if transcription_charge is None:
        return

    duration_seconds = total_duration if total_duration > 0 else 0.0
    tier = transcription_charge.tier or settings.default_transcribe_tier
    credits = (
        pricing.credits_for_video_duration(duration_seconds)
        if duration_seconds > 0
        else transcription_charge.reserved_credits
    )
    cost_usd = pricing.stt_provider_cost_usd(
        tier=tier,
        duration_seconds=duration_seconds,
        provider=options.provider_name,
        model=options.selected_model,
    )
    ledger_store.finalize(
        transcription_charge,
        credits_charged=credits,
        cost_usd=cost_usd,
        units={
            "audio_seconds": duration_seconds,
            "model": options.selected_model,
            "provider": options.provider_name,
        },
    )


def _style_subtitles(
    options: PipelineOptions,
    *,
    srt_path: Path,
    cues: list[Cue],
) -> Path:
    _notify(options, "Styling...", 65.0)
    with metrics.measure_time(options.timings, "style_subs_s"):
        highlight_style = options.resolve_ass_highlight_style(
            options.style.highlight_style,
            cues,
        )
        return subtitle_renderer.create_styled_subtitle_file(
            srt_path,
            cues=cues,
            subtitle_position=options.style.position,
            max_lines=options.style.max_lines,
            shadow_strength=options.style.shadow_strength,
            primary_color=options.style.primary_color,
            highlight_style=highlight_style,
            font_size=options.style.font_size,
            play_res_x=settings.default_width,
            play_res_y=settings.default_height,
        )


def _encode_progress(options: PipelineOptions, progress: float) -> None:
    _notify(
        options,
        f"Encoding ({int(progress)}%)...",
        80.0 + (progress * 0.2),
    )


def _encode_video(
    options: PipelineOptions,
    *,
    ass_path: Path,
    total_duration: float,
    resolved_audio_copy: bool,
    use_hw_accel: bool,
) -> None:
    ffmpeg_utils.run_ffmpeg_with_subs(
        options.input_path,
        ass_path,
        options.destination,
        video_crf=options.video_crf or settings.default_video_crf,
        video_preset=options.video_preset or settings.default_video_preset,
        audio_bitrate=options.audio_bitrate or settings.default_audio_bitrate,
        audio_copy=resolved_audio_copy,
        use_hw_accel=use_hw_accel,
        progress_callback=((lambda progress: _encode_progress(options, progress)) if total_duration > 0 else None),
        total_duration=total_duration,
        output_width=options.output_width,
        output_height=options.output_height,
        watermark_enabled=options.watermark_enabled,
        check_cancelled=options.check_cancelled,
    )


def _render_video(
    options: PipelineOptions,
    *,
    ass_path: Path,
    total_duration: float,
    resolved_audio_copy: bool,
) -> None:
    if options.transcription_only:
        return
    _notify(options, "Rendering...", 80.0)
    try:
        _encode_video(
            options,
            ass_path=ass_path,
            total_duration=total_duration,
            resolved_audio_copy=resolved_audio_copy,
            use_hw_accel=options.use_hw_accel,
        )
    except subprocess.CalledProcessError as exc:
        if not options.use_hw_accel:
            raise
        logger.warning(
            "Hardware acceleration failed; retrying with software encoding: %s",
            exc,
        )
        _encode_video(
            options,
            ass_path=ass_path,
            total_duration=total_duration,
            resolved_audio_copy=resolved_audio_copy,
            use_hw_accel=False,
        )


def _persist_pipeline_artifacts(
    options: PipelineOptions,
    *,
    audio_path: Path,
    srt_path: Path,
    ass_path: Path,
    transcript_text: str,
    social_copy: SocialCopy | None,
    cues: list[Cue],
) -> None:
    if options.transcription_only:
        options.persist_preview_asset(options.input_path, options.destination)
    if options.artifact_dir is None:
        return
    artifact_manager.persist_artifacts(
        options.artifact_dir,
        audio_path,
        srt_path,
        ass_path,
        transcript_text,
        social_copy,
        cues,
        max_subtitle_lines=options.style.max_lines,
        subtitle_size=options.style.font_size,
    )
    if options.destination.exists() and options.artifact_dir != options.destination.parent:
        try:
            shutil.copy2(
                options.destination,
                options.artifact_dir / options.destination.name,
            )
        except FileNotFoundError:
            logger.warning(
                "Rendered output disappeared before artifact copy: %s",
                options.destination,
            )


def run_pipeline_steps(options: PipelineOptions) -> PipelineResult:
    """Run the media pipeline as a linear series of independently tested steps."""
    with tempfile.TemporaryDirectory() as scratch_dir:
        scratch = Path(scratch_dir)
        scratch.mkdir(parents=True, exist_ok=True)
        _check_cancelled(options)
        total_duration, resolved_audio_copy = _probe_input(options)
        audio_path = _extract_audio(
            options,
            scratch=scratch,
            total_duration=total_duration,
        )
        srt_path, cues = _transcribe_audio(
            options,
            audio_path=audio_path,
            scratch=scratch,
            total_duration=total_duration,
        )
        _finalize_transcription_charge(
            options,
            total_duration=total_duration,
        )
        _check_cancelled(options)
        ass_path = _style_subtitles(options, srt_path=srt_path, cues=cues)
        transcript_text = subtitles.cues_to_text(cues)
        if options.generate_social_copy:
            _notify(options, "Social Copy...", 70.0)
        social_copy = social_intelligence.build_social_copy(transcript_text) if options.generate_social_copy else None
        _render_video(
            options,
            ass_path=ass_path,
            total_duration=total_duration,
            resolved_audio_copy=resolved_audio_copy,
        )
        _notify(options, "Finalizing...", 95.0)
        _persist_pipeline_artifacts(
            options,
            audio_path=audio_path,
            srt_path=srt_path,
            ass_path=ass_path,
            transcript_text=transcript_text,
            social_copy=social_copy,
            cues=cues,
        )
    return PipelineResult(
        transcript_text=transcript_text,
        social_copy=social_copy,
    )
