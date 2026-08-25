from __future__ import annotations

import pytest

from backend.app.services.video_quality import crf_for_video_quality


@pytest.mark.parametrize(
    ("quality", "expected_crf"),
    [
        (" low size ", 28),
        ("BALANCED", 23),
        ("high quality", 18),
    ],
)
def test_video_quality_profiles_are_canonical(
    quality: str,
    expected_crf: int,
) -> None:
    assert crf_for_video_quality(quality) == expected_crf


def test_unknown_video_quality_fails_closed() -> None:
    with pytest.raises(ValueError, match="Invalid video quality"):
        crf_for_video_quality("lossless-ish")
