"""
Test configuration to keep imports stable across backend and frontend suites.

Pytest prepends each test directory to ``sys.path``. We explicitly place the
project root at the front so imports resolve to the checked-in source rather
than a similarly named module inside ``backend/``.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
root_str = str(PROJECT_ROOT)

if root_str in sys.path:
    sys.path.remove(root_str)
sys.path.insert(0, root_str)
