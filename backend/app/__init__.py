"""
Backend package bootstrap.

We ensure the project root and ``src`` directory are on ``sys.path`` so the
FastAPI backend can reuse the shared ``greek_sub_publisher`` modules without
duplicating logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "src"

for candidate in (PROJECT_ROOT, SRC_DIR):
    # Ensure these paths are first so shared modules resolve to the project copy.
    if str(candidate) in sys.path:
        sys.path.remove(str(candidate))
    sys.path.insert(0, str(candidate))
