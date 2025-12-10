
import pytest
from backend.app.core import settings

def test_coerce_bool():
    """Test boolean coercion logic."""
    assert settings._coerce_bool(True, False) is True
    assert settings._coerce_bool(False, True) is False
    
    # Strings
    assert settings._coerce_bool("true", False) is True
    assert settings._coerce_bool("1", False) is True
    assert settings._coerce_bool("on", False) is True
    assert settings._coerce_bool("YES", False) is True
    
    assert settings._coerce_bool("false", True) is False
    assert settings._coerce_bool("0", True) is False
    
    # Fallback
    assert settings._coerce_bool("random", True) is True
    assert settings._coerce_bool(None, False) is False

def test_coerce_int_float_error():
    """Test numeric coercion error handling."""
    assert settings._coerce_int("123", 0) == 123
    assert settings._coerce_int("invalid", 10) == 10
    
    assert settings._coerce_float("1.5", 0.0) == 1.5
    assert settings._coerce_float("invalid", 1.0) == 1.0
