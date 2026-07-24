from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from backend.app.services.subtitle_types import Cue


class Transcriber(ABC):
    """
    Abstract base class for all transcription providers.
    """

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        language: str = "en",
        model: str = "base",
        **kwargs: Any,
    ) -> tuple[Path, list[Cue]]:
        """
        Transcribe audio file into a list of timed Cues.

        Args:
            audio_path: Absolute path to the audio file.
            output_dir: Directory where intermediate artifacts (SRT, etc.) should be saved.
            language: Language code (e.g., 'en', 'el').
            model: Model size/name identifier appropriate for the provider.
            **kwargs: Additional provider-specific arguments (temperature, vad_filter, etc.).

        Returns:
            The generated SRT path and timed cues.
        """
        raise NotImplementedError
