from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ISOLATED_RUNNER_PATH = REPOSITORY_ROOT / ".codex" / "scripts" / "run_isolated_quality_gate.py"
COVERAGE_GATE_PATH = REPOSITORY_ROOT / ".codex" / "scripts" / "check_coverage_thresholds.py"


def load_isolated_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_isolated_quality_gate",
        ISOLATED_RUNNER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load isolated quality runner")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_coverage_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "check_coverage_thresholds",
        COVERAGE_GATE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load coverage threshold gate")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object | None]] = []

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(
        self,
        _exception_type: object,
        _exception: object,
        _traceback: object,
    ) -> None:
        return None

    def execute(
        self,
        statement: object,
        parameters: object | None = None,
    ) -> None:
        self.calls.append((statement, parameters))


def test_temporary_database_url_preserves_encoded_credentials_and_ipv6() -> None:
    runner = load_isolated_runner()

    assert runner.temporary_database_url(
        "postgresql://ci%40user:p%2Fss@[::1]:5544/postgres",
        "gsp_ci_test",
    ) == ("postgresql+psycopg://ci%40user:p%2Fss@[::1]:5544/gsp_ci_test")


def test_isolated_runner_rejects_non_quality_commands() -> None:
    runner = load_isolated_runner()

    with pytest.raises(ValueError, match="must start"):
        runner.quality_command(["deploy:production"])


def test_isolated_runner_creates_and_drops_a_unique_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # REGRESSION: local `make check-all` reused gsp_test, so stale billing
    # fixtures could turn a clean codebase into a false 409 CI failure.
    runner = load_isolated_runner()
    connection = FakeConnection()
    captured: dict[str, object] = {}

    monkeypatch.setenv(
        "GSP_TEST_ADMIN_DATABASE_URL",
        "postgresql://gsp:gsp@127.0.0.1:5432/postgres",
    )
    monkeypatch.setattr(runner.psycopg, "connect", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr(runner.os, "getpid", lambda: 1234)
    monkeypatch.setattr(runner.secrets, "token_hex", lambda _length: "deadbeef")

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        check: bool,
    ) -> SimpleNamespace:
        captured.update(
            {
                "command": command,
                "cwd": cwd,
                "database_url": env["GSP_DATABASE_URL"],
                "check": check,
            }
        )
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    assert runner.main(["check:all"]) == 7
    assert captured["command"] == [
        runner.sys.executable,
        str(runner.QUALITY_RUNNER),
        "check:all",
    ]
    assert captured["cwd"] == REPOSITORY_ROOT
    assert captured["database_url"] == ("postgresql+psycopg://gsp:gsp@127.0.0.1:5432/gsp_ci_1234_deadbeef")
    assert captured["check"] is False
    rendered_statements = "\n".join(str(statement) for statement, _ in connection.calls)
    assert "CREATE DATABASE" in rendered_statements
    assert "DROP DATABASE IF EXISTS" in rendered_statements
    assert connection.calls[-2][1] == ("gsp_ci_1234_deadbeef",)


def test_github_and_make_use_the_same_isolated_local_ci_entrypoint() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "quality-gates.yml").read_text(encoding="utf-8")
    make_contract = (REPOSITORY_ROOT / ".codex" / "quality.mk").read_text(encoding="utf-8")
    quality_contract = (REPOSITORY_ROOT / ".codex" / "quality-gates.json").read_text(encoding="utf-8")
    readme = (REPOSITORY_ROOT / "README.md").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    assert "push:\n    branches:\n      - main" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "timeout-minutes: 60" in workflow
    assert "run: make ci" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020" in workflow
    assert "actions/setup-java@03ad4de0992f5dab5e18fcb136590ce7c4a0ac95" in workflow
    assert ("GSP_TEST_ADMIN_DATABASE_URL: postgresql://gsp:gsp@localhost:5432/postgres") in workflow
    assert "GSP_DATABASE_URL:" not in workflow
    assert "ci: check-all" in make_contract
    assert "$(ISOLATED_QUALITY_RUNNER) check:all" in make_contract
    assert "mypy backend/app .codex/scripts/run_isolated_quality_gate.py" in (quality_contract)
    assert '"check:complexity"' in quality_contract
    assert "check_code_complexity.py" in quality_contract
    assert "shellcheck .codex/scripts/*.sh deploy/hetzner/*.sh" in quality_contract
    assert "check_coverage_thresholds.py .coverage.json --lines 90 --branches 80" in quality_contract
    assert "check-complexity:" in make_contract
    assert "`make ci` is the canonical local and GitHub entrypoint" in readme


