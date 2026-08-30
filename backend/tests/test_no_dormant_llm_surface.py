"""Regression guard for the removed, unused text-generation surface."""

from __future__ import annotations

from pathlib import Path

from backend.app.core.config import settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_SOURCE_PATHS = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "backend" / "app",
    REPO_ROOT / "backend" / "cli.py",
    REPO_ROOT / "deploy",
    REPO_ROOT / "frontend" / "src",
    REPO_ROOT / "frontend" / "tests",
    REPO_ROOT / "src" / "main" / "java",
    REPO_ROOT / "src" / "main" / "resources" / "application.yml",
    REPO_ROOT / "docs",
)


def _source_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return [
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in {".py", ".sh", ".ts", ".tsx", ".java", ".yml", ".md"}
    ]


def test_active_source_has_no_retired_text_model_reference() -> None:
    retired_model_id = "-".join(("gpt", "5", "mini"))
    offenders = [
        str(candidate.relative_to(REPO_ROOT))
        for root in ACTIVE_SOURCE_PATHS
        for candidate in _source_files(root)
        if retired_model_id in candidate.read_text(encoding="utf-8").lower()
    ]

    assert offenders == []


def test_runtime_configuration_has_no_text_generation_models() -> None:
    for field_name in (
        "social_llm_model",
        "factcheck_llm_model",
        "extraction_llm_model",
        "use_llm_by_default",
        "llm_model",
        "llm_temperature",
        "llm_pricing",
    ):
        assert not hasattr(settings, field_name)
