from pathlib import Path
from typing import List

from backend.app.services.subtitles import Cue, generate_subtitles_from_audio
from backend.app.services.transcription.base import Transcriber

class GroqTranscriber(Transcriber):
    """
    Transcriber using Groq Cloud API for ultra-fast inference.
    """
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key 
        # API key is typically loaded from env inside the subtitles module or config

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "whisper-large-v3", **kwargs) -> tuple[Path, List[Cue]]:
        # Using the existing shared function but specifying provider="groq"
        srt_path, cues = generate_subtitles_from_audio(
            audio_path,
            output_dir=output_dir,
            model_size=model,
            language=language,
            provider="groq",
            **kwargs
        )
        return srt_path, cues
