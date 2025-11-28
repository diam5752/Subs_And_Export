from pathlib import Path

import typer

from .video_processing import normalize_and_stub_subtitles

app = typer.Typer(help="Normalize vertical videos and prepare styled Greek subtitles.")


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
    model_size: str = typer.Option(
        None,
        "--model",
        help="faster-whisper model size (e.g., tiny, base, small, medium).",
    ),
    language: str = typer.Option(
        None,
        "--language",
        help="Language code for transcription (default: el).",
    ),
    device: str = typer.Option(
        None,
        "--device",
        help="Device for faster-whisper: cpu, cuda, or auto.",
    ),
    compute_type: str = typer.Option(
        None,
        "--compute-type",
        help="faster-whisper compute type (e.g., int8, float16, auto).",
    ),
    video_crf: int = typer.Option(
        None,
        "--crf",
        help="H.264 CRF (lower = higher quality). Default tuned for Shorts/Reels.",
    ),
    video_preset: str = typer.Option(
        None,
        "--preset",
        help="ffmpeg x264 preset (slower = better quality at same size).",
    ),
    audio_bitrate: str = typer.Option(
        None,
        "--audio-bitrate",
        help="Audio bitrate (e.g., 256k). Ignored if --audio-copy is set.",
    ),
    audio_copy: bool = typer.Option(
        False,
        "--audio-copy",
        help="Copy input audio instead of re-encoding to AAC.",
    ),
) -> None:
    """Normalize a video, transcribe Greek audio, and burn styled subtitles."""
    processed_path = normalize_and_stub_subtitles(
        input_video,
        output_video,
        model_size=model_size,
        language=language,
        device=device,
        compute_type=compute_type,
        video_crf=video_crf,
        video_preset=video_preset,
        audio_bitrate=audio_bitrate,
        audio_copy=audio_copy,
    )
    typer.echo(f"Processed video saved to: {processed_path}")


def main() -> None:
    """Entry point for `python -m greek_sub_publisher.cli`."""
    app()


if __name__ == "__main__":
    main()
