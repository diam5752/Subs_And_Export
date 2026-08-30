from pathlib import Path
from typing import Any

from backend.app.services.provider_clients import (
    load_openai_compatible_client,
    resolve_groq_api_key,
)
from backend.app.services.subtitle_types import Cue
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.cloud_response import (
    call_callback,
    write_cloud_transcript,
)


class GroqTranscriber(Transcriber):
    """
    Transcriber using Groq Cloud API for ultra-fast inference.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        language: str = "en",
        model: str = "whisper-large-v3",
        **kwargs: Any,
    ) -> tuple[Path, list[Cue]]:
        prompt = kwargs.get("initial_prompt")
        progress_callback = kwargs.get("progress_callback")
        check_cancelled = kwargs.get("check_cancelled")

        call_callback(check_cancelled)

        # Resolve API Key
        api_key = self.api_key or resolve_groq_api_key()
        if not api_key:
            raise RuntimeError("Groq API key is required. Set GROQ_API_KEY env var or add to config/secrets.toml")

        # Groq uses OpenAI-compatible API
        client = load_openai_compatible_client(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        call_callback(progress_callback, 10.0)
        call_callback(check_cancelled)

        try:
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    language=language or "el",
                    prompt=prompt,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                    timeout=300.0,
                )
        except Exception as exc:
            raise RuntimeError(f"Groq transcription failed: {exc}") from exc

        call_callback(check_cancelled)
        call_callback(progress_callback, 90.0)
        result = write_cloud_transcript(
            audio_path=audio_path,
            output_dir=output_dir,
            transcript=transcript,
        )
        call_callback(progress_callback, 100.0)
        return result
