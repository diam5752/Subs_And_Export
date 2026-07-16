"""Capability-first catalog for transcription engines.

The product needs word timings for animated captions. Newer text transcription
models are deliberately kept out of that flow when their API does not expose
word timestamps; marketing recency is not treated as a substitute for a usable
subtitle contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

TranscriptionProvider = Literal["mock", "groq", "local", "openai"]
TranscriptionTier = Literal["standard", "pro"]
ProcessingPrivacy = Literal["cloud", "local"]


@dataclass(frozen=True, slots=True)
class TranscriptionEngine:
    id: str
    tier: TranscriptionTier
    provider: TranscriptionProvider
    model: str
    label: str
    description: str
    privacy: ProcessingPrivacy
    supports_word_timestamps: bool
    supports_diarization: bool
    supports_realtime: bool
    caption_ready: bool
    recommended: bool
    cost_usd_per_hour: float | None
    limitations: tuple[str, ...] = ()


def list_transcription_engines(*, caption_ready_only: bool = False) -> tuple[TranscriptionEngine, ...]:
    """Return the supported engine catalog in product recommendation order."""
    engines = (
        TranscriptionEngine(
            id="mock-studio",
            tier="standard",
            provider="mock",
            model="mock-caption-v1",
            label="Demo studio",
            description="Deterministic word-timed captions for testing the complete product with zero provider calls.",
            privacy="local",
            supports_word_timestamps=True,
            supports_diarization=False,
            supports_realtime=False,
            caption_ready=True,
            recommended=True,
            cost_usd_per_hour=0.0,
            limitations=("Transcript text is simulated while mock mode is enabled.",),
        ),
        TranscriptionEngine(
            id="groq-accurate",
            tier="pro",
            provider="groq",
            model="whisper-large-v3",
            label="Accuracy",
            description="Highest-accuracy Greek and multilingual captions with word-level timing.",
            privacy="cloud",
            supports_word_timestamps=True,
            supports_diarization=False,
            supports_realtime=False,
            caption_ready=True,
            recommended=False,
            cost_usd_per_hour=0.111,
        ),
        TranscriptionEngine(
            id="groq-fast",
            tier="standard",
            provider="groq",
            model="whisper-large-v3-turbo",
            label="Fast",
            description="Near-instant multilingual captions with word-level timing and low cost.",
            privacy="cloud",
            supports_word_timestamps=True,
            supports_diarization=False,
            supports_realtime=False,
            caption_ready=True,
            recommended=False,
            cost_usd_per_hour=0.04,
        ),
        TranscriptionEngine(
            id="local-private",
            tier="standard",
            provider="local",
            model="large-v3-turbo",
            label="Private",
            description="Offline transcription on the application server; media never reaches an AI provider.",
            privacy="local",
            supports_word_timestamps=True,
            supports_diarization=False,
            supports_realtime=False,
            caption_ready=True,
            recommended=False,
            cost_usd_per_hour=0.0,
            limitations=("Speed depends on the server CPU or GPU.",),
        ),
        TranscriptionEngine(
            id="openai-precision-text",
            tier="pro",
            provider="openai",
            model="gpt-4o-transcribe",
            label="Precision text",
            description="High-accuracy transcript text for workflows that do not require per-word animation.",
            privacy="cloud",
            supports_word_timestamps=False,
            supports_diarization=False,
            supports_realtime=False,
            caption_ready=False,
            recommended=False,
            cost_usd_per_hour=None,
            limitations=("The API returns JSON text but not word-level timestamps.",),
        ),
        TranscriptionEngine(
            id="openai-diarized",
            tier="pro",
            provider="openai",
            model="gpt-4o-transcribe-diarize",
            label="Speakers",
            description="Speaker-aware transcript segments for interviews and podcasts.",
            privacy="cloud",
            supports_word_timestamps=False,
            supports_diarization=True,
            supports_realtime=False,
            caption_ready=False,
            recommended=False,
            cost_usd_per_hour=None,
            limitations=("Speaker segments cannot drive word-level karaoke animation.",),
        ),
    )
    if caption_ready_only:
        return tuple(engine for engine in engines if engine.caption_ready)
    return engines


def find_transcription_engine(
    engines: Iterable[TranscriptionEngine],
    *,
    provider: TranscriptionProvider,
    model: str,
) -> TranscriptionEngine | None:
    normalized_model = model.strip().lower()
    return next(
        (
            engine
            for engine in engines
            if engine.provider == provider and engine.model.lower() == normalized_model
        ),
        None,
    )
