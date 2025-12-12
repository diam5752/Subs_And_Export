from pathlib import Path
from typing import List, Optional

from backend.app.services.subtitles import Cue, generate_subtitles_from_audio
from backend.app.services.transcription.base import Transcriber

class OpenAITranscriber(Transcriber):
    """
    Transcriber using OpenAI official Whisper API.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "whisper-1", **kwargs) -> tuple[Path, List[Cue]]:
        srt_path, cues = generate_subtitles_from_audio(
            audio_path,
            output_dir=output_dir,
            model_size=model,
            language=language,
            provider="openai",
            openai_api_key=self.api_key,
            **kwargs
        )
        return srt_path, cues
