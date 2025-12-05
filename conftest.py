"""
Test configuration to keep imports stable across backend and frontend suites.

Pytest prepends each test directory to ``sys.path``. When we run both the
Streamlit tests (which expect ``import app`` to load the root ``app.py``) and
the FastAPI backend tests (which live under ``backend/``), Python can
accidentally resolve ``import app`` to ``backend/app/__init__.py`` instead of
the Streamlit entrypoint. That breaks several tests that monkeypatch helpers
on the real app module.

We explicitly place the project root at the front of ``sys.path`` and evict any
wrongly-loaded ``app`` module so subsequent imports hit ``app.py`` reliably.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
root_str = str(PROJECT_ROOT)

# Ensure the project root takes precedence over test directories such as
# ``backend`` so ``import app`` resolves to ``app.py``.
if root_str in sys.path:
    sys.path.remove(root_str)
sys.path.insert(0, root_str)

# If pytest already imported the wrong ``app`` module (e.g., backend/app),
# remove it so the next import loads the Streamlit entrypoint.
mod = sys.modules.get("app")
if mod:
    mod_path = getattr(mod, "__file__", "") or ""
    backend_app_dir = PROJECT_ROOT / "backend" / "app"
    try:
        if Path(mod_path).resolve().is_relative_to(backend_app_dir):
            sys.modules.pop("app", None)
    except Exception:
        sys.modules.pop("app", None)

# Force-load the Streamlit app module so subsequent ``import app`` calls use it,
# even if other paths shadow the name later in the session.
app_path = PROJECT_ROOT / "app.py"
if "app" not in sys.modules and app_path.exists():
    spec = importlib.util.spec_from_file_location("app", app_path)
    if spec and spec.loader:
        app_module = importlib.util.module_from_spec(spec)
        sys.modules["app"] = app_module
        spec.loader.exec_module(app_module)
