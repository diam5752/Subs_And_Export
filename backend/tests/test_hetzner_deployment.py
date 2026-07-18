from __future__ import annotations

import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = REPOSITORY_ROOT / "deploy" / "hetzner"


def deployment_text(filename: str) -> str:
    return (DEPLOYMENT_ROOT / filename).read_text(encoding="utf-8")


def test_production_compose_is_mock_only_and_loopback_bound() -> None:
    compose = deployment_text("docker-compose.production.yml")

    assert '"127.0.0.1:${SUBFRAME_PREVIEW_PORT:-18090}:8080"' in compose
    assert 'GSP_MOCK_EXTERNAL_SERVICES: "1"' in compose
    assert 'GSP_ELEVENLABS_ENABLED: "0"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD: "0"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD: "0"' in compose
    assert "external: true" in compose
    assert "name: mizai_mizai-private" in compose


def test_production_environment_defaults_do_not_prune_shared_cache() -> None:
    environment = deployment_text("subframe.env.example")
    deploy_script = deployment_text("deploy-production.sh")

    assert "SUBFRAME_PREVIEW_PORT=18090" in environment
    assert "SUBFRAME_PRUNE_BUILD_CACHE=0" in environment
    assert '${SUBFRAME_PRUNE_BUILD_CACHE:-0}' in deploy_script


def test_docker_build_context_excludes_production_secrets_and_state() -> None:
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env*" in dockerignore.splitlines()
    assert "**/.env*" in dockerignore.splitlines()
    assert ".runtime/" in dockerignore.splitlines()
    assert "backups/" in dockerignore.splitlines()


def test_deployment_shell_scripts_have_valid_syntax() -> None:
    for filename in ("backup.sh", "deploy-production.sh", "verify-production.sh"):
        completed = subprocess.run(
            ["sh", "-n", str(DEPLOYMENT_ROOT / filename)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
