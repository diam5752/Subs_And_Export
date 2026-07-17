"""Fail-closed ElevenLabs Scribe v2 transcription adapter."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests

from backend.app.core.config import settings
from backend.app.services.llm_utils import resolve_elevenlabs_api_key
from backend.app.services.subtitle_types import Cue, WordTiming
from backend.app.services.transcription.base import Transcriber
from backend.app.services.transcription.utils import normalize_text, write_srt_from_segments

SCRIBE_ENDPOINT = "https://api.elevenlabs.io/v1/speech-to-text"
_LANGUAGE_CODES = {"el": "ell", "en": "eng"}
_CUE_ENDINGS = (".", "!", "?", ";", "·")


class ElevenLabsScribeTranscriber(Transcriber):
    """Convert Scribe v2 word timestamps into the application's cue contract."""

    def __init__(
        self,
        api_key: str | None = None,
        transport: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self._transport = transport or requests.post

    @staticmethod
    def _language_code(language: str | None) -> str | None:
        normalized = (language or "").strip().lower()
        if not normalized or normalized == "auto":
            return None
        return _LANGUAGE_CODES.get(normalized, normalized)

    @staticmethod
    def _parse_words(payload: dict[str, Any]) -> list[WordTiming]:
        raw_words = payload.get("words")
        if not isinstance(raw_words, list):
            return []

        words: list[WordTiming] = []
        for item in raw_words:
            if not isinstance(item, dict) or item.get("type") != "word":
                continue
            text = item.get("text")
            start = item.get("start")
            end = item.get("end")
            if not isinstance(text, str) or not text.strip():
                continue
            if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
                continue
            if float(end) <= float(start):
                continue
            words.append(
                WordTiming(
                    start=float(start),
                    end=float(end),
                    text=normalize_text(text.strip()),
                )
            )
        return words

    @staticmethod
    def _build_cues(words: list[WordTiming]) -> list[Cue]:
        cues: list[Cue] = []
        current: list[WordTiming] = []

        def flush() -> None:
            if not current:
                return
            cue_words = list(current)
            cues.append(
                Cue(
                    start=cue_words[0].start,
                    end=cue_words[-1].end,
                    text=" ".join(word.text for word in cue_words),
                    words=cue_words,
                )
            )
            current.clear()

        for word in words:
            current.append(word)
            duration = current[-1].end - current[0].start
            sentence_end = word.text.endswith(_CUE_ENDINGS)
            if sentence_end or len(current) >= 8 or duration >= 3.5:
                flush()
        flush()
        return cues

    def transcribe(
        self,
        audio_path: Path,
        output_dir: Path,
        language: str = "el",
        model: str = "scribe_v2",
        **kwargs: Any,
    ) -> tuple[Path, list[Cue]]:
        selected_model = (model or settings.elevenlabs_transcribe_model).strip()
        if selected_model != settings.elevenlabs_transcribe_model:
            raise ValueError("ElevenLabs caption transcription requires scribe_v2")
        if not settings.elevenlabs_enabled:
            raise RuntimeError("ElevenLabs Scribe v2 is disabled.")
        if settings.mock_external_services:
            raise RuntimeError("ElevenLabs Scribe v2 cannot run while mock mode is active.")
        if (
            settings.external_provider_monthly_budget_usd <= 0
            or settings.external_provider_per_request_budget_usd <= 0
        ):
            raise RuntimeError("ElevenLabs Scribe v2 safety budgets are closed.")

        api_key = self.api_key or resolve_elevenlabs_api_key()
        if not api_key:
            raise RuntimeError("ElevenLabs API key is required for Scribe v2 transcription.")

        check_cancelled = kwargs.get("check_cancelled")
        progress_callback = kwargs.get("progress_callback")
        if callable(check_cancelled):
            check_cancelled()
        if callable(progress_callback):
            progress_callback(10.0)

        form_data = {
            "model_id": selected_model,
            "timestamps_granularity": "word",
            "diarize": "false",
            "tag_audio_events": "false",
        }
        language_code = self._language_code(language)
        if language_code:
            form_data["language_code"] = language_code

        try:
            with audio_path.open("rb") as audio_file:
                response = self._transport(
                    SCRIBE_ENDPOINT,
                    headers={"xi-api-key": api_key},
                    data=form_data,
                    files={"file": (audio_path.name, audio_file, "audio/wav")},
                    timeout=(10.0, 300.0),
                )
            response.raise_for_status()
            raw_payload = response.json()
        except requests.RequestException as exc:
            raise RuntimeError("ElevenLabs Scribe v2 transcription failed.") from exc

        if callable(check_cancelled):
            check_cancelled()
        if callable(progress_callback):
            progress_callback(90.0)
        if not isinstance(raw_payload, dict):
            raise RuntimeError("ElevenLabs Scribe v2 returned an invalid response.")

        words = self._parse_words(raw_payload)
        if not words:
            raise RuntimeError("ElevenLabs Scribe v2 response did not include word timestamps.")
        cues = self._build_cues(words)
        segments = [(cue.start, cue.end, cue.text) for cue in cues]
        output_dir.mkdir(parents=True, exist_ok=True)
        srt_path = write_srt_from_segments(segments, output_dir / f"{audio_path.stem}.srt")

        if callable(progress_callback):
            progress_callback(100.0)
        return srt_path, cues
