"""Memory-only audio transcription for native local-media clients."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.core.config import settings
from backend.app.core.errors import sanitize_message
from backend.app.core.media_capacity import (
    lock_provider_transcription,
    provider_transcription_slot_weight,
)
from backend.app.services import pricing
from backend.app.services.charge_plans import reserve_processing_charges
from backend.app.services.jobs import Job, JobStore
from backend.app.services.points import make_idempotency_id
from backend.app.services.subtitle_types import Cue
from backend.app.services.transcription.elevenlabs_scribe import (
    ElevenLabsScribeTranscriber,
)
from backend.app.services.transcription.mock_service import MockTranscriber
from backend.app.services.usage_ledger import ChargeReservation, UsageLedgerStore
from backend.app.services.video_processing import resolve_runtime_transcribe_provider


@dataclass(frozen=True, slots=True)
class MobileTranscriptionEngine:
    tier: str
    provider: str
    model: str


class MobileTranscriptionInProgressError(RuntimeError):
    """The same idempotent request already owns provider dispatch."""


class MobileTranscriptionTerminalError(RuntimeError):
    """The same idempotency key belongs to a failed terminal request."""


def resolve_mobile_transcription_engine() -> MobileTranscriptionEngine:
    """Choose the reviewed engine on the server; the client cannot override it."""
    if settings.mock_external_services:
        return MobileTranscriptionEngine(
            tier="standard",
            provider="mock",
            model="mock-caption-v1",
        )
    provider = resolve_runtime_transcribe_provider("elevenlabs")
    return MobileTranscriptionEngine(
        tier="pro",
        provider=provider,
        model=settings.elevenlabs_transcribe_model,
    )


def cue_payload(cue: Cue) -> dict[str, Any]:
    words = cue.words or []
    return {
        "start": cue.start,
        "end": cue.end,
        "text": cue.text,
        "words": [{"start": word.start, "end": word.end, "text": word.text} for word in words],
    }


def _mobile_job_id(user_id: str, idempotency_key: str) -> str:
    return "mobile-" + make_idempotency_id(
        "mobile-transcription",
        user_id,
        idempotency_key,
    )


def _usage_idempotency_key(user_id: str, job_id: str) -> str:
    return make_idempotency_id("usage", "transcription", user_id, job_id)


def get_mobile_transcription_replay(
    *,
    user_id: str,
    idempotency_key: str,
    ledger_store: UsageLedgerStore,
) -> dict[str, Any] | None:
    """Return a completed response without consulting live provider gates."""
    job_id = _mobile_job_id(user_id, idempotency_key)
    result = ledger_store.get_finalized_result_by_idempotency(
        user_id=user_id,
        idempotency_key=_usage_idempotency_key(user_id, job_id),
    )
    if result is None:
        return None
    return {
        **result,
        "balance": ledger_store.points_store.get_balance(user_id),
    }


def _job_for_request(
    *,
    job_store: JobStore,
    user_id: str,
    idempotency_key: str,
) -> tuple[Job, bool]:
    job_id = _mobile_job_id(user_id, idempotency_key)
    existing = job_store.get_job(job_id)
    if existing is not None:
        if existing.user_id != user_id:
            raise RuntimeError("Mobile transcription ownership conflict")
        return existing, False
    job = job_store.create_job(
        job_id,
        user_id,
        result_data={"kind": "mobile_transcription", "server_media_retained": False},
    )
    return job, True


def _reserve_request(
    *,
    ledger_store: UsageLedgerStore,
    job: Job,
    engine: MobileTranscriptionEngine,
    duration_seconds: float,
) -> tuple[ChargeReservation, int]:
    charge_plan, balance = reserve_processing_charges(
        ledger_store=ledger_store,
        user_id=job.user_id,
        job_id=job.id,
        tier=engine.tier,
        duration_seconds=duration_seconds,
        provider=engine.provider,
        stt_model=engine.model,
    )
    if charge_plan.transcription is None:
        raise RuntimeError("Mobile transcription charge is unavailable")
    return charge_plan.transcription, balance


def _dispatch_audio(
    *,
    engine: MobileTranscriptionEngine,
    audio_bytes: bytes,
    content_type: str,
    duration_seconds: float,
) -> list[Cue]:
    if engine.provider == "mock":
        return MockTranscriber.build_cues(duration_seconds)
    with lock_provider_transcription(
        slots_required=provider_transcription_slot_weight(duration_seconds),
    ):
        return ElevenLabsScribeTranscriber().transcribe_bytes(
            audio_bytes,
            filename="gsubs-mobile-audio.m4a",
            content_type=content_type,
            language="el",
            model=engine.model,
        )


def _result_payload(
    *,
    job_id: str,
    duration_seconds: float,
    credits_charged: int,
    cues: list[Cue],
) -> dict[str, Any]:
    return {
        "request_id": job_id,
        "duration_seconds": duration_seconds,
        "credits_charged": credits_charged,
        "video_uploaded": False,
        "server_media_retained": False,
        "cues": [cue_payload(cue) for cue in cues],
    }


def _fail_request(
    *,
    ledger_store: UsageLedgerStore,
    job_store: JobStore,
    reservation: ChargeReservation,
    error: Exception,
) -> None:
    safe_error = sanitize_message(str(error))
    try:
        ledger_store.fail(reservation, status="failed", error=safe_error)
    finally:
        job_store.update_job_if_status(
            reservation.job_id or "",
            expected_statuses={"pending", "processing"},
            status="failed",
            message="Transcription failed",
        )


def _claim_request(
    *,
    user_id: str,
    idempotency_key: str,
    duration_seconds: float,
    engine: MobileTranscriptionEngine,
    job_store: JobStore,
    ledger_store: UsageLedgerStore,
) -> tuple[Job, ChargeReservation, dict[str, Any] | None]:
    job, created = _job_for_request(
        job_store=job_store,
        user_id=user_id,
        idempotency_key=idempotency_key,
    )
    try:
        reservation, _reserved_balance = _reserve_request(
            ledger_store=ledger_store,
            job=job,
            engine=engine,
            duration_seconds=duration_seconds,
        )
    except Exception:
        if created:
            job_store.delete_job(job.id)
        raise
    replay = ledger_store.get_finalized_result(reservation)
    if replay is not None:
        replay["balance"] = ledger_store.points_store.get_balance(user_id)
        return job, reservation, replay
    if job.status in {"failed", "cancelled"}:
        raise MobileTranscriptionTerminalError("Use a new idempotency key")
    if not ledger_store.mark_dispatched(reservation):
        raise MobileTranscriptionInProgressError("Transcription is already in progress")
    job_store.update_job_if_status(
        job.id,
        expected_statuses={"pending"},
        status="processing",
        progress=10,
        message="Transcribing audio",
    )
    return job, reservation, None


def _finalize_request(
    *,
    job: Job,
    reservation: ChargeReservation,
    engine: MobileTranscriptionEngine,
    duration_seconds: float,
    cues: list[Cue],
    ledger_store: UsageLedgerStore,
) -> dict[str, Any]:
    credits = pricing.credits_for_video_duration(duration_seconds)
    result = _result_payload(
        job_id=job.id,
        duration_seconds=duration_seconds,
        credits_charged=credits,
        cues=cues,
    )
    balance = ledger_store.finalize(
        reservation,
        credits_charged=credits,
        cost_usd=pricing.stt_provider_cost_usd(
            tier=engine.tier,
            duration_seconds=duration_seconds,
            provider=engine.provider,
            model=engine.model,
        ),
        units={"audio_seconds": duration_seconds, "client": "ios"},
        result=result,
        job_status="completed",
        job_result_data={
            "kind": "mobile_transcription",
            "server_media_retained": False,
            "duration_seconds": duration_seconds,
        },
    )
    return {**result, "balance": balance}


def _execute_mobile_transcription(
    *,
    user_id: str,
    idempotency_key: str,
    audio_bytes: bytes,
    content_type: str,
    duration_seconds: float,
    job_store: JobStore,
    ledger_store: UsageLedgerStore,
) -> dict[str, Any]:
    engine = resolve_mobile_transcription_engine()
    job, reservation, replay = _claim_request(
        user_id=user_id,
        idempotency_key=idempotency_key,
        duration_seconds=duration_seconds,
        engine=engine,
        job_store=job_store,
        ledger_store=ledger_store,
    )
    if replay is not None:
        return replay
    try:
        cues = _dispatch_audio(
            engine=engine,
            audio_bytes=audio_bytes,
            content_type=content_type,
            duration_seconds=duration_seconds,
        )
        return _finalize_request(
            job=job,
            reservation=reservation,
            engine=engine,
            duration_seconds=duration_seconds,
            cues=cues,
            ledger_store=ledger_store,
        )
    except Exception as exc:
        _fail_request(
            ledger_store=ledger_store,
            job_store=job_store,
            reservation=reservation,
            error=exc,
        )
        raise


def process_mobile_transcription(
    *,
    user_id: str,
    idempotency_key: str,
    audio_bytes: bytes,
    content_type: str,
    duration_seconds: float,
    job_store: JobStore,
    ledger_store: UsageLedgerStore,
) -> dict[str, Any]:
    replay = get_mobile_transcription_replay(
        user_id=user_id,
        idempotency_key=idempotency_key,
        ledger_store=ledger_store,
    )
    if replay is not None:
        return replay
    return _execute_mobile_transcription(
        user_id=user_id,
        idempotency_key=idempotency_key,
        audio_bytes=audio_bytes,
        content_type=content_type,
        duration_seconds=duration_seconds,
        job_store=job_store,
        ledger_store=ledger_store,
    )
