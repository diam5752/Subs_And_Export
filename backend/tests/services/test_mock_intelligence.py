from backend.app.services.mock_intelligence import build_mock_fact_check


def test_mock_fact_check_is_explicitly_not_a_real_verification() -> None:
    result = build_mock_fact_check("Η Γη γυρίζει γύρω από τον Ήλιο.")

    assert result.claims_checked == 0
    assert result.truth_score == 0
    assert len(result.items) == 1
    assert "mock" in result.items[0].mistake_el.lower()
    assert result.items[0].confidence == 0
