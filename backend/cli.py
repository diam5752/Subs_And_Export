from pathlib import Path

import typer

from backend.app.services.video_processing import normalize_and_stub_subtitles

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
        help="H.264 CRF (lower = higher quality). Default tuned for social platforms.",
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
    audio_copy: bool | None = typer.Option(
        None,
        "--audio-copy/--reencode-audio",
        help="Copy input audio instead of re-encoding to AAC (default: auto-detect AAC).",
    ),
    llm_social_copy: bool = typer.Option(
        False,
        "--llm-social-copy/--no-llm-social-copy",
        help="Use OpenAI GPT models to generate professional social copy (requires OPENAI_API_KEY).",
    ),
    llm_model: str = typer.Option(
        None,
        "--llm-model",
        help="OpenAI model name (defaults to gpt-5.1-mini).",
    ),
    llm_temperature: float = typer.Option(
        0.6,
        "--llm-temperature",
        min=0.0,
        max=2.0,
        help="Sampling temperature for LLM social copy.",
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
    result = normalize_and_stub_subtitles(
        input_video,
        output_video,
        model_size=model_size,
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
        use_llm_social_copy=llm_social_copy,
        llm_model=llm_model,
        llm_temperature=llm_temperature,
        llm_api_key=None,  # CLI relies on env var for now
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
