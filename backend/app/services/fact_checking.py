"""Fact Checking Service."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.errors import ProviderDispatchAlreadyClaimedError
from backend.app.schemas.base import FactCheckResponse
from backend.app.services import llm_utils, pricing
from backend.app.services.cost import CostService
from backend.app.services.usage_ledger import ChargeReservation, UsageLedgerStore

logger = logging.getLogger(__name__)

BoundedExtractedClaim = Annotated[
    str,
    Field(strict=True, min_length=1, max_length=2_000),
]


class FactClaimExtraction(BaseModel):
    """Strict provider contract for the cheap claim-extraction stage."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claims: Annotated[
        list[BoundedExtractedClaim],
        Field(max_length=100),
    ]


@dataclass(slots=True)
class FactCheckItem:
    mistake_el: str
    mistake_en: str
    correction_el: str
    correction_en: str
    explanation_el: str
    explanation_en: str
    severity: Literal["minor", "medium", "major"]
    confidence: int
    real_life_example_el: str
    real_life_example_en: str
    scientific_evidence_el: str
    scientific_evidence_en: str


@dataclass(slots=True)
class FactCheckResult:
    truth_score: int
    supported_claims_pct: int
    claims_checked: int
    items: list[FactCheckItem]


def _claims_from_extraction_response(response: Any) -> list[str]:
    """Parse an explicit claim list without treating provider errors as none."""
    content, refusal = llm_utils.extract_chat_completion_text(response)
    if refusal:
        raise ValueError("Fact-check claim extraction was refused")
    if not content:
        raise ValueError("Fact-check claim extraction returned empty content")

    parsed = json.loads(llm_utils.clean_json_response(content))
    return FactClaimExtraction.model_validate(parsed).claims


def _fact_check_result_from_payload(
    payload: dict[str, Any],
) -> FactCheckResult:
    """Validate provider or replay data against the public response schema."""
    validated = FactCheckResponse.model_validate(payload)
    return FactCheckResult(
        truth_score=validated.truth_score,
        supported_claims_pct=validated.supported_claims_pct,
        claims_checked=validated.claims_checked,
        items=[
            FactCheckItem(**item.model_dump())
            for item in validated.items
        ],
    )


def _fact_check_result_payload(
    result: FactCheckResult,
) -> dict[str, Any]:
    """Build a JSON-safe response payload before a customer is charged."""
    validated = FactCheckResponse.model_validate(
        {
            "truth_score": result.truth_score,
            "supported_claims_pct": result.supported_claims_pct,
            "claims_checked": result.claims_checked,
            "items": [asdict(item) for item in result.items],
        }
    )
    return validated.model_dump(exclude={"balance"}, mode="json")


