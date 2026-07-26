from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.app.services.financial_records import (
    financial_account_reference_hash,
    financial_retention_deadline,
)


def test_financial_account_reference_matches_the_database_trigger_contract() -> None:
    assert financial_account_reference_hash("user-123") == (
        "70e399e12477cce17f78217d84c45fd9283cbf4ea1c06210d86a5d211159b013"
    )


def test_financial_account_reference_rejects_empty_identity() -> None:
    with pytest.raises(ValueError, match="requires a user id"):
        financial_account_reference_hash(" ")


def test_financial_retention_ends_after_five_full_fiscal_years() -> None:
    athens = ZoneInfo("Europe/Athens")
    paid_at = int(datetime(2026, 7, 26, 12, 30, tzinfo=athens).timestamp())

    # REGRESSION: adding 5 * 365 days can expire records before the end of the
    # fifth full year following the relevant Greek fiscal year.
    assert financial_retention_deadline(paid_at) == int(datetime(2031, 12, 31, 23, 59, 59, tzinfo=athens).timestamp())


def test_financial_retention_uses_the_athens_fiscal_year_boundary() -> None:
    athens = ZoneInfo("Europe/Athens")
    just_after_new_year_in_athens = int(datetime(2027, 1, 1, 0, 0, 1, tzinfo=athens).timestamp())

    assert financial_retention_deadline(just_after_new_year_in_athens) == int(
        datetime(2032, 12, 31, 23, 59, 59, tzinfo=athens).timestamp()
    )


def test_financial_retention_rejects_negative_timestamp() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        financial_retention_deadline(-1)
