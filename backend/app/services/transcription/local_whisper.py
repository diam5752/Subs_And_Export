import os
from pathlib import Path
from typing import List, Optional

import stable_whisper

from backend.app.core.config import settings
from backend.app.services.subtitle_types import Cue, TimeRange, WordTiming
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments


def _get_whisper_model(
    model_size: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
) -> stable_whisper.WhisperResult:
    """
    Load a Stable-Whisper wrapped Faster-Whisper model.
    """
    if model_size == "turbo":
        model_size = settings.whisper_model

    # stable-ts wrapper for faster-whisper
    model = stable_whisper.load_faster_whisper(
        model_size_or_path=model_size,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads,
    )
    return model


class LocalWhisperTranscriber(Transcriber):
    """
    Transcriber using local faster-whisper (via stable-ts).
    """

    def __init__(self,
                 device: Optional[str] = None,
                 compute_type: Optional[str] = None,
                 beam_size: int = 5):
        self.device = device or settings.whisper_device
        self.compute_type = compute_type or settings.whisper_compute_type
        self.beam_size = beam_size

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "base", **kwargs) -> tuple[Path, List[Cue]]:
        progress_callback = kwargs.get("progress_callback")
        check_cancelled = kwargs.get("check_cancelled")

        # Check cancellation before starting expensive operations
        if check_cancelled:
            check_cancelled()

        # Default: Stabel-TS wrapping Faster-Whisper
        threads = min(8, os.cpu_count() or 4)

        # Load model using stable-ts wrapper
        model_instance = _get_whisper_model(
            model,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=threads,
        )

        # Check cancellation after model loading but before transcription
        if check_cancelled:
            check_cancelled()

        transcribe_kwargs = {
            "language": language or settings.whisper_language,
            "task": "transcribe",
            "word_timestamps": True,
            "vad": kwargs.get("vad_filter", True),
            "regroup": True,
            "suppress_silence": True,
            "suppress_word_ts": False,
            "vad_threshold": 0.35,
            "condition_on_previous_text": kwargs.get("condition_on_previous_text", False),
            "verbose": False,
        }

        transcribe_kwargs["beam_size"] = kwargs.get("beam_size", self.beam_size)
        best_of = kwargs.get("best_of")
        transcribe_kwargs["best_of"] = best_of if best_of is not None else 2

        temperature = kwargs.get("temperature")
        transcribe_kwargs["temperature"] = temperature if temperature is not None else 0.0

        initial_prompt = kwargs.get("initial_prompt")
        if initial_prompt:
            transcribe_kwargs["initial_prompt"] = initial_prompt

        result = model_instance.transcribe(str(audio_path), **transcribe_kwargs)

        # CRITICAL: Check cancellation immediately after blocking transcription
        # This prevents further processing if user cancelled during inference
        if check_cancelled:
            check_cancelled()

        cues: List[Cue] = []
        timed_text: List[TimeRange] = []

        for seg in result.segments:
            seg_start = seg.start
            seg_end = seg.end
            seg_text = seg.text

            timed_text.append((seg_start, seg_end, seg_text))

            words: Optional[List[WordTiming]] = None
            if seg.words:
                words = [
                    WordTiming(start=w.start, end=w.end, text=normalize_text(w.word))
                    for w in seg.words
                ]

            cue_text = normalize_text(seg_text)
            cues.append(Cue(start=seg_start, end=seg_end, text=cue_text, words=words))

        if progress_callback:
            progress_callback(100.0)

        srt_path = output_dir / f"{audio_path.stem}.srt"
        write_srt_from_segments(timed_text, srt_path)

        return srt_path, cues
