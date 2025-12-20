"""Intelligence routes - fact-check and social copy generation."""

from __future__ import annotations

import json
import logging
from fastapi import APIRouter, Depends, HTTPException

from ...core import config
from ...core.auth import User
from ...core.database import Database
from ...core.errors import sanitize_error
from ...core.ratelimit import limiter_content
from ...schemas.base import FactCheckResponse, SocialCopyResponse
from ...services import pricing
from ...services.charge_plans import reserve_llm_charge
from ...services.jobs import JobStore
from ...services.usage_ledger import UsageLedgerStore
from ..deps import get_current_user, get_db, get_job_store, get_usage_ledger_store
from .file_utils import data_roots


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/jobs/{job_id}/fact-check", response_model=FactCheckResponse, dependencies=[Depends(limiter_content)])
def fact_check_video(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
    db: Database = Depends(get_db),
):
    """Analyze transcript for historical or factual correctness."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to fact check")

    _, _, artifacts_root = data_roots()
    artifact_dir = artifacts_root / job_id
    transcript_path = artifact_dir / "transcript.txt"

    if not transcript_path.exists():
        raise HTTPException(404, "Transcript not found for this job")

    from ...services.subtitles import generate_fact_check

    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
        tier = pricing.resolve_tier_from_model((job.result_data or {}).get("model_size"))
        llm_models = pricing.resolve_llm_models(tier)
        reservation, _ = reserve_llm_charge(
            ledger_store=ledger_store,
            user_id=current_user.id,
            job_id=job_id,
            tier=tier,
            action="fact_check",
            model=llm_models.fact_check,
            max_prompt_chars=config.MAX_LLM_INPUT_CHARS,
            max_completion_tokens=config.MAX_LLM_OUTPUT_TOKENS_FACTCHECK,
            min_credits=config.CREDITS_MIN_FACT_CHECK[tier],
        )

        try:
            with db.session() as session:
                result = generate_fact_check(
                    transcript_text,
                    session=session,
                    job_id=job_id,
                    model=llm_models.fact_check,
                    extraction_model=llm_models.extraction,
                    ledger_store=ledger_store,
                    charge_reservation=reservation,
                )
        except Exception as exc:
            ledger_store.refund_if_reserved(reservation, status="failed", error=sanitize_error(exc))
            raise

        return FactCheckResponse(
            items=[
                {
                    "mistake_el": item.mistake_el,
                    "mistake_en": item.mistake_en,
                    "correction_el": item.correction_el,
                    "correction_en": item.correction_en,
                    "explanation_el": item.explanation_el,
                    "explanation_en": item.explanation_en,
                    "severity": item.severity,
                    "confidence": item.confidence,
                    "real_life_example_el": item.real_life_example_el,
                    "real_life_example_en": item.real_life_example_en,
                    "scientific_evidence_el": item.scientific_evidence_el,
                    "scientific_evidence_en": item.scientific_evidence_en,
                }
                for item in result.items
            ],
            truth_score=result.truth_score,
            supported_claims_pct=result.supported_claims_pct,
            claims_checked=result.claims_checked,
            balance=ledger_store.points_store.get_balance(current_user.id),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in fact_check_video")
        raise HTTPException(500, f"Failed to fact check: {sanitize_error(e)}")


@router.post("/jobs/{job_id}/social-copy", response_model=SocialCopyResponse, dependencies=[Depends(limiter_content)])
def generate_social_copy_video(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    ledger_store: UsageLedgerStore = Depends(get_usage_ledger_store),
    db: Database = Depends(get_db),
):
    """Generate viral social media copy for a video."""
    job = job_store.get_job(job_id)
    if not job or job.user_id != current_user.id:
        raise HTTPException(404, "Job not found")

    if job.status != "completed":
        raise HTTPException(400, "Job must be completed to generate social copy")

    _, _, artifacts_root = data_roots()
    artifact_dir = artifacts_root / job_id
    transcript_path = artifact_dir / "transcript.txt"

    if not transcript_path.exists():
        raise HTTPException(404, "Transcript not found for this job")

    from ...services.subtitles import build_social_copy_llm

    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
        tier = pricing.resolve_tier_from_model((job.result_data or {}).get("model_size"))
        llm_models = pricing.resolve_llm_models(tier)
        reservation, _ = reserve_llm_charge(
            ledger_store=ledger_store,
            user_id=current_user.id,
            job_id=job_id,
            tier=tier,
            action="social_copy",
            model=llm_models.social,
            max_prompt_chars=config.MAX_LLM_INPUT_CHARS,
            max_completion_tokens=config.MAX_LLM_OUTPUT_TOKENS_SOCIAL,
            min_credits=config.CREDITS_MIN_SOCIAL_COPY[tier],
        )

        try:
            with db.session() as session:
                social_copy = build_social_copy_llm(
                    transcript_text,
                    session=session,
                    job_id=job_id,
                    model=llm_models.social,
                    ledger_store=ledger_store,
                    charge_reservation=reservation,
                )

            social_path = artifact_dir / "social.json"
            social_data = {
                "title_el": social_copy.generic.title_el,
                "title_en": social_copy.generic.title_en,
                "description_el": social_copy.generic.description_el,
                "description_en": social_copy.generic.description_en,
                "hashtags": social_copy.generic.hashtags,
            }
            social_path.write_text(json.dumps(social_data, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as exc:
            ledger_store.refund_if_reserved(reservation, status="failed", error=sanitize_error(exc))
            raise

        return SocialCopyResponse(
            social_copy={
                "title_el": social_copy.generic.title_el,
                "title_en": social_copy.generic.title_en,
                "description_el": social_copy.generic.description_el,
                "description_en": social_copy.generic.description_en,
                "hashtags": social_copy.generic.hashtags,
            },
            balance=ledger_store.points_store.get_balance(current_user.id),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate social copy: {sanitize_error(e)}")
