from pathlib import Path
from typing import Any

from backend.app.services.provider_clients import (
    load_openai_compatible_client,
    resolve_openai_api_key,
)
from backend.app.services.subtitle_types import Cue
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.cloud_response import (
    call_callback,
    write_cloud_transcript,
)


class OpenAITranscriber(Transcriber):
    """
    Transcriber using OpenAI official Whisper API.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        language: str = "en",
        model: str = "whisper-1",
        **kwargs: Any,
    ) -> tuple[Path, list[Cue]]:
        """
        Transcribe using OpenAI API.
        """
        selected_model = (model or "whisper-1").strip()
        if selected_model.lower() != "whisper-1":
            raise ValueError(
                "OpenAI caption transcription requires whisper-1 because the selected model "
                "does not provide the word timestamps used by animated subtitles."
            )

        prompt = kwargs.get("initial_prompt")
        progress_callback = kwargs.get("progress_callback")
        check_cancelled = kwargs.get("check_cancelled")

        call_callback(check_cancelled)

        # Resolve API Key
        api_key = self.api_key or resolve_openai_api_key()
        if not api_key:
            raise RuntimeError("OpenAI API key is required for transcription with 'openai' provider or models.")

        client = load_openai_compatible_client(api_key)

        call_callback(progress_callback, 10.0)
        call_callback(check_cancelled)

        try:
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=selected_model,
                    file=audio_file,
                    language=language or "el",
                    prompt=prompt,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                    timeout=300.0,
                )
        except Exception as exc:
            raise RuntimeError(f"OpenAI transcription failed: {exc}") from exc

        call_callback(check_cancelled)
        call_callback(progress_callback, 90.0)
        result = write_cloud_transcript(
            audio_path=audio_path,
            output_dir=output_dir,
            transcript=transcript,
        )
        call_callback(progress_callback, 100.0)
        return result
