from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import TypeVar

import typer

from backend.app.core.cleanup import run_configured_retention
from backend.app.core.config import settings
from backend.app.core.database import Database
from backend.app.core.erasure_journal import configured_erasure_journal
from backend.app.services.erasure_reconciliation import reconcile_erasure_journal
from backend.app.services.product_feedback import (
    FeedbackNotificationWorker,
    FeedbackStore,
    SmtpFeedbackNotifier,
    run_feedback_worker,
)
from backend.app.services.video_processing import process_video_pipeline

app = typer.Typer(
    help="Normalize vertical videos and prepare styled Greek subtitles.",
    pretty_exceptions_show_locals=False,
)

_PrivacyResultT = TypeVar("_PrivacyResultT")


def _run_privacy_operation(
    operation: Callable[[Database], _PrivacyResultT],
    *,
    failure_message: str,
) -> _PrivacyResultT:
    """Run a privacy operation without rendering exception details."""
    try:
        db = Database()
    except Exception:
        typer.echo(failure_message, err=True)
        raise typer.Exit(code=1) from None

    try:
        try:
            return operation(db)
        finally:
            db.dispose()
    except Exception:
        typer.echo(failure_message, err=True)
        raise typer.Exit(code=1) from None


@app.command("reconcile-erasures")
def reconcile_erasures() -> None:
    """Replay privacy tombstones before restored services return online."""
    report = _run_privacy_operation(
        lambda db: reconcile_erasure_journal(
            db=db,
            data_dir=settings.data_dir,
            journal=configured_erasure_journal(),
        ),
        failure_message="Erasure reconciliation command failed.",
    )
    typer.echo(
        f"Erasure reconciliation complete: events={report.replayed_events} pruned={report.pruned_events}",
    )


@app.command("run-retention")
def run_retention() -> None:
    """Run media and financial retention synchronously while offline."""
    report = _run_privacy_operation(
        run_configured_retention,
        failure_message="Retention command failed.",
    )
    typer.echo(
        "Retention complete: "
        f"deleted_jobs={len(report.deleted_job_ids)} "
        f"failed_jobs={len(report.failed_job_ids)} "
        f"deleted_orphans={report.deleted_orphan_items} "
        f"failed_orphans={report.failed_orphan_items}",
    )
    if report.failed_job_ids or report.failed_orphan_items:
        raise typer.Exit(code=1)


def _configured_feedback_store(db: Database) -> FeedbackStore:
    return FeedbackStore(db=db)


def _configured_feedback_notifier() -> SmtpFeedbackNotifier:
    password = settings.feedback_smtp_password.get_secret_value() if settings.feedback_smtp_password is not None else ""
    return SmtpFeedbackNotifier(
        host=settings.feedback_smtp_host,
        port=settings.feedback_smtp_port,
        username=settings.feedback_smtp_username,
        password=password,
        mail_from=settings.feedback_mail_from,
        recipient=settings.feedback_notification_to,
        timeout_seconds=settings.feedback_smtp_timeout_seconds,
    )


@app.command("feedback-worker")
def feedback_worker() -> None:
    """Deliver the durable feedback outbox through the isolated mail network."""
    db: Database | None = None
    try:
        settings.assert_feedback_worker_configuration()
        db = Database()
        store = _configured_feedback_store(db)
        store.assert_queue_available()
        worker = FeedbackNotificationWorker(
            store=store,
            notifier=_configured_feedback_notifier(),
            retention_days=settings.feedback_retention_days,
            batch_size=settings.feedback_worker_batch_size,
        )
    except Exception:
        if db is not None:
            with suppress(Exception):
                db.dispose()
        typer.echo("Feedback worker configuration failed.", err=True)
        raise typer.Exit(code=1) from None

    try:
        run_feedback_worker(
            worker=worker,
            poll_seconds=settings.feedback_worker_poll_seconds,
        )
    except Exception:
        typer.echo("Feedback worker stopped unexpectedly.", err=True)
        raise typer.Exit(code=1) from None
    finally:
        with suppress(Exception):
            db.dispose()


