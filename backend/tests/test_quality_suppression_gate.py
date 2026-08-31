from __future__ import annotations

import importlib.util
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType, SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GATE_PATH = REPOSITORY_ROOT / ".codex" / "scripts" / "check_quality_suppressions.py"


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_quality_suppressions", GATE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load quality-suppression gate")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_gate_inventories_tracked_and_new_nonignored_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    gate = load_gate()
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout=b"src/App.java\0new/code.py\0", stderr=b"")

    monkeypatch.setattr(gate.subprocess, "run", fake_run)

    assert gate.repository_paths(tmp_path) == (
        PurePosixPath("src/App.java"),
        PurePosixPath("new/code.py"),
    )
    assert captured["command"] == [
        "git",
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
    ]


def test_gate_rejects_pmd_and_duplicate_suppressions(tmp_path: Path) -> None:
    gate = load_gate()
    java = PurePosixPath("src/App.java")
    python = PurePosixPath("backend/app.py")
    java_path = tmp_path.joinpath(*java.parts)
    python_path = tmp_path.joinpath(*python.parts)
    java_path.parent.mkdir(parents=True)
    python_path.parent.mkdir(parents=True)
    java_path.write_text(
        "// NO" + "PMD\n@Suppress" + 'Warnings("PMD.CognitiveComplexity")\nclass App {}\n',
        encoding="utf-8",
    )
    python_path.write_text(
        "# jscpd:" + "ignore-start\nvalue = 1\n# jscpd:" + "ignore-end\n",
        encoding="utf-8",
    )

    findings = gate.suppression_findings(tmp_path, (java, python))

    assert [(str(item.path), item.line) for item in findings] == [
        ("backend/app.py", 1),
        ("backend/app.py", 3),
        ("src/App.java", 1),
        ("src/App.java", 2),
    ]


def test_gate_accepts_normal_source_and_documentation(tmp_path: Path) -> None:
    gate = load_gate()
    java = PurePosixPath("src/App.java")
    markdown = PurePosixPath("docs/example.md")
    java_path = tmp_path.joinpath(*java.parts)
    markdown_path = tmp_path.joinpath(*markdown.parts)
    java_path.parent.mkdir(parents=True)
    markdown_path.parent.mkdir(parents=True)
    java_path.write_text("class App {}\n", encoding="utf-8")
    markdown_path.write_text("Documentation fixture\n", encoding="utf-8")

    assert gate.suppression_findings(tmp_path, (java, markdown)) == ()


def test_gate_rejects_formatter_bypasses(tmp_path: Path) -> None:
    gate = load_gate()
    python = PurePosixPath("backend/app.py")
    python_stub = PurePosixPath("backend/types.pyi")
    typescript = PurePosixPath("frontend/app.ts")
    eslint_config = PurePosixPath("frontend/eslint.config.mjs")
    python_path = tmp_path.joinpath(*python.parts)
    python_stub_path = tmp_path.joinpath(*python_stub.parts)
    typescript_path = tmp_path.joinpath(*typescript.parts)
    eslint_config_path = tmp_path.joinpath(*eslint_config.parts)
    python_path.parent.mkdir(parents=True)
    typescript_path.parent.mkdir(parents=True)
    python_path.write_text("# fmt:" + " off\nvalue=1\n", encoding="utf-8")
    python_stub_path.write_text("value: int  # fmt:" + " skip\n", encoding="utf-8")
    typescript_path.write_text("// prettier-" + "ignore\nconst value=1;\n", encoding="utf-8")
    eslint_config_path.write_text(
        "// prettier-" + "ignore\nexport default {};\n",
        encoding="utf-8",
    )

    findings = gate.suppression_findings(
        tmp_path,
        (python, python_stub, typescript, eslint_config),
    )

    assert [(str(item.path), item.line) for item in findings] == [
        ("backend/app.py", 1),
        ("backend/types.pyi", 1),
        ("frontend/app.ts", 1),
        ("frontend/eslint.config.mjs", 1),
    ]


def test_gate_rejects_clone_suppressions_in_module_configs(tmp_path: Path) -> None:
    gate = load_gate()
    module = PurePosixPath("frontend/build.config.cjs")
    module_path = tmp_path.joinpath(*module.parts)
    module_path.parent.mkdir(parents=True)
    module_path.write_text(
        "// jscpd:" + "ignore-start\nmodule.exports = {};\n// jscpd:" + "ignore-end\n",
        encoding="utf-8",
    )

    findings = gate.suppression_findings(tmp_path, (module,))

    assert [(str(item.path), item.line) for item in findings] == [
        ("frontend/build.config.cjs", 1),
        ("frontend/build.config.cjs", 3),
    ]
