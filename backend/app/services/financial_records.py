"""Shared policy helpers for durable payment and invoice records."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def financial_account_reference_hash(user_id: str) -> str:
    """Return the immutable v1 database reference for a GSUBS account.

    This is a compatibility identifier, not a credential or integrity digest.
    PostgreSQL trigger logic and already-retained financial records use this
    exact 64-character v1 representation, so a future keyed v2 scheme needs a
    versioned data migration rather than an in-place algorithm substitution.
    """
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("Financial account reference requires a user id")
    prefix = f"gsubs-financial-account:v1:{normalized_user_id}"
    suffix = f"{normalized_user_id}:gsubs-financial-account:v1"
    return (
        hashlib.md5(prefix.encode(), usedforsecurity=False).hexdigest()
        + hashlib.md5(suffix.encode(), usedforsecurity=False).hexdigest()
    )


def financial_retention_deadline(reference_at: int) -> int:
    """Return the end of the fifth full year after the Athens fiscal year."""
    if reference_at < 0:
        raise ValueError("Financial retention reference timestamp cannot be negative")

    athens = ZoneInfo("Europe/Athens")
    reference = datetime.fromtimestamp(reference_at, tz=athens)
    following_sixth_year = datetime(
        reference.year + 6,
        1,
        1,
        tzinfo=athens,
    )
    return int((following_sixth_year - timedelta(seconds=1)).timestamp())
