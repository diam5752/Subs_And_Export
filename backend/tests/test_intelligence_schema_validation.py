from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.schemas.base import (
    FactCheckItemSchema,
    FactCheckResponse,
    SocialCopySchema,
)


def _fact_item_payload() -> dict[str, object]:
    return {
        "mistake_el": "Λάθος",
        "mistake_en": "Wrong",
        "correction_el": "Σωστό",
        "correction_en": "Correct",
        "explanation_el": "Εξήγηση",
        "explanation_en": "Explanation",
        "severity": "medium",
        "confidence": 80,
        "real_life_example_el": "Παράδειγμα",
        "real_life_example_en": "Example",
        "scientific_evidence_el": "Επιστημονικό τεκμήριο",
        "scientific_evidence_en": "Scientific evidence",
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("confidence", -1),
        ("confidence", 101),
        ("confidence", True),
        ("severity", "critical"),
        ("mistake_el", "   "),
        ("scientific_evidence_en", "x" * 2_001),
    ],
)
def test_fact_check_item_rejects_semantically_invalid_values(
    field: str,
    value: object,
) -> None:
    payload = _fact_item_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        FactCheckItemSchema.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("truth_score", -1),
        ("truth_score", 101),
        ("supported_claims_pct", 101),
        ("claims_checked", -1),
        ("claims_checked", 101),
    ],
)
def test_fact_check_response_rejects_invalid_scores_and_claim_counts(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "items": [],
        "truth_score": 80,
        "supported_claims_pct": 75,
        "claims_checked": 3,
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        FactCheckResponse.model_validate(payload)


def test_fact_check_response_accepts_no_more_than_three_items() -> None:
    with pytest.raises(ValidationError):
        FactCheckResponse.model_validate(
            {
                "items": [_fact_item_payload() for _ in range(4)],
                "truth_score": 80,
                "supported_claims_pct": 75,
                "claims_checked": 4,
            }
        )


def test_fact_check_response_rejects_more_items_than_checked_claims() -> None:
    with pytest.raises(
        ValidationError,
        match="claims_checked must cover every reported item",
    ):
        FactCheckResponse.model_validate(
            {
                "items": [_fact_item_payload()],
                "truth_score": 80,
                "supported_claims_pct": 75,
                "claims_checked": 0,
            }
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title_el", "   "),
        ("title_en", "x" * 161),
        ("description_el", ""),
        ("description_en", "x" * 2_001),
        ("hashtags", []),
        ("hashtags", [f"#tag{index}" for index in range(15)]),
        ("hashtags", ["missing-prefix"]),
        ("hashtags", ["#two words"]),
        ("hashtags", ["#Same", "#same"]),
    ],
)
def test_social_copy_rejects_invalid_bounded_content(
    field: str,
    value: object,
) -> None:
    payload: dict[str, object] = {
        "title_el": "Τίτλος",
        "title_en": "Title",
        "description_el": "Περιγραφή",
        "description_en": "Description",
        "hashtags": ["#gsubs"],
    }
    payload[field] = value

    with pytest.raises(ValidationError):
        SocialCopySchema.model_validate(payload)


def test_intelligence_schemas_accept_boundary_values() -> None:
    item = _fact_item_payload()
    item["confidence"] = 100
    fact = FactCheckResponse.model_validate(
        {
            "items": [item, item, item],
            "truth_score": 0,
            "supported_claims_pct": 100,
            "claims_checked": 100,
        }
    )
    social = SocialCopySchema.model_validate(
        {
            "title_el": "Τίτλος",
            "title_en": "Title",
            "description_el": "Περιγραφή",
            "description_en": "Description",
            "hashtags": [f"#tag{index}" for index in range(14)],
        }
    )

    assert len(fact.items) == 3
    assert len(social.hashtags) == 14
