"""Honest deterministic intelligence previews for zero-cost mock mode."""

from __future__ import annotations

from backend.app.services.fact_checking import FactCheckItem, FactCheckResult


def build_mock_fact_check(transcript_text: str) -> FactCheckResult:
    """Return a clearly labelled preview instead of pretending to verify facts."""
    excerpt = " ".join(transcript_text.split())[:120]
    item = FactCheckItem(
        mistake_el="Προεπισκόπηση mock — δεν έγινε πραγματικός έλεγχος ισχυρισμών.",
        mistake_en="Mock preview — no claims were actually verified.",
        correction_el="Σύνδεσε υπηρεσία επαλήθευσης μόνο όταν αποφασίσεις να ενεργοποιήσεις live mode.",
        correction_en="Connect a verification service only when you choose to enable live mode.",
        explanation_el=f"Το demo διάβασε το transcript τοπικά: {excerpt or 'χωρίς κείμενο'}",
        explanation_en="The demo read the transcript locally and made no network request.",
        severity="minor",
        confidence=0,
        real_life_example_el="Η κάρτα αυτή υπάρχει για να ελεγχθεί το UI χωρίς χρέωση.",
        real_life_example_en="This card exists to test the UI without any charge.",
        scientific_evidence_el="Δεν χρησιμοποιήθηκε εξωτερική πηγή σε mock mode.",
        scientific_evidence_en="No external source was used in mock mode.",
    )
    return FactCheckResult(
        truth_score=0,
        supported_claims_pct=0,
        claims_checked=0,
        items=[item],
    )
