"""Artifact persistence utilities."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import List, Optional

from backend.app.core.config import settings
from backend.app.services.subtitle_types import Cue

from . import subtitle_renderer
from .social_intelligence import SocialCopy

logger = logging.getLogger(__name__)


def _prepare_cues_for_delivery(
    cues: List[Cue] | None,
    *,
    max_subtitle_lines: int,
    subtitle_size: int,
) -> List[Cue]:
    if not cues:
        return []

    normalized = subtitle_renderer.normalize_cues_for_ass(cues)
    if max_subtitle_lines <= 0:
        return normalized

    effective_chars = subtitle_renderer.effective_max_chars(
        max_chars=settings.max_sub_line_chars,
        font_size=subtitle_size,
        play_res_x=settings.default_width,
    )
    return subtitle_renderer.normalize_cues_for_ass(
        subtitle_renderer.split_long_cues(
            normalized,
            max_chars=effective_chars,
            max_lines=max_subtitle_lines,
        )
    )


def persist_artifacts(
    artifact_dir: Path,
    audio_path: Path,
    srt_path: Path,
    ass_path: Path,
    transcript_text: str,
    social_copy: Optional[SocialCopy],
    cues: Optional[List[Cue]] = None,
    *,
    max_subtitle_lines: int = 2,
    subtitle_size: int = settings.default_sub_font_size,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)

    for src in (audio_path, srt_path, ass_path):
        try:
            if src.exists():
                shutil.copy2(src, artifact_dir / src.name)
        except FileNotFoundError:
            continue

    (artifact_dir / "transcript.txt").write_text(transcript_text, encoding="utf-8")

    if social_copy:
        social_txt = (
            f"Title: {social_copy.generic.title}\n"
            f"Description: {social_copy.generic.description}\n"
            f"Hashtags: {' '.join(social_copy.generic.hashtags)}\n"
        )
        (artifact_dir / "social_copy.txt").write_text(social_txt, encoding="utf-8")

        social_json = {
            "title": social_copy.generic.title,
            "description": social_copy.generic.description,
            "hashtags": social_copy.generic.hashtags,
        }
        (artifact_dir / "social_copy.json").write_text(
            json.dumps(social_json, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    delivery_cues = _prepare_cues_for_delivery(
        cues,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_size=subtitle_size,
    )

    cues_data = []
    if delivery_cues:
        cues_data = [
            {
                "start": c.start,
                "end": c.end,
                "text": c.text,
                "words": [
                    {"start": w.start, "end": w.end, "text": w.text}
                    for w in c.words
                ] if c.words else None
            }
            for c in delivery_cues
        ]

    (artifact_dir / "transcription.json").write_text(
        json.dumps(cues_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
