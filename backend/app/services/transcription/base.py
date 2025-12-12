from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from backend.app.services.subtitles import Cue

class Transcriber(ABC):
    """
    Abstract base class for all transcription providers.
    """
    
    @abstractmethod
    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "base", **kwargs) -> tuple[Path, List[Cue]]:
        """
        Transcribe audio file into a list of timed Cues.
        
        Args:
            audio_path: Absolute path to the audio file.
            output_dir: Directory where intermediate artifacts (SRT, etc.) should be saved.
            language: Language code (e.g., 'en', 'el').
            model: Model size/name identifier appropriate for the provider.
            **kwargs: Additional provider-specific arguments (temperature, vad_filter, etc.).
        
        Returns:
            Tuple[Path, List[Cue]]: The path to the generated SRT file and the list of cues.
        """
        pass
