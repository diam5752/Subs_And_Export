"""Zero-cost deterministic transcription used by the product's mock mode."""

from __future__ import annotations

from pathlib import Path

from backend.app.services.subtitle_types import Cue, WordTiming
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments

_PHRASES = (
    "Αυτό είναι ένα ασφαλές mock transcript",
    "Δοκιμάζουμε τον ρυθμό και τα animated subtitles",
    "Καμία εξωτερική υπηρεσία AI δεν καλείται",
    "Το export παράγεται κανονικά στη συσκευή σου",
)


class MockTranscriber(Transcriber):
    """Produce honest demo cues with word timings and no network access."""

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        language: str = "el",
        model: str = "mock-caption-v1",
        **kwargs: object,
    ) -> tuple[Path, list[Cue]]:
        del language, model
        check_cancelled = kwargs.get("check_cancelled")
        progress_callback = kwargs.get("progress_callback")
        if callable(check_cancelled):
            check_cancelled()
        if callable(progress_callback):
            progress_callback(10.0)

        total_duration = max(1.0, float(kwargs.get("total_duration") or 12.0))
        cue_count = min(len(_PHRASES), max(1, round(total_duration / 3.0)))
        cue_duration = total_duration / cue_count
        cues: list[Cue] = []
        segments: list[tuple[float, float, str]] = []

        for index, phrase in enumerate(_PHRASES[:cue_count]):
            start = index * cue_duration
            end = min(total_duration, (index + 1) * cue_duration)
            normalized_phrase = normalize_text(phrase)
            tokens = normalized_phrase.split()
            word_duration = (end - start) / max(1, len(tokens))
            words = [
                WordTiming(
                    start=start + token_index * word_duration,
                    end=min(end, start + (token_index + 1) * word_duration),
                    text=token,
                )
                for token_index, token in enumerate(tokens)
            ]
            cues.append(Cue(start=start, end=end, text=normalized_phrase, words=words))
            segments.append((start, end, normalized_phrase))

        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = write_srt_from_segments(segments, output_dir / f"{audio_path.stem}.srt")
        if callable(progress_callback):
            progress_callback(100.0)
        return srt_path, cues
