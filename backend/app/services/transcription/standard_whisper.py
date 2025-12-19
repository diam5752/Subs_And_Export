import os
from pathlib import Path
from typing import List

from backend.app.core import config
from backend.app.services.subtitle_types import Cue, TimeRange
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments


class StandardTranscriber(Transcriber):
    """
    Transcriber using whisper.cpp with Metal/CoreML acceleration (Apple Silicon optimized).
    """

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "base", **kwargs) -> tuple[Path, List[Cue]]:
        progress_callback = kwargs.get("progress_callback")
        check_cancelled = kwargs.get("check_cancelled")

        # Check cancellation before starting
        if check_cancelled:
            check_cancelled()

        try:
            from pywhispercpp.model import Model as WhisperCppModel
        except ImportError:
            raise RuntimeError(
                "pywhispercpp not installed. For best performance on Apple Silicon, install with CoreML:\n"
                "WHISPER_COREML=1 pip install git+https://github.com/absadiki/pywhispercpp\n"
                "Or for basic install: pip install pywhispercpp"
            )

        model_size = model or config.WHISPERCPP_MODEL
        language = language or config.WHISPERCPP_LANGUAGE

        if progress_callback:
            progress_callback(5.0)

        # Initialize whisper.cpp model
        model_instance = WhisperCppModel(
            model_size,
            print_realtime=False,
            print_progress=False,
        )

        # Check cancellation after model loading
        if check_cancelled:
            check_cancelled()

        if progress_callback:
            progress_callback(15.0)

        # Transcribe
        segments = model_instance.transcribe(
            str(audio_path),
            language=language,
            n_threads=min(8, os.cpu_count() or 4),
        )

        # Check cancellation after transcription
        if check_cancelled:
            check_cancelled()

        if progress_callback:
            progress_callback(85.0)


        cues: List[Cue] = []
        timed_text: List[TimeRange] = []

        for seg in segments:
            seg_start = seg.t0 / 100.0  # centiseconds to seconds
            seg_end = seg.t1 / 100.0
            seg_text = seg.text.strip()

            if not seg_text:
                continue

            # Normalize the full segment text
            normalized_text = normalize_text(seg_text)
            if not normalized_text:
                continue

            # Standard model: No word columns, just block text
            cues.append(Cue(start=seg_start, end=seg_end, text=normalized_text, words=None))
            timed_text.append((seg_start, seg_end, seg_text))

        srt_path = output_dir / f"{audio_path.stem}.srt"
        write_srt_from_segments(timed_text, srt_path)

        if progress_callback:
            progress_callback(100.0)

        return srt_path, cues
