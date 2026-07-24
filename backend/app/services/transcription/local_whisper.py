import importlib
import os
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Callable, Iterable

from backend.app.core.config import settings
from backend.app.services.subtitle_types import Cue, TimeRange, WordTiming
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments

if TYPE_CHECKING:
    from faster_whisper import WhisperModel
else:
    WhisperModel = Any

LOCAL_MODEL_ALIASES: dict[str, str] = {
    "standard": "large-v3-turbo",
    "pro": "large-v3",
    "turbo": "large-v3-turbo",
    "enhanced": "large-v3-turbo",
    "ultimate": "large-v3",
    "whisper-large-v3-turbo": "large-v3-turbo",
    "whisper-large-v3": "large-v3",
}


def _load_faster_whisper() -> ModuleType:
    try:
        return importlib.import_module("faster_whisper")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "faster-whisper is required for local transcription. Install faster-whisper to enable local Whisper."
        ) from exc


def _resolve_local_model_name(model_size: str | None) -> str:
    requested = (model_size or settings.whisper_model).strip().lower()
    if not requested:
        requested = settings.whisper_model.strip().lower()

    return LOCAL_MODEL_ALIASES.get(requested, requested)


def _resolve_compute_type(device: str, compute_type: str) -> str:
    if compute_type and compute_type != "auto":
        return compute_type

    normalized_device = device.strip().lower()
    if normalized_device in {"auto", "cpu"}:
        return "int8"

    return "default"


def _get_whisper_model(
    model_size: str,
    device: str,
    compute_type: str,
    cpu_threads: int,
) -> WhisperModel:
    faster_whisper = _load_faster_whisper()
    model = faster_whisper.WhisperModel(
        model_size_or_path=_resolve_local_model_name(model_size),
        device=device,
        compute_type=_resolve_compute_type(device, compute_type),
        cpu_threads=cpu_threads,
    )
    return model


class LocalWhisperTranscriber(Transcriber):
    """
    Transcriber using local faster-whisper directly.
    """

    def __init__(
        self,
        device: str | None = None,
        compute_type: str | None = None,
        beam_size: int = 5,
    ) -> None:
        self.device = device or settings.whisper_device
        self.compute_type = compute_type or settings.whisper_compute_type
        self.beam_size = beam_size

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        language: str = "en",
        model: str = "base",
        **kwargs: Any,
    ) -> tuple[Path, list[Cue]]:
        progress_callback = kwargs.get("progress_callback")
        check_cancelled = kwargs.get("check_cancelled")

        # Check cancellation before starting expensive operations
        if callable(check_cancelled):
            check_cancelled()

        threads = min(8, os.cpu_count() or 4)

        model_instance = _get_whisper_model(
            model,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=threads,
        )

        # Check cancellation after model loading but before transcription
        if callable(check_cancelled):
            check_cancelled()

        transcribe_kwargs = {
            "language": language or settings.whisper_language,
            "task": "transcribe",
            "word_timestamps": True,
            "vad_filter": kwargs.get("vad_filter", True),
            "condition_on_previous_text": kwargs.get("condition_on_previous_text", False),
        }

        transcribe_kwargs["beam_size"] = kwargs.get("beam_size", self.beam_size)
        best_of = kwargs.get("best_of")
        transcribe_kwargs["best_of"] = best_of if best_of is not None else 2

        temperature = kwargs.get("temperature")
        transcribe_kwargs["temperature"] = temperature if temperature is not None else 0.0

        initial_prompt = kwargs.get("initial_prompt")
        if initial_prompt:
            transcribe_kwargs["initial_prompt"] = initial_prompt

        if callable(progress_callback):
            progress_callback(10.0)

        segments, _info = model_instance.transcribe(str(audio_path), **transcribe_kwargs)

        cues: list[Cue] = []
        timed_text: list[TimeRange] = []
        for seg in _iter_segments(segments, check_cancelled):
            seg_start = seg.start
            seg_end = seg.end
            seg_text = seg.text.strip()

            timed_text.append((seg_start, seg_end, seg_text))

            words: list[WordTiming] | None = None
            if seg.words:
                words = [
                    WordTiming(start=w.start, end=w.end, text=normalize_text(w.word.strip()))
                    for w in seg.words
                    if w.word
                ]

            cue_text = normalize_text(seg_text)
            cues.append(Cue(start=seg_start, end=seg_end, text=cue_text, words=words))

        if callable(check_cancelled):
            check_cancelled()

        if callable(progress_callback):
            progress_callback(100.0)

        srt_path = output_dir / f"{audio_path.stem}.srt"
        write_srt_from_segments(timed_text, srt_path)

        return srt_path, cues


def _iter_segments(
    segments: Iterable[Any],
    check_cancelled: Callable[[], None] | None,
) -> Iterable[Any]:
    for segment in segments:
        if check_cancelled is not None:
            check_cancelled()
        yield segment
