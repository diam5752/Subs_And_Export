"""Regression checks for the public and operational GSUBS privacy baseline."""

import json
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_public_legal_copy_contains_verified_identity_and_no_false_cookie_choice() -> None:
    frontend = REPOSITORY_ROOT / "frontend"
    greek = json.loads((frontend / "src/i18n/el.json").read_text(encoding="utf-8"))
    english = json.loads((frontend / "src/i18n/en.json").read_text(encoding="utf-8"))

    for messages in (greek, english):
        assert "802523620" in messages["termsSellerBody"]
        assert "EL802523620" in messages["termsSellerBody"]
        assert "177974203000" in messages["termsSellerBody"]
        assert "ELGEMI.177974203000" in messages["termsSellerBody"]
        assert "cookie consent" not in messages["privacyCookiesBody"].casefold()
        assert "analytics" in messages["privacyCookiesBody"].casefold()
        assert "hetzner" in messages["privacyProvidersBody"].casefold()
        assert "google workspace" in messages["privacyProvidersBody"].casefold()

    layout = (frontend / "src/app/layout.tsx").read_text(encoding="utf-8")
    assert "CookieConsent" not in layout
    assert not (frontend / "src/components/CookieConsent.tsx").exists()


def test_operational_compliance_pack_keeps_open_evidence_explicit() -> None:
    compliance_root = REPOSITORY_ROOT / "docs/compliance"
    required = {
        "README.md",
        "ropa.md",
        "processors-and-transfers.md",
        "data-subject-rights-runbook.md",
        "personal-data-breach-runbook.md",
        "legitimate-interests-assessment.md",
        "dpia-dpo-and-minors-screening.md",
    }
    assert required <= {path.name for path in compliance_root.iterdir() if path.is_file()}

    processors = (compliance_root / "processors-and-transfers.md").read_text(
        encoding="utf-8",
    )
    breach = (compliance_root / "personal-data-breach-runbook.md").read_text(
        encoding="utf-8",
    )
    rights = (compliance_root / "data-subject-rights-runbook.md").read_text(
        encoding="utf-8",
    )
    assert "**OPEN:**" in processors
    assert "Zero Retention Mode" in processors
    assert "within 72 hours" in breach
    assert "one month" in rights