@app.command("check-feedback-worker")
def check_feedback_worker() -> None:
    """Validate mail configuration and the feedback queue without sending."""
    try:
        settings.assert_feedback_worker_configuration()
        db = Database()
        try:
            _configured_feedback_store(db).assert_queue_available()
        finally:
            db.dispose()
    except Exception:
        typer.echo("Feedback worker health check failed.", err=True)
        raise typer.Exit(code=1) from None
    typer.echo("Feedback worker ready.")


@app.command("process")
def process(
    input_video: Path = typer.Argument(
        ...,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        help="Path to the source video file.",
    ),
    output_video: Path = typer.Option(
        ...,
        "--output",
        "-o",
        dir_okay=False,
        help="Path where the processed video will be written.",
    ),
    tier: str = typer.Option(
        settings.default_transcribe_tier,
        "--tier",
        help="Transcription quality tier: standard or pro.",
    ),
    provider: str = typer.Option(
        "mock",
        "--provider",
        help="Transcription provider: mock, local, groq, openai, or elevenlabs.",
    ),
    language: str | None = typer.Option(
        None,
        "--language",
        help="Language code for transcription (default: el).",
    ),
    beam_size: int | None = typer.Option(
        None,
        "--beam-size",
        min=1,
        help="Beam size for beam search decoding (higher = better quality, slower).",
    ),
    best_of: int | None = typer.Option(
        None,
        "--best-of",
        min=1,
        help="Number of candidate samples to pick best from during decoding.",
    ),
    device: str | None = typer.Option(
        None,
        "--device",
        help="Device for faster-whisper: cpu, cuda, or auto.",
    ),
    compute_type: str | None = typer.Option(
        None,
        "--compute-type",
        help="faster-whisper compute type (e.g., int8, float16, auto).",
    ),
    video_crf: int | None = typer.Option(
        None,
        "--crf",
        help="H.264 CRF (lower = higher quality). Default tuned for social platforms.",
    ),
    video_preset: str | None = typer.Option(
        None,
        "--preset",
        help="ffmpeg x264 preset (slower = better quality at same size).",
    ),
    audio_bitrate: str | None = typer.Option(
        None,
        "--audio-bitrate",
        help="Audio bitrate (e.g., 256k). Ignored if --audio-copy is set.",
    ),
    audio_copy: bool | None = typer.Option(
        None,
        "--audio-copy/--reencode-audio",
        help="Copy input audio instead of re-encoding to AAC (default: auto-detect AAC).",
    ),
    artifacts_dir: Path | None = typer.Option(
        None,
        "--artifacts",
        "-a",
        file_okay=False,
        dir_okay=True,
        writable=True,
        readable=False,
        resolve_path=True,
        help="Directory where intermediate audio/SRT/ASS and social copy files will be saved.",
    ),
    social_copy: bool = typer.Option(
        True,
        "--social-copy/--no-social-copy",
        help="Generate platform-ready titles and descriptions from the transcript.",
    ),
) -> None:
    """Normalize a video, transcribe Greek audio, and burn styled subtitles."""
    result = process_video_pipeline(
        input_video,
        output_video,
        transcribe_tier=tier,
        transcribe_provider=provider,
        language=language,
        beam_size=beam_size,
        best_of=best_of,
        device=device,
        compute_type=compute_type,
        video_crf=video_crf,
        video_preset=video_preset,
        audio_bitrate=audio_bitrate,
        audio_copy=audio_copy,
        generate_social_copy=social_copy,
        artifact_dir=artifacts_dir,
    )
    processed_path = result[0] if isinstance(result, tuple) else result
    typer.echo(f"Processed video saved to: {processed_path}")

    if isinstance(result, tuple):
        social = result[1]
        typer.echo("\nGenerated Social Copy:")
        typer.echo(f"Title [EL]: {social.generic.title_el}")
        typer.echo(f"Title [EN]: {social.generic.title_en}")
        typer.echo(f"Description [EL]:\n{social.generic.description_el}")
        typer.echo(f"Description [EN]:\n{social.generic.description_en}")
        if social.generic.hashtags:
            typer.echo(f"Hashtags: {' '.join(social.generic.hashtags)}")


def main() -> None:
    """Entry point for `python -m backend.cli`."""
    app()  # pragma: no cover


if __name__ == "__main__":
    main()  # pragma: no cover
