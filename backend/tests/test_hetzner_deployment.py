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
    assert 'GSP_GCS_BUCKET: ""' in compose
    assert 'GOOGLE_APPLICATION_CREDENTIALS: ""' in compose
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
        "GSP_GCS_BUCKET=",
        "GOOGLE_APPLICATION_CREDENTIALS=",
        "GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0",
        "GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=0",
        "GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0",
        "GSP_WORKSPACE_RETENTION_HOURS=24",
        "GSP_STALE_JOB_RETENTION_HOURS=6",
        "GSP_ORPHAN_RETENTION_HOURS=1",
        "GSP_CLEANUP_INTERVAL_MINUTES=15",
        "GSP_STORAGE_MIN_FREE_MB=2048",
        "GSP_RETENTION_CLEANUP_ENABLED=1",
    ):
        assert expected in verifier


def test_production_environment_defaults_do_not_prune_shared_cache() -> None:
    environment = deployment_text("subframe.env.example")
    compose = deployment_text("docker-compose.production.yml")
    deploy_script = deployment_text("deploy-production.sh")
    frontend_dockerfile = (
        REPOSITORY_ROOT / "frontend" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "SUBFRAME_HOSTNAME=gsubs.gr" in environment
    # REGRESSION: the browser and backend production ceilings both used 95 MB
    # while other runtime defaults silently allowed 1 GiB.
    assert "SUBFRAME_MAX_UPLOAD_MB=500" in environment
    assert "GSP_MAX_UPLOAD_MB=500" in environment
    assert "GSP_WORKSPACE_RETENTION_HOURS=24" in environment
    assert "GSP_STALE_JOB_RETENTION_HOURS=6" in environment
    assert "GSP_ORPHAN_RETENTION_HOURS=1" in environment
    assert "GSP_CLEANUP_INTERVAL_MINUTES=15" in environment
    assert "GSP_STORAGE_MIN_FREE_MB=2048" in environment
    assert "GSP_RETENTION_CLEANUP_ENABLED=1" in environment
    assert "NEXT_PUBLIC_MAX_UPLOAD_MB: ${SUBFRAME_MAX_UPLOAD_MB:-500}" in compose
    assert "ARG NEXT_PUBLIC_MAX_UPLOAD_MB=500" in frontend_dockerfile
    assert "GSP_ALLOWED_ORIGINS=https://gsubs.gr,https://www.gsubs.gr" in environment
    assert (
        "GSP_TRUSTED_HOSTS=gsubs.gr,www.gsubs.gr,backend,localhost,127.0.0.1"
        in environment
    )
    assert "subframe.mizai.gr" not in environment
    assert "SUBFRAME_PREVIEW_PORT=18090" in environment
    assert "SUBFRAME_PRUNE_BUILD_CACHE=0" in environment
    assert '${SUBFRAME_PRUNE_BUILD_CACHE:-0}' in deploy_script


def test_edge_routes_billing_api_and_verifier_smokes_catalog() -> None:
    """REGRESSION: the deployed edge previously sent /billing to Next.js."""
    caddyfile = deployment_text("Caddyfile")
    verifier = deployment_text("verify-production.sh")

    assert "/billing /billing/*" in caddyfile
    assert "/billing/catalog" in verifier


def test_docker_build_context_excludes_production_secrets_and_state() -> None:
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")

    assert ".env*" in dockerignore.splitlines()
    assert "**/.env*" in dockerignore.splitlines()
    assert ".runtime/" in dockerignore.splitlines()
    assert "backups/" in dockerignore.splitlines()


def test_backend_image_contains_the_gsubs_watermark() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    watermark = REPOSITORY_ROOT / "gsubs-logo.png"

    assert watermark.is_file()
    assert "COPY gsubs-logo.png /gsubs-logo.png" in dockerfile


def test_frontend_image_applies_the_patched_dependency_compatibility_export() -> None:
    dockerfile = (REPOSITORY_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    package = (REPOSITORY_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    patch_script = REPOSITORY_ROOT / "frontend" / "scripts" / "patch-brace-expansion.cjs"
    script_copy = "COPY scripts/patch-brace-expansion.cjs"

    assert '"brace-expansion": "5.0.8"' in package
    assert '"postinstall": "node scripts/patch-brace-expansion.cjs"' in package
    assert patch_script.is_file()
    assert script_copy in dockerfile
    assert dockerfile.index(script_copy) < dockerfile.index("RUN npm ci")


def test_frontend_build_context_excludes_generated_and_local_state() -> None:
    dockerignore = (REPOSITORY_ROOT / "frontend" / ".dockerignore").read_text(
        encoding="utf-8",
    ).splitlines()

    for expected in (
        "node_modules/",
        ".next/",
        "coverage/",
        "test-results/",
        "playwright-report/",
        ".env*",
    ):
        assert expected in dockerignore


def test_deployment_shell_scripts_have_valid_syntax() -> None:
    for filename in ("backup.sh", "deploy-production.sh", "verify-production.sh"):
        completed = subprocess.run(
            ["sh", "-n", str(DEPLOYMENT_ROOT / filename)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
