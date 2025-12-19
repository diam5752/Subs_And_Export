from pathlib import Path
from typing import List

from backend.app.services.subtitle_types import Cue, TimeRange, WordTiming
from backend.app.services.llm_utils import resolve_groq_api_key
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments


class GroqTranscriber(Transcriber):
    """
    Transcriber using Groq Cloud API for ultra-fast inference.
    """

    def __init__(self, api_key: str = None):
        self.api_key = api_key

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "whisper-large-v3", **kwargs) -> tuple[Path, List[Cue]]:
        prompt = kwargs.get("initial_prompt")
        progress_callback = kwargs.get("progress_callback")
        check_cancelled = kwargs.get("check_cancelled")

        # Check cancellation before starting
        if check_cancelled:
            check_cancelled()

        # Resolve API Key
        api_key = self.api_key or resolve_groq_api_key()
        if not api_key:
            raise RuntimeError(
                "Groq API key is required. Set GROQ_API_KEY env var or add to config/secrets.toml"
            )

        # Groq uses OpenAI-compatible API
        try:
            from openai import OpenAI
        except ImportError:
            raise RuntimeError("openai package is required for Groq transcription")

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1"
        )

        if progress_callback:
            progress_callback(10.0)

        # Check cancellation before API call
        if check_cancelled:
            check_cancelled()

        try:
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=model,
                    file=audio_file,
                    language=language or "el",
                    prompt=prompt,
                    response_format="verbose_json",
                    timestamp_granularities=["word", "segment"],
                    timeout=300.0,
                )
        except Exception as exc:
            raise RuntimeError(f"Groq transcription failed: {exc}") from exc

        # Check cancellation after API call
        if check_cancelled:
            check_cancelled()

        if progress_callback:
            progress_callback(90.0)

        # Convert response to our Cue/WordTiming format (same as OpenAI)
        cues: List[Cue] = []
        timed_text: List[TimeRange] = []

        if hasattr(transcript, "segments"):
            for seg in transcript.segments:
                seg_text = seg.text or ""
                seg_start = seg.start
                seg_end = seg.end

                current_words: List[WordTiming] = []
                all_words = getattr(transcript, "words", [])
                if all_words:
                    seg_words_data = [
                        w for w in all_words
                        if w.start >= seg_start and w.start < seg_end
                    ]
                    current_words = [
                        WordTiming(start=w.start, end=w.end, text=normalize_text(w.word))
                        for w in seg_words_data
                    ]

                processed_text = normalize_text(seg_text)
                cues.append(Cue(start=seg_start, end=seg_end, text=processed_text, words=current_words))
                timed_text.append((seg_start, seg_end, seg_text))

        if progress_callback:
            progress_callback(100.0)

        srt_path = output_dir / f"{audio_path.stem}.srt"
        write_srt_from_segments(timed_text, srt_path)

        return srt_path, cues