def generate_fact_check(
    transcript_text: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    extraction_model: str | None = None,
    temperature: float = 1,
    session: Session | None = None,
    job_id: str | None = None,
    ledger_store: UsageLedgerStore | None = None,
    charge_reservation: ChargeReservation | None = None,
) -> FactCheckResult:
    """
    Analyze transcript for historical, logical, or factual errors using an LLM.
    """
    if ledger_store and charge_reservation:
        if not ledger_store.mark_dispatched(charge_reservation):
            replay = ledger_store.get_finalized_result(charge_reservation)
            if isinstance(replay, dict):
                return _fact_check_result_from_payload(replay)
            raise ProviderDispatchAlreadyClaimedError(
                "Paid provider dispatch is already in progress",
            )

    if not api_key:
        api_key = llm_utils.resolve_openai_api_key()

    if not api_key:
        raise RuntimeError("OpenAI API key is required for Fact Checking.")

    model_name = model or settings.factcheck_llm_model
    extraction_model_name = extraction_model or settings.extraction_llm_model
    client = llm_utils.load_openai_client(api_key)

    # Cost Optimization: Hybrid Strategy
    # Stage 1: Extraction (Cheap Model) - Get potential claims
    # Stage 2: Verification (Smart Model) - Verify extracted claims

    # 1. Extraction
    extraction_prompt = (
        "Identify potental FACTUAL ERRORS in the text.\n"
        "Return a JSON list of doubtful claims. If none, return empty list.\n"
        "Format: { \"claims\": [\"claim 1\", \"claim 2\"] }\n"
        "Ignore opinions. Focus on objective facts (dates, numbers, events)."
    )

    usage_prompt = 0
    usage_completion = 0
    total_cost = 0.0
    breakdown: dict[str, Any] = {}

    try:
        extract_response = client.chat.completions.create(
            model=extraction_model_name, # Cheap model
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": transcript_text.strip()[:settings.max_llm_input_chars]}
            ],
            temperature=0.3,
            max_completion_tokens=settings.max_llm_output_tokens_extraction,
            response_format={"type": "json_object"},
            timeout=30.0
        )
        if hasattr(extract_response, "usage"):
             prompt_tokens = int(extract_response.usage.prompt_tokens or 0)
             completion_tokens = int(extract_response.usage.completion_tokens or 0)
             usage_prompt += prompt_tokens
             usage_completion += completion_tokens
             breakdown["extraction"] = {
                 "prompt_tokens": prompt_tokens,
                 "completion_tokens": completion_tokens,
                 "total_tokens": prompt_tokens + completion_tokens,
                 "model": extraction_model_name,
             }

             if session:
                 extract_cost = CostService.track_usage(
                     session,
                     extraction_model_name,
                     prompt_tokens,
                     completion_tokens,
                     job_id
                 )
                 total_cost += extract_cost
                 logger.info(f"Fact Check Extraction Token Usage: Input={prompt_tokens}, Output={completion_tokens} | Cost: ${extract_cost:.6f}")
             else:
                 logger.info(f"Fact Check Extraction Token Usage: Input={prompt_tokens}, Output={completion_tokens}")

        claims = _claims_from_extraction_response(extract_response)

        if not claims:
            logger.info("Fact Check: No doubtful claims found by extractor.")
            result = FactCheckResult(
                truth_score=100,
                supported_claims_pct=100,
                claims_checked=0,
                items=[],
            )
            if ledger_store and charge_reservation:
                tier = charge_reservation.tier or settings.default_transcribe_tier
                credits = pricing.credits_for_tokens(
                    tier=tier,
                    prompt_tokens=usage_prompt,
                    completion_tokens=usage_completion,
                    min_credits=charge_reservation.min_credits,
                )
                if total_cost <= 0:
                    total_cost = pricing.llm_cost_estimate_usd(
                        model_name=extraction_model_name,
                        prompt_tokens=usage_prompt,
                        completion_tokens=usage_completion,
                    )
                units = {
                    "prompt_tokens": usage_prompt,
                    "completion_tokens": usage_completion,
                    "total_tokens": usage_prompt + usage_completion,
                    "models": breakdown,
                    "short_circuit": True,
                }
                ledger_store.finalize(
                    charge_reservation,
                    credits_charged=credits,
                    cost_usd=total_cost,
                    units=units,
                    result=_fact_check_result_payload(result),
                )
            return result

    except Exception as e:
        logger.warning(f"Fact Check Extraction failed: {e}. Fallback to full check.")
        if ledger_store and charge_reservation:
            ledger_store.fail(
                charge_reservation,
                status="failed",
                error=f"Fact-check extraction failed: {type(e).__name__}",
            )
            raise ValueError("Fact-check extraction failed after provider dispatch") from e
        # Fallback to original full check if extraction fails
        claims = ["Full Text Analysis"]

    # 2. Verification (Smart Model)
    # We send the specific claims + context to the smart model
    logger.info(f"Fact Check: Verifying {len(claims)} claims with smart model.")

    system_prompt = (
        "### ROLE\n"
        "Expert Fact Checker. Analyze the transcript for factual errors (dates, numbers, history, science).\n\n"
        "### TASK\n"
        "1) Analyze the transcript.\n"
        "2) Output items ONLY for incorrect/misleading claims (Max 3).\n"
        "3) FOR EACH ITEM, provide content in BOTH Greek (EL) and English (EN).\n\n"
        f"CLAIMS TO CHECK: {json.dumps(claims)}\n\n"
        "### FOR EACH ERROR:\n"
        "- MISTAKE_EL / MISTAKE_EN: Quote the error in both languages.\n"
        "- CORRECTION_EL / CORRECTION_EN: Correct facts in both languages.\n"
        "- EXPLANATION_EL / EXPLANATION_EN: Brief reason in both languages.\n"
        "- REAL_LIFE_EXAMPLE_EL / REAL_LIFE_EXAMPLE_EN: Concrete scenario (1 sentence) in both languages.\n"
        "- SCIENTIFIC_EVIDENCE_EL / SCIENTIFIC_EVIDENCE_EN: Citation/proof (1 sentence) in both languages.\n"
        "- SEVERITY: minor/medium/major.\n"
        "- CONFIDENCE: 0-100.\n\n"
        "### SCORES\n"
        "- truth_score (0-100)\n"
        "- supported_claims_pct (0-100)\n"
        "- claims_checked (int)\n\n"
        "### OUTPUT JSON\n"
        "{\n"
        '  "truth_score": 0-100,\n'
        '  "supported_claims_pct": 0-100,\n'
        '  "claims_checked": int,\n'
        '  "items": [\n'
        '    {\n'
        '      "mistake_el": "str",\n'
        '      "mistake_en": "str",\n'
        '      "correction_el": "str",\n'
        '      "correction_en": "str",\n'
        '      "explanation_el": "str",\n'
        '      "explanation_en": "str",\n'
        '      "severity": "str",\n'
        '      "confidence": int,\n'
        '      "real_life_example_el": "str",\n'
        '      "real_life_example_en": "str",\n'
        '      "scientific_evidence_el": "str",\n'
        '      "scientific_evidence_en": "str"\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "If no errors: items=[]\n"
        "JSON ONLY. No markdown."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript_text.strip()[:settings.max_llm_input_chars]},
    ]


    max_retries = 0 if charge_reservation else 2
    last_exc = None

    for attempt in range(max_retries + 1):
        response: Any | None = None
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                timeout=120.0,
                temperature=temperature,
                max_completion_tokens=settings.max_llm_output_tokens_factcheck,
                response_format={"type": "json_object"},
            )

            # Log usage for Detailed Check
            if hasattr(response, "usage"):
                prompt_tokens = int(response.usage.prompt_tokens or 0)
                completion_tokens = int(response.usage.completion_tokens or 0)
                usage_prompt += prompt_tokens
                usage_completion += completion_tokens
                breakdown["verification"] = {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "model": model_name,
                }

                if session:
                    detail_cost = CostService.track_usage(
                        session,
                        model_name,
                        prompt_tokens,
                        completion_tokens,
                        job_id
                    )
                    total_cost += detail_cost
                    logger.info(
                        f"Fact Check Detail Token Usage: Input={prompt_tokens}, Output={completion_tokens} | Cost: ${detail_cost:.6f}"
                    )
                else:
                    logger.info(f"Fact Check Detail Token Usage: Input={prompt_tokens}, Output={completion_tokens}")

            content, refusal = llm_utils.extract_chat_completion_text(response)
            if refusal:
                raise ValueError(f"LLM refusal: {refusal}")
            if not content:
                raise ValueError("Empty response from LLM")

            cleaned_content = llm_utils.clean_json_response(content)
            parsed = json.loads(cleaned_content)
            result = _fact_check_result_from_payload(
                {
                    "truth_score": parsed["truth_score"],
                    "supported_claims_pct": parsed[
                        "supported_claims_pct"
                    ],
                    "claims_checked": parsed["claims_checked"],
                    "items": parsed.get("items", []),
                }
            )

            if ledger_store and charge_reservation:
                tier = charge_reservation.tier or settings.default_transcribe_tier
                credits = pricing.credits_for_tokens(
                    tier=tier,
                    prompt_tokens=usage_prompt,
                    completion_tokens=usage_completion,
                    min_credits=charge_reservation.min_credits,
                )
                if total_cost <= 0:
                    total_cost = pricing.llm_cost_estimate_usd(
                        model_name=model_name,
                        prompt_tokens=usage_prompt,
                        completion_tokens=usage_completion,
                    )
                units = {
                    "prompt_tokens": usage_prompt,
                    "completion_tokens": usage_completion,
                    "total_tokens": usage_prompt + usage_completion,
                    "models": breakdown,
                }
                ledger_store.finalize(
                    charge_reservation,
                    credits_charged=credits,
                    cost_usd=total_cost,
                    units=units,
                    result=_fact_check_result_payload(result),
                )

            return result

        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.exception(f"Fact Check JSON Error (Attempt {attempt+1}/{max_retries+1})")
            llm_utils.chat_completion_debug(response)
            last_exc = exc
            if attempt < max_retries:
                messages.append({"role": "user", "content": "FIX_JSON_ONLY: return ONLY valid JSON matching the schema."})
                continue

    if ledger_store and charge_reservation:
        if usage_prompt + usage_completion > 0:
            if total_cost <= 0:
                total_cost = pricing.llm_cost_estimate_usd(
                    model_name=model_name,
                    prompt_tokens=usage_prompt,
                    completion_tokens=usage_completion,
                )
            units = {
                "prompt_tokens": usage_prompt,
                "completion_tokens": usage_completion,
                "total_tokens": usage_prompt + usage_completion,
                "models": breakdown,
                "failed": True,
            }
            ledger_store.fail(
                charge_reservation,
                status="failed",
                error="Fact-check provider output was unusable",
                actual_cost_usd=total_cost,
                units=units,
            )
        else:
            ledger_store.fail(charge_reservation, status="failed", error=str(last_exc))
    raise ValueError("Failed to generate fact check after retries") from last_exc
