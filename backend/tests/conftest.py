import sys
from unittest.mock import MagicMock

# Mock modules that require compilation/heavy install
sys.modules["faster_whisper"] = MagicMock()
sys.modules["stable_whisper"] = MagicMock()
sys.modules["pydub"] = MagicMock()
