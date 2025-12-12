from pathlib import Path
from typing import List, Optional

from backend.app.core import config
from backend.app.services.subtitles import Cue, generate_subtitles_from_audio
from backend.app.services.transcription.base import Transcriber


class LocalWhisperTranscriber(Transcriber):
    """
    Transcriber using local faster-whisper or whisper.cpp via the existing subtitles module.
    """

    def __init__(self,
                 device: Optional[str] = None,
                 compute_type: Optional[str] = None,
                 beam_size: int = 5):
        self.device = device or config.WHISPER_DEVICE
        self.compute_type = compute_type or config.WHISPER_COMPUTE_TYPE
        self.beam_size = beam_size

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "base", **kwargs) -> tuple[Path, List[Cue]]:
        # Reuse existing logic in subtitles.py which handles details well
        # In a full refactor, we would move that logic here.
        # For now, we wrap it to satisfy the interface.

        srt_path, cues = generate_subtitles_from_audio(
            audio_path,
            output_dir=output_dir,
            model_size=model,
            language=language,
            device=self.device,
            compute_type=self.compute_type,
            beam_size=self.beam_size,
            provider="local",
            **kwargs
        )
        return srt_path, cues
