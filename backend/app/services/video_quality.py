"""Canonical video-quality profiles shared by processing and export paths."""

from __future__ import annotations

VIDEO_QUALITY_CRF: dict[str, int] = {
    "low size": 28,
    "balanced": 23,
    "high quality": 18,
}


def crf_for_video_quality(value: str) -> int:
    """Resolve a validated, human-facing quality name to its x264 CRF."""
    normalized = value.strip().lower()
    try:
        return VIDEO_QUALITY_CRF[normalized]
    except KeyError as exc:
        raise ValueError("Invalid video quality") from exc
