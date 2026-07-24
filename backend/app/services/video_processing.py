"""Video normalization and subtitle burn-in helpers."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, cast

from backend.app.core import metrics
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.services import (
    artifact_manager,
    ffmpeg_utils,
    llm_utils,
    pricing,
    settings_utils,
    social_intelligence,
    subtitle_renderer,
    subtitles,
)
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
from backend.app.services.usage_ledger import ChargePlan, ChargeReservation, UsageLedgerStore

logger = logging.getLogger(__name__)

ALLOWED_TIER_PROVIDER_OVERRIDES: dict[str, set[str]] = {
    "standard": {"mock", "groq", "local"},
    "pro": {"mock", "elevenlabs", "groq", "openai", "local"},
}
ALLOWED_HIGHLIGHT_STYLES: frozenset[str] = frozenset(
    {"static", "karaoke", "pop", "active-graphics"}
)


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

        cues: list[Cue] = []
        for raw_cue in payload:
            if not isinstance(raw_cue, dict):
                raise ValueError("transcription cue must be an object")
            start = raw_cue.get("start")
            end = raw_cue.get("end")
            text = raw_cue.get("text")
            if (
                isinstance(start, bool)
                or not isinstance(start, (int, float))
                or isinstance(end, bool)
                or not isinstance(end, (int, float))
                or not isinstance(text, str)
            ):
                raise ValueError("transcription cue fields are invalid")

            words_payload = raw_cue.get("words")
            words: list[WordTiming] | None = None
            if words_payload is not None:
                if not isinstance(words_payload, list):
                    raise ValueError("cue words must be a list")
                words = []
                for raw_word in words_payload:
                    if not isinstance(raw_word, dict):
                        raise ValueError("word timing must be an object")
                    word_start = raw_word.get("start")
                    word_end = raw_word.get("end")
                    word_text = raw_word.get("text")
                    if (
                        isinstance(word_start, bool)
                        or not isinstance(word_start, (int, float))
                        or isinstance(word_end, bool)
                        or not isinstance(word_end, (int, float))
                        or not isinstance(word_text, str)
                    ):
                        raise ValueError("word timing fields are invalid")
                    words.append(
                        WordTiming(
                            start=float(word_start),
                            end=float(word_end),
                            text=word_text,
                        )
                    )
            cues.append(Cue(start=float(start), end=float(end), text=text, words=words))
        return cues
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        logger.warning("Could not load persisted transcription from %s: %s", path, exc)
        return None


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
        if (
            settings.external_provider_monthly_budget_usd <= 0
            or settings.external_provider_per_request_budget_usd <= 0
        ):
            raise RuntimeError("ElevenLabs Scribe v2 safety budgets are closed.")
        if not llm_utils.resolve_elevenlabs_api_key():
            raise RuntimeError("ElevenLabs API key is missing.")

    if normalized_provider == "groq" and not llm_utils.resolve_groq_api_key():
        logger.warning("GROQ_API_KEY is missing; falling back to local faster-whisper transcription.")
        return "local"

    if normalized_provider == "openai" and not llm_utils.resolve_openai_api_key(openai_api_key):
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
    use_llm_social_copy: bool = False,
    llm_model: str | None = None,
    llm_temperature: float = 0.6,
    llm_api_key: str | None = None,
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
    db: Database | None = None,
    job_id: str | None = None,
    ledger_store: UsageLedgerStore | None = None,
    charge_plan: ChargePlan | None = None,
) -> Path | tuple[Path, SocialCopy]:

    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    font_size = settings_utils.font_size_from_subtitle_size(subtitle_size)
    effective_highlight_style = _normalize_highlight_style(
        highlight_style,
        karaoke_enabled=karaoke_enabled,
    )

    style = SubtitleStyle(
        position=subtitle_position,
        max_lines=max_subtitle_lines,
        primary_color=subtitle_color or settings.default_sub_color,
        shadow_strength=shadow_strength,
        highlight_style=effective_highlight_style,
        font_size=font_size,
    )

    tier = pricing.normalize_tier(transcribe_tier)
    provider_name = transcribe_provider.strip().lower() if transcribe_provider else None
    if provider_name:
        allowed_providers = ALLOWED_TIER_PROVIDER_OVERRIDES[tier]
        if provider_name not in allowed_providers:
            raise ValueError("transcribe_provider does not match selected tier")
    else:
        provider_name = settings.transcribe_tier_provider[tier]

    provider_name = resolve_runtime_transcribe_provider(
        provider_name,
        openai_api_key=openai_api_key,
    )
    selected_model = pricing.resolve_requested_transcribe_model(
        tier=tier,
        provider=provider_name,
        openai_model=provider_model,
    )

    transcriber: Transcriber
    if provider_name == "mock":
        transcriber = MockTranscriber()
    elif provider_name == "groq":
        transcriber = GroqTranscriber()
    elif provider_name == "openai":
        transcriber = OpenAITranscriber(api_key=openai_api_key)
    elif provider_name == "elevenlabs":
        transcriber = ElevenLabsScribeTranscriber()
    elif provider_name == "local":
        transcriber = LocalWhisperTranscriber(
            device=device,
            compute_type=compute_type,
            beam_size=beam_size or 5,
        )
    else:
        raise ValueError(f"Provider '{provider_name}' is not supported.")

    pipeline_timings: dict[str, float] = {}
    pipeline_error: str | None = None
    overall_start = time.perf_counter()
    total_duration = 0.0
    resolved_audio_copy = audio_copy if audio_copy is not None else False

    try:
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            scratch.mkdir(parents=True, exist_ok=True)

            if check_cancelled:
                check_cancelled()

            if progress_callback is not None or audio_copy is None:
                try:
                    probe = media_probe or ffmpeg_utils.probe_media(input_path)
                    if probe.duration_s is not None and probe.duration_s > 0:
                        total_duration = probe.duration_s
                    if audio_copy is None:
                        resolved_audio_copy = probe.audio_is_aac
                except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
                    logger.warning("Could not probe input media %s: %s", input_path, exc)
                    total_duration = 0.0
                    resolved_audio_copy = audio_copy if audio_copy is not None else False

            def _extract_cb(progress: float) -> None:
                if progress_callback:
                    progress_callback(
                        f"Extracting Audio ({int(progress)}%)...",
                        progress * 0.05,
                    )

            if progress_callback:
                progress_callback("Extracting audio...", 0.0)
            if check_cancelled:
                check_cancelled()
            with metrics.measure_time(pipeline_timings, "extract_audio_s"):
                audio_path = subtitles.extract_audio(
                    input_path,
                    output_dir=scratch,
                    check_cancelled=check_cancelled,
                    progress_callback=_extract_cb if total_duration else None,
                    total_duration=total_duration,
                )

            if progress_callback:
                progress_callback("Transcribing audio...", 5.0)
            if check_cancelled:
                check_cancelled()
            with metrics.measure_time(pipeline_timings, "transcribe_s"):
                def _transcribe_cb(progress: float) -> None:
                    if progress_callback:
                        progress_callback(
                            f"Transcribing ({int(progress)}%)...",
                            5.0 + (progress * 0.6),
                        )

                transcribe_kwargs: dict[str, Any] = {
                    "best_of": best_of,
                    "total_duration": total_duration,
                    "openai_api_key": openai_api_key,
                    "chunk_length": chunk_length,
                    "condition_on_previous_text": condition_on_previous_text,
                    "initial_prompt": initial_prompt,
                    "vad_filter": vad_filter if vad_filter is not None else True,
                    "vad_parameters": vad_parameters,
                    "temperature": temperature,
                    "progress_callback": _transcribe_cb if total_duration > 0 else None,
                    "check_cancelled": check_cancelled,
                }

                if (
                    ledger_store
                    and charge_plan
                    and charge_plan.transcription
                    and getattr(
                        charge_plan.transcription,
                        "estimated_cost_usd",
                        0.0,
                    )
                    > 0
                ):
                    ledger_store.mark_dispatched(charge_plan.transcription)

                srt_path, cues = transcriber.transcribe(
                    audio_path,
                    output_dir=scratch,
                    language=language or settings.whisper_language,
                    model=selected_model,
                    **transcribe_kwargs,
                )

            if ledger_store and charge_plan and charge_plan.transcription:
                duration_seconds = total_duration if total_duration > 0 else 0.0
                tier = charge_plan.transcription.tier or settings.default_transcribe_tier
                credits = (
                    pricing.credits_for_video_duration(duration_seconds)
                    if duration_seconds > 0
                    else charge_plan.transcription.reserved_credits
                )
                cost_usd = pricing.stt_provider_cost_usd(
                    tier=tier,
                    duration_seconds=duration_seconds,
                    provider=provider_name,
                    model=selected_model,
                )
                units = {
                    "audio_seconds": duration_seconds,
                    "model": selected_model,
                    "provider": provider_name,
                }
                ledger_store.finalize(
                    charge_plan.transcription,
                    credits_charged=credits,
                    cost_usd=cost_usd,
                    units=units,
                )

            if check_cancelled:
                check_cancelled()

            if progress_callback:
                progress_callback("Styling...", 65.0)
            with metrics.measure_time(pipeline_timings, "style_subs_s"):
                ass_highlight_style = _resolve_ass_highlight_style(style.highlight_style, cues)

                ass_path = subtitle_renderer.create_styled_subtitle_file(
                    srt_path,
                    cues=cues,
                    subtitle_position=style.position,
                    max_lines=style.max_lines,
                    shadow_strength=style.shadow_strength,
                    primary_color=style.primary_color,
                    highlight_style=ass_highlight_style,
                    font_size=style.font_size,
                    play_res_x=settings.default_width,
                    play_res_y=settings.default_height,
                )

            transcript_text = subtitles.cues_to_text(cues)
            social_copy: SocialCopy | None = None
            future_social: Future[SocialCopy] | None = None

            with ThreadPoolExecutor() as executor:
                if generate_social_copy:
                    if progress_callback:
                        progress_callback("Social Copy...", 70.0)
                    if use_llm_social_copy and not settings.mock_external_services:
                        def _run_social_with_session(
                            text: str,
                            model: str | None,
                            temp: float,
                            api_key: str | None,
                            reservation: ChargeReservation | None,
                        ) -> SocialCopy:
                            if db:
                                with db.session() as session:
                                    return social_intelligence.build_social_copy_llm(
                                        text,
                                        model=model,
                                        temperature=temp,
                                        api_key=api_key,
                                        session=session,
                                        job_id=job_id,
                                        ledger_store=ledger_store,
                                        charge_reservation=reservation,
                                    )
                            return social_intelligence.build_social_copy_llm(
                                    text,
                                    model=model,
                                    temperature=temp,
                                    api_key=api_key,
                                    ledger_store=ledger_store,
                                    charge_reservation=reservation,
                                )

                        future_social = executor.submit(
                            _run_social_with_session,
                            transcript_text,
                            llm_model,
                            llm_temperature,
                            llm_api_key,
                            charge_plan.social_copy if charge_plan else None,
                        )
                    else:
                        social_copy = social_intelligence.build_social_copy(transcript_text)

            if not transcription_only:
                if progress_callback:
                    progress_callback("Rendering...", 80.0)

                try:
                    def _enc_cb(progress: float) -> None:
                        if progress_callback:
                            progress_callback(
                                f"Encoding ({int(progress)}%)...",
                                80.0 + (progress * 0.2),
                            )

                    ffmpeg_utils.run_ffmpeg_with_subs(
                        input_path, ass_path, destination,
                        video_crf=video_crf or settings.default_video_crf,
                        video_preset=video_preset or settings.default_video_preset,
                        audio_bitrate=audio_bitrate or settings.default_audio_bitrate,
                        audio_copy=resolved_audio_copy,
                        use_hw_accel=use_hw_accel,
                        progress_callback=_enc_cb if total_duration > 0 else None,
                        total_duration=total_duration,
                        output_width=output_width,
                        output_height=output_height,
                        watermark_enabled=watermark_enabled,
                        check_cancelled=check_cancelled,
                    )
                except subprocess.CalledProcessError as exc:
                    if use_hw_accel:
                        logger.warning("Hardware acceleration failed; retrying with software encoding: %s", exc)
                        # Retry without hardware acceleration
                        ffmpeg_utils.run_ffmpeg_with_subs(
                            input_path, ass_path, destination,
                            video_crf=video_crf or settings.default_video_crf,
                            video_preset=video_preset or settings.default_video_preset,
                            audio_bitrate=audio_bitrate or settings.default_audio_bitrate,
                            audio_copy=resolved_audio_copy,
                            use_hw_accel=False,
                            progress_callback=_enc_cb if total_duration > 0 else None,
                            total_duration=total_duration,
                            output_width=output_width,
                            output_height=output_height,
                            watermark_enabled=watermark_enabled,
                            check_cancelled=check_cancelled,
                        )
                    else:
                        raise

                if future_social:
                    social_copy = future_social.result()

            if progress_callback:
                progress_callback("Finalizing...", 95.0)
            if transcription_only:
                _persist_preview_asset(input_path, destination)
            if artifact_dir:
                artifact_manager.persist_artifacts(
                    artifact_dir,
                    audio_path,
                    srt_path,
                    ass_path,
                    transcript_text,
                    social_copy,
                    cues,
                    max_subtitle_lines=style.max_lines,
                    subtitle_size=style.font_size,
                )
                if destination.exists() and artifact_dir != destination.parent:
                    try:
                        shutil.copy2(destination, artifact_dir / destination.name)
                    except FileNotFoundError:
                        logger.warning("Rendered output disappeared before artifact copy: %s", destination)

    except Exception as exc:
        pipeline_error = str(exc)
        raise
    finally:
        pipeline_timings["total_s"] = time.perf_counter() - overall_start
        metrics.log_pipeline_metrics(
            {
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
                "timings": pipeline_timings,
            }
        )

    if progress_callback:
        progress_callback("Done!", 100.0)

    if not transcription_only and not destination.exists():
        raise RuntimeError(f"Output video was not produced. Error: {pipeline_error or 'Unknown'}")

    if generate_social_copy:
        if social_copy is None:
            social_copy = social_intelligence.build_social_copy(transcript_text or "")
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
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError("Original input video not found")

    width, height = settings.default_width, settings.default_height
    try:
        w_str, h_str = resolution.lower().replace("×", "x").split("x")
    except ValueError as exc:
        raise ValueError("Invalid resolution format") from exc

    try:
        width, height = int(w_str), int(h_str)
    except ValueError as exc:
        raise ValueError("Invalid resolution format") from exc

    if width <= 0 or height <= 0:
        raise ValueError("Resolution dimensions must be positive")
    if width > settings.max_resolution_dimension or height > settings.max_resolution_dimension:
        raise ValueError(f"Resolution exceeds max {settings.max_resolution_dimension}")

    transcript_path = artifact_dir / f"{input_path.stem}.srt"
    if not transcript_path.exists():
        srts = list(artifact_dir.glob("*.srt"))
        if srts:
            transcript_path = srts[0]
        else:
            raise FileNotFoundError("Transcript not found. Cannot generate variant.")

    job = job_store.get_job(job_id)
    if not job or job.user_id != user_id:
        raise PermissionError("Job not found or access denied")

    result_data = job.result_data or {}
    ass_path = transcript_path.with_suffix(".ass")

    def _resolve_param(val: Any, default: int) -> int:
        return int(val) if val is not None else default

    if subtitle_settings:
        cues = _load_persisted_cues(artifact_dir / "transcription.json")

        font_size = settings_utils.font_size_from_subtitle_size(subtitle_settings.get("subtitle_size"))
        karaoke_enabled = bool(subtitle_settings.get("karaoke_enabled", True))
        requested_style = str(subtitle_settings.get("highlight_style") or "karaoke")
        highlight_style = _resolve_ass_highlight_style(
            _normalize_highlight_style(requested_style, karaoke_enabled=karaoke_enabled),
            cues,
        )

        base_width, base_height = settings.default_width, settings.default_height

        resolved_color = str(subtitle_settings.get("subtitle_color") or settings.default_sub_color)
        ass_path = subtitle_renderer.create_styled_subtitle_file(
            transcript_path,
            cues=cues,
            subtitle_position=settings_utils.normalize_subtitle_position(
                subtitle_settings.get("subtitle_position")
            ),
            max_lines=_resolve_param(subtitle_settings.get("max_subtitle_lines"), 2),
            primary_color=resolved_color,
            shadow_strength=_resolve_param(subtitle_settings.get("shadow_strength"), 4),
            font_size=font_size,
            highlight_style=highlight_style,
            play_res_x=base_width,
            play_res_y=base_height,
            output_dir=artifact_dir,
        )

    elif not ass_path.exists():
        ass_candidates = sorted(artifact_dir.glob("*.ass"))
        ass_path = ass_candidates[0] if ass_candidates else ass_path

    if not ass_path.exists():
        font_size = settings_utils.font_size_from_subtitle_size(result_data.get("subtitle_size"))
        karaoke_enabled = bool(result_data.get("karaoke_enabled", True))
        requested_style = str(result_data.get("highlight_style") or "karaoke")
        cues = _load_persisted_cues(artifact_dir / "transcription.json")
        highlight_style = _resolve_ass_highlight_style(
            _normalize_highlight_style(requested_style, karaoke_enabled=karaoke_enabled),
            cues,
        )

        base_width, base_height = settings.default_width, settings.default_height

        ass_path = subtitle_renderer.create_styled_subtitle_file(
            transcript_path,
            cues=cues,
            subtitle_position=settings_utils.normalize_subtitle_position(
                result_data.get("subtitle_position")
            ),
            max_lines=_resolve_param(result_data.get("max_subtitle_lines"), 2),
            primary_color=str(result_data.get("subtitle_color") or settings.default_sub_color),
            shadow_strength=_resolve_param(result_data.get("shadow_strength"), 4),
            font_size=font_size,
            highlight_style=highlight_style,
            play_res_x=base_width,
            play_res_y=base_height,
            output_dir=artifact_dir,
        )

    output_filename = f"processed_{width}x{height}.mp4"
    destination = artifact_dir / output_filename

    stored_crf = result_data.get("video_crf")
    video_crf = int(stored_crf) if stored_crf is not None else settings.default_video_crf

    watermark_enabled = bool(subtitle_settings.get("watermark_enabled", False)) if subtitle_settings else bool(result_data.get("watermark_enabled", False))
    audio_copy = ffmpeg_utils.input_audio_is_aac(input_path)

    ffmpeg_utils.run_ffmpeg_with_subs(
        input_path,
        ass_path,
        destination,
        video_crf=video_crf,
        video_preset=settings.default_video_preset,
        audio_bitrate=settings.default_audio_bitrate,
        audio_copy=audio_copy,
        use_hw_accel=settings.use_hw_accel,
        output_width=width,
        output_height=height,
        watermark_enabled=watermark_enabled,
    )

    return destination
