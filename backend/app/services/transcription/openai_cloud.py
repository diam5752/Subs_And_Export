from pathlib import Path
from typing import List, Optional

from backend.app.services.subtitles import Cue, WordTiming, TimeRange, _resolve_openai_api_key, _load_openai_client
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments


class OpenAITranscriber(Transcriber):
    """
    Transcriber using OpenAI official Whisper API.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    def transcribe(self, audio_path: Path, output_dir: Path, language: str = "en", model: str = "whisper-1", **kwargs) -> tuple[Path, List[Cue]]:
        """
        Transcribe using OpenAI API.
        """
        prompt = kwargs.get("initial_prompt")
        progress_callback = kwargs.get("progress_callback")

        # Resolve API Key
        api_key = self.api_key or _resolve_openai_api_key()
        if not api_key:
            raise RuntimeError(
                "OpenAI API key is required for transcription with 'openai' provider or models."
            )

        client = _load_openai_client(api_key)

        if progress_callback:
            progress_callback(10.0)

        try:
            with open(audio_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=model or "whisper-1",
                    file=audio_file,
                    language=language or "el",
                    prompt=prompt,
                    response_format="verbose_json",
                    timestamp_granularities=["word"] # Get word-level timestamps
                )
        except Exception as exc:
            raise RuntimeError(f"OpenAI transcription failed: {exc}") from exc

        if progress_callback:
            progress_callback(90.0)

        # Convert OpenAI verbose_json response to our Cue/WordTiming format
        cues: List[Cue] = []
        timed_text: List[TimeRange] = []

        # OpenAI returns segments
        if hasattr(transcript, "segments"):
            for seg in transcript.segments:
                seg_text = seg.text or ""
                seg_start = seg.start
                seg_end = seg.end

                current_words: List[WordTiming] = []

                # Let's look at transcript.words if available
                all_words = getattr(transcript, "words", [])
                if all_words:
                     # Filter words belonging to this segment time range
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
