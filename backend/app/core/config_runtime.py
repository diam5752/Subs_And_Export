"""Runtime configuration checks shared by the application settings model."""

from __future__ import annotations

import re
from email.utils import parseaddr
from typing import Any, cast

DEV_DOWNLOAD_GRANT_SECRET = "gsubs-dev-only-download-grant-secret-not-for-production"


class SettingsRuntimeChecks:
    """Behavior-only mixin; Pydantic fields remain declared in Settings."""

    def assert_download_grant_configuration(self: Any) -> None:
        """Require a dedicated high-entropy signing key outside development."""
        if self.is_dev:
            return
        secret = self.download_grant_secret.get_secret_value() if self.download_grant_secret is not None else ""
        if len(secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "Production cross-browser downloads require a dedicated "
                "GSP_DOWNLOAD_GRANT_SECRET of at least 32 bytes.",
            )

    def download_grant_signing_secret(self: Any) -> str:
        """Return the configured key, with an explicitly dev-only fallback."""
        if self.download_grant_secret is not None:
            configured = self.download_grant_secret.get_secret_value()
            if len(configured.encode("utf-8")) >= 32:
                return cast(str, configured)
        if self.is_dev:
            return DEV_DOWNLOAD_GRANT_SECRET
        self.assert_download_grant_configuration()
        raise RuntimeError("Download grant signing secret is unavailable")

    def assert_paid_credits_configuration(self: Any) -> None:
        """Fail closed before a runtime can create real Checkout Sessions."""
        if not self.paid_credits_enabled:
            return
        missing_launch_gates = [
            gate
            for gate, ready in (
                ("consumer policy approval", self.consumer_policy_approved),
                (
                    "durable contract-confirmation channel",
                    self.durable_confirmation_channel_ready,
                ),
                ("approved manual adjustment workflow", self.adjustment_workflow_ready),
            )
            if not ready
        ]
        if missing_launch_gates:
            raise RuntimeError(
                "Paid credit Checkout remains fail closed until these independent "
                f"launch gates are ready: {', '.join(missing_launch_gates)}."
            )
        if self.stripe_automatic_tax_enabled:
            raise RuntimeError(
                "Stripe Automatic Tax is owner-gated until active tax registrations "
                "and the tax-inclusive catalog are reviewed."
            )

        if not self.assert_stripe_stage_configuration():
            raise RuntimeError(
                "A Stripe restricted key, webhook signing secret and all three Stripe credit Price IDs are required."
            )

    def assert_feedback_api_configuration(self: Any) -> None:
        """Fail closed when the public inbox lacks a stable pseudonym key."""
        if not self.feedback_enabled:
            return
        hash_secret = (
            self.feedback_hash_secret.get_secret_value().strip() if self.feedback_hash_secret is not None else ""
        )
        if len(hash_secret) < 32:
            raise RuntimeError(
                "Enabled product feedback requires a dedicated secret of at least 32 characters.",
            )

    def assert_feedback_worker_configuration(self: Any) -> None:
        """Require an encrypted, complete SMTP bundle before delivery starts."""
        if not self.feedback_enabled:
            raise RuntimeError("The product feedback worker cannot run while feedback is disabled.")

        password = (
            self.feedback_smtp_password.get_secret_value().strip() if self.feedback_smtp_password is not None else ""
        )
        missing = [
            label
            for label, value in (
                ("notification recipient", self.feedback_notification_to),
                ("mail sender", self.feedback_mail_from),
                ("SMTP host", self.feedback_smtp_host),
                ("SMTP username", self.feedback_smtp_username),
                ("SMTP password", password),
            )
            if not value.strip()
        ]
        if missing:
            raise RuntimeError(
                "Feedback notification configuration is incomplete: " + ", ".join(missing) + ".",
            )
        if not self.feedback_smtp_starttls:
            raise RuntimeError("Feedback SMTP delivery requires STARTTLS.")
        if not self._is_valid_mailbox(self.feedback_notification_to, allow_display_name=False):
            raise RuntimeError("Feedback notification recipient is not a valid email address.")
        if not self._is_valid_mailbox(self.feedback_mail_from, allow_display_name=True):
            raise RuntimeError("Feedback mail sender is not a valid email address.")
        if re.search(r"[\s\x00-\x1f\x7f]", self.feedback_smtp_host):
            raise RuntimeError("Feedback SMTP host is invalid.")

    @staticmethod
    def _is_valid_mailbox(value: str, *, allow_display_name: bool) -> bool:
        if any(character in value for character in ("\r", "\n", "\x00")):
            return False
        display_name, address = parseaddr(value)
        if not allow_display_name and display_name:
            return False
        if address != value.strip() and not allow_display_name:
            return False
        local, separator, domain = address.rpartition("@")
        return bool(separator and local and "." in domain and not domain.startswith("."))

    def assert_stripe_stage_configuration(self: Any) -> bool:
        """Validate an all-or-nothing Stripe bundle without enabling Checkout."""
        restricted_key = (
            self.stripe_restricted_key.get_secret_value().strip() if self.stripe_restricted_key is not None else ""
        )
        webhook_secret = (
            self.stripe_webhook_secret.get_secret_value().strip() if self.stripe_webhook_secret is not None else ""
        )
        price_ids = (
            self.stripe_price_starter.strip(),
            self.stripe_price_core.strip(),
            self.stripe_price_pro.strip(),
        )
        if not any((restricted_key, webhook_secret, *price_ids)):
            return False
        if not restricted_key:
            raise RuntimeError(
                "Stripe staging configuration must be complete or entirely absent; a Stripe restricted key is required."
            )
        if not webhook_secret:
            raise RuntimeError(
                "Stripe staging configuration must be complete or entirely absent; "
                "a Stripe webhook signing secret is required."
            )
        if not all(price_id.startswith("price_") for price_id in price_ids):
            raise RuntimeError(
                "Stripe staging configuration must be complete or entirely absent; "
                "all three Stripe credit Price IDs are required."
            )
        if self.stripe_automatic_tax_enabled:
            raise RuntimeError(
                "Stripe Automatic Tax is owner-gated until active tax registrations "
                "and the tax-inclusive catalog are reviewed."
            )

        self.assert_stripe_gateway_configuration()
        if "{CHECKOUT_SESSION_ID}" not in self.stripe_success_url:
            raise RuntimeError("Stripe success URL must include {CHECKOUT_SESSION_ID}.")
        if not self.is_dev and (
            not self.stripe_success_url.startswith("https://") or not self.stripe_cancel_url.startswith("https://")
        ):
            raise RuntimeError("Stripe return URLs must use HTTPS outside development.")
        return True

    def assert_stripe_gateway_configuration(self: Any) -> None:
        """Require mode-matched, non-empty secrets before any Stripe SDK use."""
        restricted_key = (
            self.stripe_restricted_key.get_secret_value().strip() if self.stripe_restricted_key is not None else ""
        )
        webhook_secret = (
            self.stripe_webhook_secret.get_secret_value().strip() if self.stripe_webhook_secret is not None else ""
        )
        expected_key_prefix = "rk_test_" if self.is_dev else "rk_live_"
        if not restricted_key.startswith(expected_key_prefix):
            raise RuntimeError(
                "A Stripe restricted key with an "
                f"{expected_key_prefix} prefix is required for paid credits "
                "in this runtime environment."
            )
        if not webhook_secret.startswith("whsec_"):
            raise RuntimeError("A Stripe webhook signing secret is required for paid credits.")

    @property
    def paid_credit_checkout_enabled(self: Any) -> bool:
        """Expose the complete launch gate without activating any side effect."""
        return cast(
            bool,
            self.paid_credits_enabled
            and self.consumer_policy_approved
            and self.durable_confirmation_channel_ready
            and self.adjustment_workflow_ready,
        )
