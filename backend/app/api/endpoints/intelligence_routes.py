"""Intelligence routes - fact-check and social copy generation."""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException

from ...core.auth import User
from ...core.database import Database
from ...core.errors import sanitize_message
from ...core.ratelimit import limiter_content
from ...schemas.base import FactCheckResponse, SocialCopyResponse
from ...services.jobs import JobStore
from ...services.points import FACT_CHECK_COST, PointsStore
from ..deps import get_current_user, get_db, get_job_store, get_points_store
from .file_utils import data_roots
from .processing_tasks import ChargeContext, refund_charge_best_effort


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/jobs/{job_id}/fact-check", response_model=FactCheckResponse, dependencies=[Depends(limiter_content)])
def fact_check_video(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    points_store: PointsStore = Depends(get_points_store),
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
        charge = ChargeContext(
            user_id=current_user.id,
            cost=FACT_CHECK_COST,
            reason="fact_check",
            meta={"charge_id": uuid.uuid4().hex, "job_id": job_id},
        )
        new_balance = points_store.spend(current_user.id, FACT_CHECK_COST, reason=charge.reason, meta=charge.meta)

        try:
            with db.session() as session:
                result = generate_fact_check(transcript_text, session=session, job_id=job_id)
        except Exception as exc:
            refund_charge_best_effort(points_store, charge, status="failed", error=sanitize_message(str(exc)))
            raise

        return FactCheckResponse(
            items=[
                {
                    "mistake": item.mistake,
                    "correction": item.correction,
                    "explanation": item.explanation,
                    "severity": item.severity,
                    "confidence": item.confidence,
                    "real_life_example": item.real_life_example,
                    "scientific_evidence": item.scientific_evidence,
                }
                for item in result.items
            ],
            truth_score=result.truth_score,
            supported_claims_pct=result.supported_claims_pct,
            claims_checked=result.claims_checked,
            balance=new_balance,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in fact_check_video")
        raise HTTPException(500, f"Failed to fact check: {sanitize_message(str(e))}")


@router.post("/jobs/{job_id}/social-copy", response_model=SocialCopyResponse, dependencies=[Depends(limiter_content)])
def generate_social_copy_video(
    job_id: str,
    current_user: User = Depends(get_current_user),
    job_store: JobStore = Depends(get_job_store),
    points_store: PointsStore = Depends(get_points_store),
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

    from ...services.points import SOCIAL_COPY_COST
    from ...services.subtitles import build_social_copy_llm

    try:
        transcript_text = transcript_path.read_text(encoding="utf-8")
        charge = ChargeContext(
            user_id=current_user.id,
            cost=SOCIAL_COPY_COST,
            reason="social_copy",
            meta={"charge_id": uuid.uuid4().hex, "job_id": job_id},
        )
        new_balance = points_store.spend(current_user.id, SOCIAL_COPY_COST, reason=charge.reason, meta=charge.meta)

        try:
            with db.session() as session:
                social_copy = build_social_copy_llm(transcript_text, session=session, job_id=job_id)

            social_path = artifact_dir / "social.json"
            social_data = {
                "title": social_copy.generic.title,
                "description": social_copy.generic.description,
                "hashtags": social_copy.generic.hashtags,
            }
            social_path.write_text(json.dumps(social_data, ensure_ascii=False, indent=2), encoding="utf-8")

        except Exception as exc:
            refund_charge_best_effort(points_store, charge, status="failed", error=sanitize_message(str(exc)))
            raise

        return SocialCopyResponse(
            social_copy={
                "title": social_copy.generic.title,
                "description": social_copy.generic.description,
                "hashtags": social_copy.generic.hashtags,
            },
            balance=new_balance,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to generate social copy: {sanitize_message(str(e))}")
