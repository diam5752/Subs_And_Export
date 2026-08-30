"""Artifact persistence utilities."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from backend.app.core.config import settings
from backend.app.services.subtitle_types import Cue

from . import subtitle_renderer
from .social_intelligence import SocialCopy

logger = logging.getLogger(__name__)


def _copy_available_artifacts(artifact_dir: Path, sources: tuple[Path, ...]) -> None:
    for source in sources:
        try:
            if source.exists():
                shutil.copy2(source, artifact_dir / source.name)
        except FileNotFoundError:
            continue


def _persist_social_copy(artifact_dir: Path, social_copy: SocialCopy) -> None:
    generic = social_copy.generic
    social_txt = (
        f"Title (EL): {generic.title_el}\n"
        f"Description (EL): {generic.description_el}\n"
        f"Title (EN): {generic.title_en}\n"
        f"Description (EN): {generic.description_en}\n"
        f"Hashtags: {' '.join(generic.hashtags)}\n"
    )
    (artifact_dir / "social_copy.txt").write_text(social_txt, encoding="utf-8")
    social_json = {
        "title_el": generic.title_el,
        "description_el": generic.description_el,
        "title_en": generic.title_en,
        "description_en": generic.description_en,
        "hashtags": generic.hashtags,
    }
    (artifact_dir / "social_copy.json").write_text(
        json.dumps(social_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _serialize_cues(cues: list[Cue]) -> list[dict[str, Any]]:
    return [
        {
            "start": cue.start,
            "end": cue.end,
            "text": cue.text,
            "words": (
                [{"start": word.start, "end": word.end, "text": word.text} for word in cue.words] if cue.words else None
            ),
        }
        for cue in cues
    ]


def _prepare_cues_for_delivery(
    cues: list[Cue] | None,
    *,
    max_subtitle_lines: int,
    subtitle_size: int,
) -> list[Cue]:
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
    social_copy: SocialCopy | None,
    cues: list[Cue] | None = None,
    *,
    max_subtitle_lines: int = 2,
    subtitle_size: int = settings.default_sub_font_size,
) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    _copy_available_artifacts(artifact_dir, (audio_path, srt_path, ass_path))

    (artifact_dir / "transcript.txt").write_text(transcript_text, encoding="utf-8")

    if social_copy:
        _persist_social_copy(artifact_dir, social_copy)

    delivery_cues = _prepare_cues_for_delivery(
        cues,
        max_subtitle_lines=max_subtitle_lines,
        subtitle_size=subtitle_size,
    )

    cues_data = _serialize_cues(delivery_cues)

    (artifact_dir / "transcription.json").write_text(
        json.dumps(cues_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
