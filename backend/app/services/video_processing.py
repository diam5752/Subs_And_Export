"""Video normalization and subtitle burn-in helpers."""

from __future__ import annotations

import json
import logging
import shutil
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, cast

from backend.app.core import metrics
from backend.app.core.config import settings
from backend.app.core.media_capacity import (
    lock_provider_transcription,
    provider_transcription_slot_weight,
)
from backend.app.services import (
    ffmpeg_utils,
    pricing,
    provider_clients,
    settings_utils,
    social_intelligence,
)
from backend.app.services import subtitle_renderer as subtitle_renderer
from backend.app.services import subtitles as subtitles
from backend.app.services.jobs import JobStore
from backend.app.services.social_intelligence import SocialCopy
from backend.app.services.styles import SubtitleHighlightStyle, SubtitleStyle
from backend.app.services.subtitle_types import Cue, WordTiming
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.elevenlabs_scribe import ElevenLabsScribeTranscriber
from backend.app.services.transcription.groq_cloud import GroqTranscriber
from backend.app.services.transcription.local_whisper import LocalWhisperTranscriber
from backend.app.services.transcription.mock_service import MockTranscriber
from backend.app.services.transcription.openai_cloud import OpenAITranscriber
from backend.app.services.usage_ledger import ChargePlan, UsageLedgerStore
from backend.app.services.video_pipeline_steps import (
    PipelineOptions,
    PipelineResult,
    run_pipeline_steps,
)
from backend.app.services.video_variants import (
    _encode_video_variant as _encode_video_variant,
)
from backend.app.services.video_variants import generate_video_variant as _generate_video_variant

logger = logging.getLogger(__name__)

ALLOWED_TIER_PROVIDER_OVERRIDES: dict[str, set[str]] = {
    "standard": {"mock", "groq", "local"},
    "pro": {"mock", "elevenlabs", "groq", "openai", "local"},
}
ALLOWED_HIGHLIGHT_STYLES: frozenset[str] = frozenset({"static", "karaoke", "pop", "active-graphics"})


def _normalize_highlight_style(
    value: str,
    *,
    karaoke_enabled: bool,
) -> SubtitleHighlightStyle:
    if not karaoke_enabled:
        return "static"
    normalized = value.strip().lower()
    if normalized not in ALLOWED_HIGHLIGHT_STYLES:
        raise ValueError("Unsupported subtitle highlight style")
    return cast(SubtitleHighlightStyle, normalized)


def _resolve_ass_highlight_style(
    style: SubtitleHighlightStyle,
    cues: list[Cue] | None,
) -> str:
    if style != "active-graphics":
        return style
    return "active" if cues and any(cue.words for cue in cues) else "karaoke"


def _load_persisted_cues(path: Path) -> list[Cue] | None:
    if not path.exists():
        return None
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("transcription.json must contain a list")

        return [_parse_persisted_cue(raw_cue) for raw_cue in payload]
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Could not load persisted transcription from %s: %s", path, exc)
        return None


