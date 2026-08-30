"""Stable Stripe webhook fingerprints across delivery retries."""

from __future__ import annotations

import hashlib
import json
import re
import secrets

from backend.app.services.billing_types import BillingValidationError

_STRIPE_PENDING_WEBHOOKS_TOKEN_RE = re.compile(
    rb'("pending_webhooks"\s*:\s*)([0-9]+)',
)
_LEGACY_STRIPE_PENDING_WEBHOOKS_MAX = 1024


def _valid_pending_webhook_count(value: object) -> bool:
    return value is None or isinstance(value, int) and not isinstance(value, bool) and value >= 0


def stripe_webhook_payload_fingerprint(payload: bytes) -> str:
    """Hash immutable event data while ignoring Stripe's delivery counter."""
    try:
        envelope = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BillingValidationError("Invalid Stripe webhook event") from exc
    if not isinstance(envelope, dict):
        raise BillingValidationError("Invalid Stripe webhook event")
    pending_webhooks = envelope.pop("pending_webhooks", None)
    if not _valid_pending_webhook_count(pending_webhooks):
        raise BillingValidationError("Invalid Stripe pending webhook count")
    try:
        canonical_payload = json.dumps(
            envelope,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    except (TypeError, ValueError) as exc:
        raise BillingValidationError("Invalid Stripe webhook event") from exc
    return hashlib.sha256(canonical_payload).hexdigest()


def legacy_webhook_hash_matches_pending_count(
    payload: bytes,
    expected_hash: str,
) -> bool:
    """Accept a legacy raw hash only if solely the delivery counter changed."""
    if secrets.compare_digest(hashlib.sha256(payload).hexdigest(), expected_hash):
        return True
    try:
        envelope = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    pending_webhooks = envelope.get("pending_webhooks") if isinstance(envelope, dict) else None
    if not _valid_pending_webhook_count(pending_webhooks):
        return False
    matches = list(_STRIPE_PENDING_WEBHOOKS_TOKEN_RE.finditer(payload))
    if len(matches) != 1 or int(matches[0].group(2)) != pending_webhooks:
        return False
    match = matches[0]
    prefix = payload[: match.start(2)]
    suffix = payload[match.end(2) :]
    return any(
        secrets.compare_digest(
            hashlib.sha256(prefix + str(candidate).encode() + suffix).hexdigest(),
            expected_hash,
        )
        for candidate in range(_LEGACY_STRIPE_PENDING_WEBHOOKS_MAX + 1)
    )
