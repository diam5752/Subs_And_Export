"""Social Intelligence Service for generating titles, descriptions, and metadata."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, List, Sequence

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.services import llm_utils
from backend.app.services.cost import CostService
from backend.app.services import pricing
from backend.app.services.usage_ledger import ChargeReservation, UsageLedgerStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SocialContent:
    title_el: str
    title_en: str
    description_el: str
    description_en: str
    hashtags: List[str]


@dataclass(frozen=True)
class SocialCopy:
    generic: SocialContent


@dataclass
class ViralMetadata:
    hooks: List[str]
    caption_hook: str
    caption_body: str
    cta: str
    hashtags: List[str]


_STOPWORDS = {
    "και",
    "για",
    "στο",
    "στη",
    "the",
    "this",
    "that",
    "and",
    "for",
    "with",
    "your",
    "from",
    "about",
    "στον",
    "μια",
    "είναι",
    "που",
    "τους",
}


def _extract_keywords(text: str, limit: int = 5) -> List[str]:
    tokens = re.findall(r"[\wάέίόύήώϊϋΐΰ]+", text.lower())
    ranked: dict[str, tuple[int, int]] = {}
    for idx, tok in enumerate(tokens):
        if tok in _STOPWORDS or len(tok) <= 3:
            continue
        count, first_idx = ranked.get(tok, (0, idx))
        ranked[tok] = (count + 1, first_idx)
    ordered = sorted(ranked.items(), key=lambda item: (-item[1][0], item[1][1]))
    return [kw for kw, _ in ordered[:limit]]


def _summarize_text(text: str, max_words: int = 45) -> str:
    words = text.split()
    summary_words = words[:max_words]
    return " ".join(summary_words).strip()


def _compose_title(keywords: Sequence[str]) -> str:
    if not keywords:
        return "Greek Highlights"
    if len(keywords) == 1:
        return f"{keywords[0].title()} Highlights"
    return f"{keywords[0].title()} & {keywords[1].title()} Moments"


def _build_hashtags(keywords: Sequence[str], extra: Sequence[str]) -> List[str]:
    raw_tags = [f"#{kw.replace(' ', '')}" for kw in keywords]
    raw_tags.extend(f"#{tag}" if not tag.startswith("#") else tag for tag in extra)
    deduped = list(dict.fromkeys(raw_tags))
    return deduped[:10]


def _platform_copy(
    base_title_el: str,
    base_title_en: str,
    summary_el: str,
    summary_en: str,
    hashtags: Sequence[str],
    *,
    extra_tags: Sequence[str],
) -> SocialContent:
    all_tags_raw = [*hashtags, *extra_tags]
    # Normalize to ensure all have # prefix
    all_tags = list(dict.fromkeys(
        [f"#{tag.lstrip('#')}" for tag in all_tags_raw]
    ))
    formatted_tags = " ".join(all_tags)
    desc_el = f"{summary_el}\n{formatted_tags}".strip()
    desc_en = f"{summary_en}\n{formatted_tags}".strip()
    return SocialContent(
        title_el=base_title_el.strip(), 
        title_en=base_title_en.strip(),
        description_el=desc_el, 
        description_en=desc_en,
        hashtags=all_tags
    )


def build_social_copy(transcript_text: str) -> SocialCopy:
    """
    Create generic social copy from transcript text.

    The output stays deterministic and avoids external API calls so it can be
    used in CI environments.
    """

    clean_text = transcript_text.strip()
    keywords = _extract_keywords(clean_text)
    base_title = _compose_title(keywords)
    summary = _summarize_text(clean_text)
    shared_tags = _build_hashtags(keywords, ["greek", "subtitles", "verticalvideo"])

    generic_copy = _platform_copy(
        base_title,
        base_title, # Fallback title for EN
        summary,
        summary, # Fallback summary for EN
        shared_tags,
        extra_tags=["trending", "viral", "fyp"],
    )

    return SocialCopy(generic=generic_copy)


def build_social_copy_llm(
    transcript_text: str,
    *,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 1,
    session: Session | None = None,
    job_id: str | None = None,
    ledger_store: UsageLedgerStore | None = None,
    charge_reservation: ChargeReservation | None = None,
) -> SocialCopy:
    """
    Generate professional social copy using OpenAI's GPT models.

    Securely handles API key from multiple sources (in priority order):
    1. Explicit api_key parameter
    2. OPENAI_API_KEY environment variable

    Args:
        transcript_text: Video transcript to generate social copy from
        api_key: Optional explicit API key (overrides env)
        model: Model name (defaults to gpt-4o-mini)
        temperature: Sampling temperature (0.0-2.0, default 0.6)

    Returns:
        SocialCopy with platform-specific titles and descriptions

    Raises:
        RuntimeError: If no API key is found in any source
        ValueError: If LLM response is invalid
    """
    # Try to get API key from multiple sources (env, secrets.toml)
    if not api_key:
        api_key = llm_utils.resolve_openai_api_key()

    # Validate API key is present
    if not api_key:
        raise RuntimeError(
            "OpenAI API key is required for AI enrichment. Please set it via:\n"
            "  1. Environment variable: export OPENAI_API_KEY='your-key'\n"
            "  2. Secrets file: config/secrets.toml\n"
            "  3. Pass explicitly via api_key parameter"
        )

    model_name = model or settings.social_llm_model
    client = llm_utils.load_openai_client(api_key)

    system_prompt = (
        "You are a viral bilingual (Greek/English) copywriter. Your job is to make viewers STOP scrolling.\n"
        "Input: a transcript from a short video.\n\n"
        "Return ONLY valid JSON matching EXACTLY this schema:\n"
        '{\n'
        '  "title_el": "...", "title_en": "...",\n'
        '  "description_el": "...", "description_en": "...",\n'
        '  "hashtags": ["#tag1", "#tag2"]\n'
        '}\n\n'
        "### TITLES (35–80 chars)\n"
        "- Hook the viewer IMMEDIATELY. CURIOUS/BOLD labels.\n"
        "- TITLE_EL: Viral Greek title.\n"
        "- TITLE_EN: Viral English version of the SAME hook.\n\n"
        "### DESCRIPTIONS (100–400 chars)\n"
        "- Punchy hooks, emotions/controversy.\n"
        "- End with a CTA (e.g., 'Συμφωνείς;' / 'Agree?').\n"
        "- DESCRIPTION_EL: Greek description.\n"
        "- DESCRIPTION_EN: English description.\n"
        "- Use 1-2 emojis strategically.\n\n"
        "### HASHTAGS (8–14 items)\n"
        "- Mix of EL and EN tags.\n\n"
        "### RULES\n"
        "- Stay true to content.\n"
        "- Sound like a creator.\n"
        "- JSON ONLY."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": transcript_text.strip()[:settings.max_llm_input_chars]},
    ]

    # Retry mechanism
    max_retries = 3
    last_exc = None

    usage_prompt = 0
    usage_completion = 0
    total_cost = 0.0

    for attempt in range(max_retries + 1):
        response: Any | None = None
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=settings.max_llm_output_tokens_social,
                response_format={"type": "json_object"},
                timeout=60.0,
            )
            
            # Log usage for Social Copy
            if hasattr(response, "usage"):
                prompt_tokens = int(response.usage.prompt_tokens or 0)
                completion_tokens = int(response.usage.completion_tokens or 0)
                usage_prompt += prompt_tokens
                usage_completion += completion_tokens

                if session:
                    cost = CostService.track_usage(
                        session, 
                        model_name, 
                        prompt_tokens, 
                        completion_tokens, 
                        job_id
                    )
                    total_cost += cost
                    logger.info(
                        f"Social Copy Token Usage: Input={prompt_tokens}, Output={completion_tokens}, Total={response.usage.total_tokens} | Cost: ${cost:.6f}"
                    )
                else:
                    # Fallback logging if no session
                    logger.warning("No DB session provided for build_social_copy_llm. Cost not tracked in DB.")
                    logger.info(f"Social Copy Token Usage: Input={prompt_tokens}, Output={completion_tokens}")
            
            content, refusal = llm_utils.extract_chat_completion_text(response)
            if refusal:
                raise ValueError(f"LLM refusal: {refusal}")
            if not content:
                raise ValueError("Empty response from LLM")

            cleaned_content = llm_utils.clean_json_response(content)
            parsed = json.loads(cleaned_content)

            if ledger_store and charge_reservation:
                tier = charge_reservation.tier or settings.default_transcribe_tier
                credits = pricing.credits_for_tokens(
                    tier=tier,
                    prompt_tokens=usage_prompt,
                    completion_tokens=usage_completion,
                    min_credits=charge_reservation.min_credits,
                )
                if session and total_cost <= 0:
                    total_cost = pricing.llm_cost_usd(
                        session,
                        model_name=model_name,
                        prompt_tokens=usage_prompt,
                        completion_tokens=usage_completion,
                    )
                units = {
                    "prompt_tokens": usage_prompt,
                    "completion_tokens": usage_completion,
                    "total_tokens": usage_prompt + usage_completion,
                    "model": model_name,
                }
                ledger_store.finalize(
                    charge_reservation,
                    credits_charged=credits,
                    cost_usd=total_cost,
                    units=units,
                )

            return SocialCopy(
                generic=SocialContent(
                    title_el=parsed["title_el"],
                    title_en=parsed["title_en"],
                    description_el=parsed["description_el"],
                    description_en=parsed["description_en"],
                    hashtags=parsed.get("hashtags", []),
                )
            )
        except Exception as exc:
            logger.exception(f"Social Copy JSON Error (Attempt {attempt+1}/{max_retries+1})")
            llm_utils.chat_completion_debug(response)

            last_exc = exc
            if attempt < max_retries:
                # Retry prompt with stronger instruction
                messages.append({"role": "user", "content": "ERROR: The last response was not valid JSON. Return ONLY the JSON object. No other text."})
                continue

    # raise ValueError("Failed to generate valid social copy after retries") from last_exc
    logger.error(f"Failed to generate valid social copy after retries: {last_exc}")
    logger.warning("Falling back to deterministic social copy generation.")
    if ledger_store and charge_reservation:
        if usage_prompt + usage_completion > 0:
            tier = charge_reservation.tier or settings.default_transcribe_tier
            credits = pricing.credits_for_tokens(
                tier=tier,
                prompt_tokens=usage_prompt,
                completion_tokens=usage_completion,
                min_credits=charge_reservation.min_credits,
            )
            if session and total_cost <= 0:
                total_cost = pricing.llm_cost_usd(
                    session,
                    model_name=model_name,
                    prompt_tokens=usage_prompt,
                    completion_tokens=usage_completion,
                )
            units = {
                "prompt_tokens": usage_prompt,
                "completion_tokens": usage_completion,
                "total_tokens": usage_prompt + usage_completion,
                "model": model_name,
                "fallback": True,
            }
            ledger_store.finalize(
                charge_reservation,
                credits_charged=credits,
                cost_usd=total_cost,
                units=units,
                status="failed",
            )
        else:
            ledger_store.fail(charge_reservation, status="failed", error=str(last_exc))
    return build_social_copy(transcript_text)
