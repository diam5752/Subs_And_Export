"""Honest deterministic intelligence previews for zero-cost mock mode."""

from __future__ import annotations

from backend.app.services.fact_checking import FactCheckResult


def build_mock_fact_check(_transcript_text: str) -> FactCheckResult:
    """Return an empty, unverified result instead of inventing a fact-check item."""
    return FactCheckResult(
        truth_score=0,
        supported_claims_pct=0,
        claims_checked=0,
        items=[],
    )
