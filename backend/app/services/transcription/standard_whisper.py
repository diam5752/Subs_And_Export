import os
import unicodedata
from pathlib import Path
from typing import List

from backend.app.core import config
from backend.app.services.subtitles import Cue, TimeRange
from backend.app.services.transcription.base import Transcriber


def _normalize_text(text: str) -> str:
    """
    Uppercase + strip accents for consistent, bold subtitle styling.
    Duplicated here to ensure Standard Model independence.
    """
    normalized = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return stripped.upper()

def _format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:01d}:{minutes:02d}:{secs:05.2f}"

def _write_srt_from_segments(segments: List[TimeRange], dest: Path) -> Path:
    lines: List[str] = []
    for idx, (start, end, text) in enumerate(segments, start=1):
        start_ts = _format_timestamp(start)
        end_ts = _format_timestamp(end)
        lines.append(str(idx))
        lines.append(f"{start_ts.replace('.', ',')} --> {end_ts.replace('.', ',')}")
        lines.append(text.strip())
        lines.append("")  # blank line separator
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest

class StandardTranscriber(Transcriber):
    """
    Transcriber using whisper.cpp with Metal/CoreML acceleration (Apple Silicon optimized).
    """

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "base", **kwargs) -> tuple[Path, List[Cue]]:
        progress_callback = kwargs.get("progress_callback")

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

        if progress_callback:
            progress_callback(15.0)

        # Transcribe
        segments = model_instance.transcribe(
            str(audio_path),
            language=language,
            n_threads=min(8, os.cpu_count() or 4),
        )

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
            normalized_text = _normalize_text(seg_text)
            if not normalized_text:
                continue

            # Standard model: No word columns, just block text
            cues.append(Cue(start=seg_start, end=seg_end, text=normalized_text, words=None))
            timed_text.append((seg_start, seg_end, seg_text))

        srt_path = output_dir / f"{audio_path.stem}.srt"
        _write_srt_from_segments(timed_text, srt_path)

        if progress_callback:
            progress_callback(100.0)

        return srt_path, cues
