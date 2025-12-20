"""Video normalization and subtitle burn-in helpers."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from backend.app.core import config, metrics
from backend.app.core.database import Database
from backend.app.services import (
    artifact_manager,
    ffmpeg_utils,
    pricing,
    settings_utils,
    subtitles,
)
from backend.app.services.styles import SubtitleStyle
from backend.app.services.transcription.groq_cloud import GroqTranscriber
from backend.app.services.transcription.openai_cloud import OpenAITranscriber
from backend.app.services.usage_ledger import ChargePlan, UsageLedgerStore

logger = logging.getLogger(__name__)


def normalize_and_stub_subtitles(
    input_path: Path,
    output_path: Path,
    *,
    # Transcription Options
    model_size: str | None = None,
    language: str | None = None,
    transcribe_provider: str | None = None,
    openai_api_key: str | None = None,
    # Style Options (Will construct SubtitleStyle)
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
    use_hw_accel: bool = config.USE_HW_ACCEL,
    progress_callback: Callable[[str, float], None] | None = None,
    check_cancelled: Callable[[], None] | None = None,
    transcription_only: bool = False,
    output_width: int | None = None,
    output_height: int | None = None,
    # Legacy/Passed-through but less impactful now
    beam_size: int | None = None,
    best_of: int | None = None,
    temperature: float | None = None,
    chunk_length: int | None = None,
    condition_on_previous_text: bool | None = None,
    initial_prompt: str | None = None,
    vad_filter: bool | None = None,
    vad_parameters: dict | None = None,
    video_crf: int | None = None,
    video_preset: str | None = None,
    audio_bitrate: str | None = None,
    watermark_enabled: bool = False,
    audio_copy: bool | None = None,
    db: Database | None = None,
    job_id: str | None = None,
    ledger_store: UsageLedgerStore | None = None,
    charge_plan: ChargePlan | None = None,
) -> Path | tuple[Path, subtitles.SocialCopy]:

    if not input_path.exists():
        raise FileNotFoundError(f"Input video not found: {input_path}")

    destination = output_path.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)

    # --- 1. CONFIGURATION (The Director) ---
    font_size = settings_utils.font_size_from_subtitle_size(subtitle_size)

    # Determine effective highlight style
    effective_highlight_style = highlight_style
    if not karaoke_enabled:
        effective_highlight_style = "static"

    style = SubtitleStyle(
        position=subtitle_position if subtitle_position is not None else 16,
        max_lines=max_subtitle_lines,
        primary_color=subtitle_color or config.DEFAULT_SUB_COLOR,
        shadow_strength=shadow_strength,
        highlight_style=effective_highlight_style,
        font_size=font_size
    )

    # Map abstract model names to concrete models & providers
    tier = pricing.resolve_tier_from_model(model_size)
    provider_name = transcribe_provider.strip().lower() if transcribe_provider else None
    if provider_name:
        expected_provider = config.TRANSCRIBE_TIER_PROVIDER[tier]
        if provider_name != expected_provider:
            raise ValueError("transcribe_provider does not match selected tier")
    else:
        provider_name = config.TRANSCRIBE_TIER_PROVIDER[tier]

    selected_model = config.TRANSCRIBE_TIER_MODEL[tier]

    # Instantiate Transcriber (The Ear)
    transcriber = None
    if provider_name == "groq":
        transcriber = GroqTranscriber()
    elif provider_name == "openai":
        transcriber = OpenAITranscriber(api_key=openai_api_key)
    else:
        raise ValueError(f"Provider '{provider_name}' is not supported.")

    # --- PIPELINE EXECUTION ---
    pipeline_timings: dict[str, float] = {}
    pipeline_error: str | None = None
    overall_start = time.perf_counter()
    total_duration = 0.0
    resolved_audio_copy = audio_copy if audio_copy is not None else False

    try:
        with tempfile.TemporaryDirectory() as scratch_dir:
            scratch = Path(scratch_dir)
            scratch.mkdir(parents=True, exist_ok=True)

            if check_cancelled: check_cancelled()

            # Probe once for duration + audio codec
            if progress_callback is not None or audio_copy is None:
                try:
                    probe = ffmpeg_utils.probe_media(input_path)
                    if probe.duration_s is not None and probe.duration_s > 0:
                        total_duration = probe.duration_s
                    if audio_copy is None:
                        resolved_audio_copy = probe.audio_is_aac
                except Exception:
                    total_duration = 0.0
                    resolved_audio_copy = audio_copy if audio_copy is not None else False

            # Step 1: Extract Audio
            def _extract_cb(p: float):
                if progress_callback: progress_callback(f"Extracting Audio ({int(p)}%)...", p * 0.05)

            if progress_callback: progress_callback("Extracting audio...", 0.0)
            if check_cancelled: check_cancelled()
            with metrics.measure_time(pipeline_timings, "extract_audio_s"):
                audio_path = subtitles.extract_audio(
                    input_path,
                    output_dir=scratch,
                    check_cancelled=check_cancelled,
                    progress_callback=_extract_cb if total_duration else None,
                    total_duration=total_duration
                )

            # Step 2: Transcribe
            if progress_callback: progress_callback("Transcribing audio...", 5.0)
            if check_cancelled: check_cancelled()
            with metrics.measure_time(pipeline_timings, "transcribe_s"):
                def _transcribe_cb(p):
                    if progress_callback: progress_callback(f"Transcribing ({int(p)}%)...", 5.0 + (p * 0.6))

                transcribe_kwargs = {
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

                srt_path, cues = transcriber.transcribe(
                    audio_path,
                    output_dir=scratch,
                    language=language or config.WHISPER_LANGUAGE,
                    model=selected_model,
                    **transcribe_kwargs
                )

            if ledger_store and charge_plan and charge_plan.transcription:
                duration_seconds = total_duration if total_duration > 0 else 0.0
                tier = charge_plan.transcription.tier or config.DEFAULT_TRANSCRIBE_TIER
                credits = pricing.credits_for_minutes(
                    tier=tier,
                    duration_seconds=duration_seconds,
                    min_credits=charge_plan.transcription.min_credits,
                )
                cost_usd = pricing.stt_cost_usd(tier=tier, duration_seconds=duration_seconds)
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

            if check_cancelled: check_cancelled()

            # Step 3: Style (ASS Generation)
            if progress_callback: progress_callback("Styling...", 65.0)
            with metrics.measure_time(pipeline_timings, "style_subs_s"):
                has_words = bool(cues and any(c.words for c in cues))
                ass_highlight_style = style.highlight_style
                if ass_highlight_style == "active-graphics":
                    ass_highlight_style = "active" if has_words else "karaoke"

                ass_path = subtitles.create_styled_subtitle_file(
                    srt_path,
                    cues=cues,
                    subtitle_position=style.position,
                    max_lines=style.max_lines,
                    shadow_strength=style.shadow_strength,
                    primary_color=style.primary_color,
                    highlight_style=ass_highlight_style,
                    font_size=style.font_size,
                    play_res_x=config.DEFAULT_WIDTH,
                    play_res_y=config.DEFAULT_HEIGHT,
                )

            # Step 4: Social Copy & Rendering
            transcript_text = subtitles.cues_to_text(cues)
            social_copy = None
            future_social = None

            with ThreadPoolExecutor() as executor:
                if generate_social_copy:
                    if progress_callback: progress_callback("Social Copy...", 70.0)
                    if use_llm_social_copy:
                        def _run_social_with_session(text, model, temp, api_key, reservation):
                            if db:
                                with db.session() as session:
                                    return subtitles.build_social_copy_llm(
                                        text,
                                        model=model,
                                        temperature=temp,
                                        api_key=api_key,
                                        session=session,
                                        job_id=job_id,
                                        ledger_store=ledger_store,
                                        charge_reservation=reservation,
                                    )
                            else:
                                 return subtitles.build_social_copy_llm(
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
                        social_copy = subtitles.build_social_copy(transcript_text)

            # RENDER (The Eye)
            if not transcription_only:
                if progress_callback: progress_callback("Rendering...", 80.0)

                try:
                    def _enc_cb(p):
                        if progress_callback: progress_callback(f"Encoding ({int(p)}%)...", 80.0 + (p * 0.2))

                    ffmpeg_utils.run_ffmpeg_with_subs(
                        input_path, ass_path, destination,
                        video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
                        video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
                        audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
                        audio_copy=resolved_audio_copy,
                        use_hw_accel=use_hw_accel,
                        progress_callback=_enc_cb if total_duration > 0 else None,
                        total_duration=total_duration,
                        output_width=output_width,
                        output_height=output_height,
                        watermark_enabled=watermark_enabled,
                        check_cancelled=check_cancelled,
                        timeout=3600.0,
                    )
                except subprocess.CalledProcessError as exc:
                    if use_hw_accel:
                        logger.warning("Hardware acceleration failed; retrying with software encoding: %s", exc)
                        # Retry without hardware acceleration
                        ffmpeg_utils.run_ffmpeg_with_subs(
                            input_path, ass_path, destination,
                            video_crf=video_crf or config.DEFAULT_VIDEO_CRF,
                            video_preset=video_preset or config.DEFAULT_VIDEO_PRESET,
                            audio_bitrate=audio_bitrate or config.DEFAULT_AUDIO_BITRATE,
                            audio_copy=resolved_audio_copy,
                            use_hw_accel=False, # Force False
                            progress_callback=_enc_cb if total_duration > 0 else None,
                            total_duration=total_duration,
                            output_width=output_width,
                            output_height=output_height,
                            watermark_enabled=watermark_enabled,
                            check_cancelled=check_cancelled,
                            timeout=3600.0,
                        )
                    else:
                        raise

                if future_social:
                    social_copy = future_social.result()

            # Step 5: Artifacts
            if progress_callback: progress_callback("Finalizing...", 95.0)
            if artifact_dir:
                 artifact_manager.persist_artifacts(artifact_dir, audio_path, srt_path, ass_path, transcript_text, social_copy, cues)
                 if destination.exists() and artifact_dir != destination.parent:
                     try:
                         import shutil
                         shutil.copy2(destination, artifact_dir / destination.name)
                     except FileNotFoundError:
                         pass

    except Exception as exc:
        pipeline_error = str(exc)
        raise
    finally:
        pipeline_timings["total_s"] = time.perf_counter() - overall_start
        metrics.log_pipeline_metrics(
            {
                "status": "error" if pipeline_error else "success",
                "error": pipeline_error,
                "model_size": selected_model,
                "device": device or config.WHISPER_DEVICE,
                "compute_type": compute_type or config.WHISPER_COMPUTE_TYPE,
                "transcribe_provider": provider_name,
                "use_hw_accel": use_hw_accel,
                "language": language or config.WHISPER_LANGUAGE,
                "video_preset": video_preset or config.DEFAULT_VIDEO_PRESET,
                "video_crf": video_crf or config.DEFAULT_VIDEO_CRF,
                "timings": pipeline_timings,
            }
        )

    if progress_callback: progress_callback("Done!", 100.0)

    if not transcription_only and not destination.exists():
        raise RuntimeError(f"Output video was not produced. Error: {pipeline_error or 'Unknown'}")

    if generate_social_copy:
        if social_copy is None:
            # Safety fallback
            social_copy = subtitles.build_social_copy(transcript_text or "")
        return (destination if not transcription_only else input_path), social_copy
    return destination if not transcription_only else input_path


def generate_video_variant(
    job_id: str,
    input_path: Path,
    artifact_dir: Path,
    resolution: str,
    job_store,
    user_id: str,
    subtitle_settings: dict | None = None,
) -> Path:
    if not input_path.exists():
        raise FileNotFoundError("Original input video not found")

    width, height = config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT
    try:
        w_str, h_str = resolution.lower().replace("×", "x").split("x")
        width, height = int(w_str), int(h_str)
        if width > config.MAX_RESOLUTION_DIMENSION or height > config.MAX_RESOLUTION_DIMENSION:
            raise ValueError(f"Resolution exceeds max {config.MAX_RESOLUTION_DIMENSION}")
    except Exception as e:
        logger.warning(f"Failed to parse resolution in variant gen: {e}")
        if "exceeds max" in str(e):
            raise e

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

    # If explicit settings provided, we FORCE regeneration
    if subtitle_settings:
        cues = None
        transcription_json = artifact_dir / "transcription.json"

        if transcription_json.exists():
            try:
                import json
                data = json.loads(transcription_json.read_text(encoding="utf-8"))
                cues = []
                for item in data:
                    words = [subtitles.WordTiming(**w) for w in item["words"]] if item.get("words") else None
                    cues.append(subtitles.Cue(
                        start=item["start"],
                        end=item["end"],
                        text=item["text"],
                        words=words
                    ))
            except Exception as e:
                logger.warning(f"Failed to load transcription.json: {e}")

        font_size = settings_utils.font_size_from_subtitle_size(subtitle_settings.get("subtitle_size"))
        karaoke_enabled = bool(subtitle_settings.get("karaoke_enabled", True))
        requested_highlight_style = str(subtitle_settings.get("highlight_style") or "karaoke").lower()
        highlight_style = "static" if not karaoke_enabled else requested_highlight_style

        # FIX: Always use reference resolution (1080x1920) for ASS generation.
        base_width, base_height = config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT

        ass_path = subtitles.create_styled_subtitle_file(
            transcript_path,
            cues=cues,
            subtitle_position=settings_utils.parse_legacy_position(subtitle_settings.get("subtitle_position")),
            max_lines=_resolve_param(subtitle_settings.get("max_subtitle_lines"), 2),
            primary_color=str(subtitle_settings.get("subtitle_color") or config.DEFAULT_SUB_COLOR),
            shadow_strength=_resolve_param(subtitle_settings.get("shadow_strength"), 4),
            font_size=font_size,
            highlight_style=highlight_style,
            play_res_x=base_width,
            play_res_y=base_height,
            output_dir=artifact_dir,
        )

    # Otherwise try to reuse existing ASS
    elif not ass_path.exists():
        ass_candidates = sorted(artifact_dir.glob("*.ass"))
        ass_path = ass_candidates[0] if ass_candidates else ass_path

    if not ass_path.exists():
        # Fallback: regenerate ASS using persisted job settings.
        font_size = settings_utils.font_size_from_subtitle_size(result_data.get("subtitle_size"))
        karaoke_enabled = bool(result_data.get("karaoke_enabled", True))
        requested_highlight_style = str(result_data.get("highlight_style") or "karaoke").lower()
        highlight_style = "static" if not karaoke_enabled else requested_highlight_style

        cues = None
        transcription_json = artifact_dir / "transcription.json"
        if transcription_json.exists():
            try:
                import json
                data = json.loads(transcription_json.read_text(encoding="utf-8"))
                cues = []
                for item in data:
                    words = [subtitles.WordTiming(**w) for w in item["words"]] if item.get("words") else None
                    cues.append(subtitles.Cue(
                        start=item["start"],
                        end=item["end"],
                        text=item["text"],
                        words=words
                    ))
            except Exception as e:
                logger.warning(f"Failed to load transcription.json: {e}")

        base_width, base_height = config.DEFAULT_WIDTH, config.DEFAULT_HEIGHT

        ass_path = subtitles.create_styled_subtitle_file(
            transcript_path,
            cues=cues,
            subtitle_position=settings_utils.parse_legacy_position(result_data.get("subtitle_position")),
            max_lines=_resolve_param(result_data.get("max_subtitle_lines"), 2),
            primary_color=str(result_data.get("subtitle_color") or config.DEFAULT_SUB_COLOR),
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
    video_crf = int(stored_crf) if stored_crf is not None else config.DEFAULT_VIDEO_CRF

    watermark_enabled = bool(subtitle_settings.get("watermark_enabled", False)) if subtitle_settings else bool(result_data.get("watermark_enabled", False))

    ffmpeg_utils.run_ffmpeg_with_subs(
        input_path,
        ass_path,
        destination,
        video_crf=video_crf,
        video_preset=config.DEFAULT_VIDEO_PRESET,
        audio_bitrate=config.DEFAULT_AUDIO_BITRATE,
        audio_copy=True,
        use_hw_accel=config.USE_HW_ACCEL,
        output_width=width,
        output_height=height,
        watermark_enabled=watermark_enabled,
        timeout=3600.0,
    )

    return destination
