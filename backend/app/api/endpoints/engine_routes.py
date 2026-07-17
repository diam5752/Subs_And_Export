"""Transcription engine discovery for web and mobile clients."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...core.auth import User
from ...core.config import settings
from ...services.llm_utils import (
    resolve_elevenlabs_api_key,
    resolve_groq_api_key,
    resolve_openai_api_key,
)
from ...services.transcription.catalog import TranscriptionEngine, list_transcription_engines
from ..deps import get_current_user

router = APIRouter()


class TranscriptionEngineResponse(BaseModel):
    id: str
    tier: str
    provider: str
    model: str
    label: str
    description: str
    privacy: str
    supports_word_timestamps: bool
    supports_diarization: bool
    supports_realtime: bool
    caption_ready: bool
    recommended: bool
    available: bool
    cost_usd_per_hour: float | None
    limitations: list[str]


def _provider_available(engine: TranscriptionEngine) -> bool:
    if settings.mock_external_services:
        return engine.provider == "mock"
    if engine.provider == "mock":
        return False
    if engine.provider == "local":
        return True
    if engine.provider == "groq":
        return bool(resolve_groq_api_key())
    if engine.provider == "elevenlabs":
        budgets_open = (
            settings.external_provider_monthly_budget_usd > 0
            and settings.external_provider_per_request_budget_usd > 0
        )
        return settings.elevenlabs_enabled and budgets_open and bool(resolve_elevenlabs_api_key())
    return bool(resolve_openai_api_key())


@router.get("/transcription-engines", response_model=list[TranscriptionEngineResponse])
def transcription_engines(
    _current_user: User = Depends(get_current_user),
) -> list[TranscriptionEngineResponse]:
    """Expose provider capabilities without exposing provider credentials."""
    return [
        TranscriptionEngineResponse(
            id=engine.id,
            tier=engine.tier,
            provider=engine.provider,
            model=engine.model,
            label=engine.label,
            description=engine.description,
            privacy=engine.privacy,
            supports_word_timestamps=engine.supports_word_timestamps,
            supports_diarization=engine.supports_diarization,
            supports_realtime=engine.supports_realtime,
            caption_ready=engine.caption_ready,
            recommended=engine.recommended and _provider_available(engine),
            available=_provider_available(engine),
            cost_usd_per_hour=engine.cost_usd_per_hour,
            limitations=list(engine.limitations),
        )
        for engine in list_transcription_engines()
    ]