def test_coverage_gate_enforces_lines_and_branches_independently(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = load_coverage_gate()
    report = tmp_path / "coverage.json"
    report.write_text(
        '{"totals":{"covered_lines":91,"num_statements":100,'
        '"covered_branches":81,"num_branches":100}}',
        encoding="utf-8",
    )

    assert gate.main([str(report), "--lines", "90", "--branches", "80"]) == 0
    assert "PASS: coverage thresholds met" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("covered_lines", "covered_branches", "failed_metric"),
    [(89, 81, "lines"), (91, 79, "branches")],
)
def test_coverage_gate_fails_when_one_metric_drops_below_its_floor(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    covered_lines: int,
    covered_branches: int,
    failed_metric: str,
) -> None:
    gate = load_coverage_gate()
    report = tmp_path / "coverage.json"
    report.write_text(
        '{"totals":{'
        f'"covered_lines":{covered_lines},"num_statements":100,'
        f'"covered_branches":{covered_branches},"num_branches":100'
        '}}',
        encoding="utf-8",
    )

    assert gate.main([str(report), "--lines", "90", "--branches", "80"]) == 1
    error = capsys.readouterr().err
    assert "FAIL: coverage threshold missed" in error
    assert failed_metric in error


def test_coverage_gate_rejects_reports_without_branch_data(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = load_coverage_gate()
    report = tmp_path / "coverage.json"
    report.write_text(
        '{"totals":{"covered_lines":91,"num_statements":100,'
        '"covered_branches":0,"num_branches":0}}',
        encoding="utf-8",
    )

    assert gate.main([str(report)]) == 2
    assert "no branches to evaluate" in capsys.readouterr().err


def test_all_github_actions_are_pinned_to_full_commit_shas() -> None:
    workflow_directory = REPOSITORY_ROOT / ".github" / "workflows"
    action_reference = re.compile(r"uses:\s+[^@\s]+@([^\s#]+)")

    references = [
        (workflow.name, match.group(1))
        for workflow in sorted(workflow_directory.glob("*.yml"))
        for match in action_reference.finditer(workflow.read_text(encoding="utf-8"))
    ]

    assert references
    assert all(re.fullmatch(r"[0-9a-f]{40}", revision) for _, revision in references)


def test_supply_chain_and_container_workflows_cover_release_inputs() -> None:
    workflow_directory = REPOSITORY_ROOT / ".github" / "workflows"
    codeql = (workflow_directory / "codeql.yml").read_text(encoding="utf-8")
    supply_chain = (workflow_directory / "supply-chain.yml").read_text(encoding="utf-8")
    containers = (workflow_directory / "container-images.yml").read_text(encoding="utf-8")
    dependabot = (REPOSITORY_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    wrapper = (REPOSITORY_ROOT / ".mvn" / "wrapper" / "maven-wrapper.properties").read_text(
        encoding="utf-8"
    )

    for language in ("javascript-typescript", "python", "java-kotlin"):
        assert language in codeql
    assert "queries: security-extended" in codeql
    assert "gitleaks/gitleaks-action@" in supply_chain
    assert "actions/dependency-review-action@" in supply_chain
    assert "fail-on-severity: high" in supply_chain
    assert "docker/build-push-action@" in containers
    assert "aquasecurity/trivy-action@" in containers
    assert "severity: HIGH,CRITICAL" in containers
    for ecosystem in ("github-actions", "npm", "pip", "maven", "docker"):
        assert f"package-ecosystem: {ecosystem}" in dependabot
    assert (
        "distributionSha256Sum=55fadd669532a3205d5db95f490bf13971d8b0843526f407f29db0e61f074ab3"
        in wrapper
    )


def test_runtime_images_apply_security_updates_and_drop_unused_package_managers() -> None:
    backend_dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    frontend_dockerfile = (REPOSITORY_ROOT / "frontend" / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "apt-get update && apt-get upgrade -y" in backend_dockerfile
    assert "apk upgrade --no-cache" in frontend_dockerfile
    assert "rm -rf /usr/local/lib/node_modules/npm" in frontend_dockerfile
    assert "rm -f /usr/local/bin/npm" in frontend_dockerfile


def test_shell_gate_keeps_backup_validation_effectful_and_audits_dependencies() -> None:
    verify_backup = (REPOSITORY_ROOT / "deploy" / "hetzner" / "verify-backup.sh").read_text(
        encoding="utf-8"
    )
    security_gate = (REPOSITORY_ROOT / ".codex" / "scripts" / "run_security_gate.sh").read_text(
        encoding="utf-8"
    )

    assert 'read_independent_mount_options "$INDEPENDENT_DIR" >/dev/null' in verify_backup
    assert "independent_mount_options=" not in verify_backup
    assert "tr '[:upper:]' '[:lower:]'" in verify_backup
    assert "pip check" in security_gate
