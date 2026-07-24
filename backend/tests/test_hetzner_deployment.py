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
    assert 'GSP_PAID_CREDITS_ENABLED: "0"' in compose
    assert 'GSP_STRIPE_AUTOMATIC_TAX_ENABLED: "0"' in compose
    assert 'GSP_STRIPE_RESTRICTED_KEY: ""' in compose
    assert 'GSP_STRIPE_WEBHOOK_SECRET: ""' in compose
    assert 'GSP_STRIPE_PRICE_STARTER: ""' in compose
    assert 'GSP_STRIPE_PRICE_CORE: ""' in compose
    assert 'GSP_STRIPE_PRICE_PRO: ""' in compose
    assert 'STRIPE_SECRET_KEY: ""' in compose
    assert 'STRIPE_WEBHOOK_SECRET: ""' in compose
    assert 'OPENAI_API_KEY: ""' in compose
    assert 'GROQ_API_KEY: ""' in compose
    assert 'ELEVENLABS_API_KEY: ""' in compose
    assert 'GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD: "0"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD: "0"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD: "0"' in compose
    assert "external: true" in compose
    assert "name: mizai_mizai-private" in compose


def test_production_verifier_requires_every_fail_closed_runtime_setting() -> None:
    verifier = deployment_text("verify-production.sh")

    for expected in (
        "GSP_MOCK_EXTERNAL_SERVICES=1",
        "GSP_ELEVENLABS_ENABLED=0",
        "GSP_PAID_CREDITS_ENABLED=0",
        "GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0",
        "GSP_STRIPE_RESTRICTED_KEY=",
        "GSP_STRIPE_WEBHOOK_SECRET=",
        "GSP_STRIPE_PRICE_STARTER=",
        "GSP_STRIPE_PRICE_CORE=",
        "GSP_STRIPE_PRICE_PRO=",
        "STRIPE_SECRET_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
        "OPENAI_API_KEY=",
        "GROQ_API_KEY=",
        "ELEVENLABS_API_KEY=",
        "GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0",
        "GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=0",
        "GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0",
    ):
        assert expected in verifier


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
