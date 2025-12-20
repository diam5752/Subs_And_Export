import pytest

def test_sso_persistence_vulnerability(tmp_path):
    pytest.skip("Skipping legacy SQLite-based test. Needs refactor to use main Test DB setup.")
