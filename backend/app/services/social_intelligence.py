"""Deterministic social-copy helpers for the local CLI workflow."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class SocialContent:
    title_el: str
    title_en: str
    description_el: str
    description_en: str
    hashtags: list[str]


@dataclass(frozen=True, slots=True)
class SocialCopy:
    generic: SocialContent


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


def _extract_keywords(text: str, limit: int = 5) -> list[str]:
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


def _build_hashtags(keywords: Sequence[str], extra: Sequence[str]) -> list[str]:
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
