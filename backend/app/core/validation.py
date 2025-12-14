"""Validation utilities for security and data integrity."""

import re

# Strict hex color validation for ASS (&HAABBGGRR) and HTML (#RRGGBB)
# Matches:
# - &H followed by 1-8 hex digits (e.g., &H0000FFFF)
# - # followed by 3-8 hex digits (e.g., #FFFFFF, #FFFFFFFF)
COLOR_PATTERN = re.compile(r"^(&H[0-9A-Fa-f]{1,8}|#[0-9A-Fa-f]{3,8})$")

def validate_color_hex(value: str | None) -> None:
    """
    Validate that a string is a safe hex color code.
    Raises ValueError if invalid.
    """
    if not value:
        return

    clean = value.strip()

    if not COLOR_PATTERN.match(clean):
        # Allow checking if it contains dangerous chars explicitly for better error messages
        if "," in value or "\n" in value or "\r" in value:
            raise ValueError("Color contains invalid characters (injection attempt detected)")
        raise ValueError(f"Invalid color format: {value}")