def _required_number(value: object, *, detail: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(detail)
    return float(value)


def _parse_persisted_word(raw_word: object) -> WordTiming:
    if not isinstance(raw_word, dict):
        raise ValueError("word timing must be an object")
    text = raw_word.get("text")
    if not isinstance(text, str):
        raise ValueError("word timing fields are invalid")
    return WordTiming(
        start=_required_number(
            raw_word.get("start"),
            detail="word timing fields are invalid",
        ),
        end=_required_number(
            raw_word.get("end"),
            detail="word timing fields are invalid",
        ),
        text=text,
    )


def _parse_persisted_words(payload: object) -> list[WordTiming] | None:
    if payload is None:
        return None
    if not isinstance(payload, list):
        raise ValueError("cue words must be a list")
    return [_parse_persisted_word(raw_word) for raw_word in payload]


def _parse_persisted_cue(raw_cue: object) -> Cue:
    if not isinstance(raw_cue, dict):
        raise ValueError("transcription cue must be an object")
    text = raw_cue.get("text")
    if not isinstance(text, str):
        raise ValueError("transcription cue fields are invalid")
    return Cue(
        start=_required_number(
            raw_cue.get("start"),
            detail="transcription cue fields are invalid",
        ),
        end=_required_number(
            raw_cue.get("end"),
            detail="transcription cue fields are invalid",
        ),
        text=text,
        words=_parse_persisted_words(raw_cue.get("words")),
        position=settings_utils.parse_optional_subtitle_position(raw_cue.get("position")),
    )


def resolve_runtime_transcribe_provider(
    requested_provider: str,
    *,
    openai_api_key: str | None = None,
) -> str:
    if settings.mock_external_services:
        return "mock"

    normalized_provider = requested_provider.strip().lower()

    if normalized_provider == "elevenlabs":
        if not settings.elevenlabs_enabled:
            raise RuntimeError("ElevenLabs Scribe v2 is disabled.")
        if settings.external_provider_monthly_budget_usd <= 0 or settings.external_provider_per_request_budget_usd <= 0:
            raise RuntimeError("ElevenLabs Scribe v2 safety budgets are closed.")
        if not provider_clients.resolve_elevenlabs_api_key():
            raise RuntimeError("ElevenLabs API key is missing.")

    if normalized_provider == "groq" and not provider_clients.resolve_groq_api_key():
        logger.warning("GROQ_API_KEY is missing; falling back to local faster-whisper transcription.")
        return "local"

    if normalized_provider == "openai" and not provider_clients.resolve_openai_api_key(openai_api_key):
        logger.warning("OPENAI_API_KEY is missing; falling back to local faster-whisper transcription.")
        return "local"

    return normalized_provider


def _persist_preview_asset(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return

    try:
        destination.hardlink_to(source)
        return
    except OSError as exc:
        logger.debug("Hard link unavailable for preview asset; copying instead: %s", exc)

    shutil.copy2(source, destination)


def _processing_style(
    *,
    subtitle_position: int,
    max_subtitle_lines: int,
    subtitle_color: str | None,
    shadow_strength: int,
    highlight_style: str,
    subtitle_size: int,
    karaoke_enabled: bool,
) -> SubtitleStyle:
    return SubtitleStyle(
        position=subtitle_position,
        max_lines=max_subtitle_lines,
        primary_color=subtitle_color or settings.default_sub_color,
        shadow_strength=shadow_strength,
        highlight_style=_normalize_highlight_style(
            highlight_style,
            karaoke_enabled=karaoke_enabled,
        ),
        font_size=settings_utils.font_size_from_subtitle_size(subtitle_size),
    )


def _resolve_transcription_request(
    *,
    transcribe_tier: str | None,
    transcribe_provider: str | None,
    openai_api_key: str | None,
    provider_model: str | None,
) -> tuple[str, str]:
    tier = pricing.normalize_tier(transcribe_tier)
    provider_name = (
        transcribe_provider.strip().lower() if transcribe_provider else settings.transcribe_tier_provider[tier]
    )
    if provider_name not in ALLOWED_TIER_PROVIDER_OVERRIDES[tier]:
        raise ValueError("transcribe_provider does not match selected tier")
    provider_name = resolve_runtime_transcribe_provider(
        provider_name,
        openai_api_key=openai_api_key,
    )
    selected_model = pricing.resolve_requested_transcribe_model(
        tier=tier,
        provider=provider_name,
        openai_model=provider_model,
    )
    return provider_name, selected_model


def _build_transcriber(
    *,
    provider_name: str,
    openai_api_key: str | None,
    device: str | None,
    compute_type: str | None,
    beam_size: int | None,
) -> Transcriber:
    if provider_name == "mock":
        return MockTranscriber()
    if provider_name == "groq":
        return GroqTranscriber()
    if provider_name == "openai":
        return OpenAITranscriber(api_key=openai_api_key)
    if provider_name == "elevenlabs":
        return ElevenLabsScribeTranscriber()
    if provider_name == "local":
        return LocalWhisperTranscriber(
            device=device,
            compute_type=compute_type,
            beam_size=beam_size or 5,
        )
    raise ValueError(f"Provider '{provider_name}' is not supported.")


def _log_pipeline_result(
    *,
    options: PipelineOptions,
    pipeline_error: str | None,
    selected_model: str,
    provider_name: str,
    device: str | None,
    compute_type: str | None,
    use_hw_accel: bool,
    language: str | None,
    video_preset: str | None,
    video_crf: int | None,
) -> None:
    metrics_payload: dict[str, object] = {
        "status": "error" if pipeline_error else "success",
        "error": pipeline_error,
        "transcribe_model": selected_model,
        "device": device or settings.whisper_device,
        "compute_type": compute_type or settings.whisper_compute_type,
        "transcribe_provider": provider_name,
        "use_hw_accel": use_hw_accel,
        "language": language or settings.whisper_language,
        "video_preset": video_preset or settings.default_video_preset,
        "video_crf": video_crf or settings.default_video_crf,
        "timings": options.timings,
    }
    metrics.log_pipeline_metrics(metrics_payload)


def process_video_pipeline(
    input_path: Path,
    output_path: Path,
    *,
    # Transcription Options
    transcribe_tier: str | None = None,
    language: str | None = None,
    transcribe_provider: str | None = None,
    openai_api_key: str | None = None,
    provider_model: str | None = None,
    # Style options
    subtitle_position: int = 16,
    max_subtitle_lines: int = 2,
    subtitle_color: str | None = None,
    shadow_strength: int = 4,
    highlight_style: str = "karaoke",
    subtitle_size: int = 100,
    karaoke_enabled: bool = True,
    # Pipeline Options
    device: str | None = None,
    compute_type: str | None = None,
    generate_social_copy: bool = False,
    artifact_dir: Path | None = None,
    use_hw_accel: bool = settings.use_hw_accel,
    progress_callback: Callable[[str, float], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
    transcription_only: bool = False,
    output_width: int | None = None,
    output_height: int | None = None,
    media_probe: ffmpeg_utils.MediaProbe | None = None,
    # Provider and encoder options
    beam_size: int | None = None,
    best_of: int | None = None,
    temperature: float | None = None,
    chunk_length: int | None = None,
    condition_on_previous_text: bool | None = None,
    initial_prompt: str | None = None,
    vad_filter: bool | None = None,
    vad_parameters: dict[str, Any] | None = None,
    video_crf: int | None = None,
    video_preset: str | None = None,
    audio_bitrate: str | None = None,
    watermark_enabled: bool = False,
    audio_copy: bool | None = None,
    ledger_store: UsageLedgerStore | None = None,
    charge_plan: ChargePlan | None = None,
) -> Path | tuple[Path, SocialCopy]:

    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    style = _processing_style(
        subtitle_position=subtitle_position,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_color=subtitle_color,
        shadow_strength=shadow_strength,
        highlight_style=highlight_style,
        subtitle_size=subtitle_size,
        karaoke_enabled=karaoke_enabled,
    )
    provider_name, selected_model = _resolve_transcription_request(
        transcribe_tier=transcribe_tier,
        transcribe_provider=transcribe_provider,
        openai_api_key=openai_api_key,
        provider_model=provider_model,
    )
    transcriber = _build_transcriber(
        provider_name=provider_name,
        openai_api_key=openai_api_key,
        device=device,
        compute_type=compute_type,
        beam_size=beam_size,
    )
    options = PipelineOptions(
        input_path=input_path,
        destination=destination,
        style=style,
        transcriber=transcriber,
        provider_name=provider_name,
        selected_model=selected_model,
        language=language,
        openai_api_key=openai_api_key,
        generate_social_copy=generate_social_copy,
        artifact_dir=artifact_dir,
        use_hw_accel=use_hw_accel,
        progress_callback=progress_callback,
        check_cancelled=check_cancelled,
        transcription_only=transcription_only,
        output_width=output_width,
        output_height=output_height,
        media_probe=media_probe,
        best_of=best_of,
        temperature=temperature,
        chunk_length=chunk_length,
        condition_on_previous_text=condition_on_previous_text,
        initial_prompt=initial_prompt,
        vad_filter=vad_filter,
        vad_parameters=vad_parameters,
        video_crf=video_crf,
        video_preset=video_preset,
        audio_bitrate=audio_bitrate,
        watermark_enabled=watermark_enabled,
        audio_copy=audio_copy,
        ledger_store=ledger_store,
        charge_plan=charge_plan,
        persist_preview_asset=_persist_preview_asset,
        resolve_ass_highlight_style=_resolve_ass_highlight_style,
        lock_provider_transcription=lock_provider_transcription,
        provider_slot_weight=provider_transcription_slot_weight,
    )

    overall_start = time.perf_counter()
    pipeline_error: str | None = None
    result: PipelineResult
    try:
        result = run_pipeline_steps(options)
    except Exception as exc:
        pipeline_error = str(exc)
        raise
    finally:
        options.timings["total_s"] = time.perf_counter() - overall_start
        _log_pipeline_result(
            options=options,
            pipeline_error=pipeline_error,
            selected_model=selected_model,
            provider_name=provider_name,
            device=device,
            compute_type=compute_type,
            use_hw_accel=use_hw_accel,
            language=language,
            video_preset=video_preset,
            video_crf=video_crf,
        )

    if progress_callback:
        progress_callback("Done!", 100.0)
    if not transcription_only and not destination.exists():
        raise RuntimeError(f"Output video was not produced. Error: {pipeline_error or 'Unknown'}")
    if generate_social_copy:
        social_copy = result.social_copy or social_intelligence.build_social_copy(result.transcript_text)
        return destination, social_copy
    return destination


def generate_video_variant(
    job_id: str,
    input_path: Path,
    artifact_dir: Path,
    resolution: str,
    job_store: JobStore,
    user_id: str,
    subtitle_settings: Mapping[str, Any] | None = None,
    video_crf: int | None = None,
    held_render_slots: tuple[int, ...] | None = None,
    progress_callback: Callable[[float], None] | None = None,
) -> Path:
    """Render a variant while preserving this module's patchable helpers."""
    return _generate_video_variant(
        job_id,
        input_path,
        artifact_dir,
        resolution,
        job_store,
        user_id,
        subtitle_settings=subtitle_settings,
        video_crf=video_crf,
        held_render_slots=held_render_slots,
        progress_callback=progress_callback,
        load_persisted_cues=_load_persisted_cues,
        normalize_highlight_style=_normalize_highlight_style,
        resolve_ass_highlight_style=_resolve_ass_highlight_style,
    )
