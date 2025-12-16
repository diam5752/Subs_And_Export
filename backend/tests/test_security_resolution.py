
import pytest
from backend.app.api.endpoints import videos
from backend.app.core import config

def test_parse_resolution_huge_values():
    """Test that _parse_resolution rejects huge values."""
    w, h = videos._parse_resolution("100000x100000")
    assert w is None
    assert h is None

def test_parse_resolution_valid():
    w, h = videos._parse_resolution("1920x1080")
    assert w == 1920
    assert h == 1080

def test_parse_resolution_invalid_format():
    w, h = videos._parse_resolution("invalid")
    assert w is None
    assert h is None

def test_parse_resolution_max_limit():
    """Test boundary condition."""
    limit = config.MAX_RESOLUTION_DIMENSION
    # Exact limit should pass
    w, h = videos._parse_resolution(f"{limit}x{limit}")
    assert w == limit
    assert h == limit

    # Limit + 1 should fail
    w, h = videos._parse_resolution(f"{limit+1}x{limit}")
    assert w is None
    assert h is None
