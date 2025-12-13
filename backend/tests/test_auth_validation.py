"""Tests for input validation in auth flow."""
from backend.app.core.ratelimit import limiter_register


class TestEmailValidation:
    """Test email validation logic via API."""

    def test_invalid_emails_registration(self, client):
        """Test that registration fails with invalid emails."""
        invalid_emails = [
            "plainaddress",
            "#@%^%#$@#$@#.com",
            "@example.com",
            "Joe Smith <email@example.com>",
            "email.example.com",
            "email@example@example.com",
        ]

        for email in invalid_emails:
            limiter_register.reset()
            response = client.post("/auth/register", json={
                "email": email,
                "password": "ValidPassword123",
                "name": "Test User"
            })
            assert response.status_code == 400, f"Email {email} should be rejected, got {response.status_code}"

    def test_valid_emails_registration(self, client):
        """Test that registration succeeds with valid emails."""
        valid_emails = [
            "valid.user@example.com",
            "user+tag@domain.co.uk",
            "123user@sub.domain.org"
        ]

        for email in valid_emails:
            limiter_register.reset()
            response = client.post("/auth/register", json={
                "email": email,
                "password": "ValidPassword123",
                "name": "Test User"
            })
            # Should succeed (200)
            assert response.status_code == 200, f"Email {email} should be accepted, got {response.status_code} {response.text}"
