"""Tests for configuration helper functions."""

from backend.app.core.gcs import _coerce_bool


def test_coerce_bool_with_bool_values() -> None:
    """Test boolean coercion with actual boolean values."""
    # When given a bool, the function doesn't handle it directly
    # as it only accepts str | None. These are edge cases.
    pass


def test_coerce_bool_with_truthy_strings() -> None:
    """Test boolean coercion with truthy string values."""
    assert _coerce_bool("true", False) is True
    assert _coerce_bool("1", False) is True
    assert _coerce_bool("on", False) is True
    assert _coerce_bool("YES", False) is True
    assert _coerce_bool("  TRUE  ", False) is True  # With whitespace


def test_coerce_bool_with_falsy_strings() -> None:
    """Test boolean coercion with falsy string values."""
    assert _coerce_bool("false", True) is False
    assert _coerce_bool("0", True) is False
    assert _coerce_bool("no", True) is False
    assert _coerce_bool("off", True) is False
    assert _coerce_bool("  FALSE  ", True) is False  # With whitespace


def test_coerce_bool_with_fallback() -> None:
    """Test boolean coercion falls back to default for unrecognized values."""
    assert _coerce_bool("random", True) is True
    assert _coerce_bool("random", False) is False
    assert _coerce_bool(None, False) is False
    assert _coerce_bool(None, True) is True
    assert _coerce_bool("", True) is True  # Empty string falls back to default
