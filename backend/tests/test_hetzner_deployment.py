from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from decimal import Decimal
from pathlib import Path

from backend.tests.hetzner_deployment_test_support import (
    DEPLOYMENT_ROOT,
    REPOSITORY_ROOT,
    copy_release_script,
    deployment_text,
    production_compose_decimal,
    write_gcs_retirement_evidence,
)


def test_production_compose_enables_reviewed_paid_credits_and_budgeted_scribe() -> None:
    compose = deployment_text("docker-compose.production.yml")

    assert '"127.0.0.1:${SUBFRAME_PREVIEW_PORT:-18090}:8080"' in compose
    assert "GSP_APP_ENV: production" in compose
    assert "APP_ENV: production" in compose
    assert 'GSP_MOCK_EXTERNAL_SERVICES: "0"' in compose
    assert 'GSP_ELEVENLABS_ENABLED: "1"' in compose
    assert 'GSP_ELEVENLABS_API_BASE: "http://app-edge:8081/elevenlabs"' in compose
    assert 'GSP_PAID_CREDITS_ENABLED: "1"' in compose
    assert 'GSP_CONSUMER_POLICY_APPROVED: "1"' in compose
    assert 'GSP_DURABLE_CONFIRMATION_CHANNEL_READY: "1"' in compose
    assert 'GSP_ADJUSTMENT_WORKFLOW_READY: "1"' in compose
    assert 'GSP_STRIPE_AUTOMATIC_TAX_ENABLED: "0"' in compose
    assert 'GSP_STRIPE_API_BASE: "http://app-edge:8081/stripe"' in compose
    assert 'GSP_STRIPE_RESTRICTED_KEY: "${GSP_STRIPE_RESTRICTED_KEY:-}"' in compose
    assert 'GSP_STRIPE_WEBHOOK_SECRET: "${GSP_STRIPE_WEBHOOK_SECRET:-}"' in compose
    assert 'GSP_STRIPE_PRICE_STARTER: "${GSP_STRIPE_PRICE_STARTER:-}"' in compose
    assert 'GSP_STRIPE_PRICE_CORE: "${GSP_STRIPE_PRICE_CORE:-}"' in compose
    assert 'GSP_STRIPE_PRICE_PRO: "${GSP_STRIPE_PRICE_PRO:-}"' in compose
    assert 'GSP_BILLING_ADMIN_USER_IDS: ""' in compose
    assert 'GSP_OBSERVABILITY_ENABLED: "1"' in compose
    assert 'GSP_OBSERVABILITY_RETENTION_HOURS: "168"' in compose
    assert 'GSP_OBSERVABILITY_PRESENCE_TTL_SECONDS: "90"' in compose
    assert 'GSP_OBSERVABILITY_ADMIN_USER_IDS: "${GSP_OBSERVABILITY_ADMIN_USER_IDS:?' in compose
    assert 'GSP_FEEDBACK_ENABLED: "1"' in compose
    assert "SUBFRAME_FEEDBACK_API_ENV_FILE is required" in compose
    assert 'GSP_DISABLE_RATELIMIT: "0"' in compose
    assert 'GSP_USE_MEMORY_RATELIMIT: "0"' in compose
    assert 'STRIPE_SECRET_KEY: ""' in compose
    assert 'STRIPE_WEBHOOK_SECRET: ""' in compose
    assert 'OPENAI_API_KEY: ""' in compose
    assert 'GROQ_API_KEY: ""' in compose
    assert 'ELEVENLABS_API_KEY: "${ELEVENLABS_API_KEY:?ELEVENLABS_API_KEY is required}"' in compose
    # REGRESSION: the production frontend once required cloud-object uploads
    # while the production runtime disabled them, making every paid job fail.
    assert "GSP_GCS" not in compose
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in compose
    assert 'GOOGLE_CLIENT_SECRET: ""' in compose
    assert 'GOOGLE_REDIRECT_URI: ""' in compose
    assert 'GSP_GOOGLE_OAUTH_CERTS_URL: "http://app-edge:8081/oauth2/v1/certs"' in compose
    assert 'GSP_BETA_LOGIN_PROMOTION_ENABLED: "1"' in compose
    assert 'GSP_MAX_VIDEO_DURATION_SECONDS: "180"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD: "100"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD: "10"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD: "0.05"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER: "1.25"' in compose
    # REGRESSION: production previously admitted one customer and had no
    # explicit container budget for bounded multi-user media work.
    assert 'GSP_MAX_ACTIVE_MEDIA_JOBS: "5"' in compose
    assert 'GSP_MEDIA_RENDER_SLOTS: "2"' in compose
    assert 'GSP_MEDIA_RENDER_THREADS_PER_SLOT: "2"' in compose
    assert 'GSP_MEDIA_EXTRACTION_SLOTS: "1"' in compose
    assert 'GSP_MEDIA_EXTRACTION_THREADS_PER_SLOT: "1"' in compose
    assert 'GSP_PROVIDER_TRANSCRIPTION_SLOTS: "8"' in compose
    assert 'GSP_UPLOAD_INACTIVITY_TIMEOUT_SECONDS: "30"' in compose
    assert 'cpus: "${SUBFRAME_BACKEND_CPUS:-3.0}"' in compose
    assert 'mem_limit: "${SUBFRAME_BACKEND_MEMORY_LIMIT:-3g}"' in compose
    assert "pids_limit: 256" in compose
    assert 'GSP_WORKSPACE_RETENTION_HOURS: "24"' in compose
    assert 'GSP_STALE_JOB_RETENTION_HOURS: "6"' in compose
    assert 'GSP_ORPHAN_RETENTION_HOURS: "1"' in compose
    assert 'GSP_CLEANUP_INTERVAL_MINUTES: "15"' in compose
    assert 'GSP_STORAGE_MIN_FREE_MB: "2048"' in compose
    assert 'GSP_RETENTION_CLEANUP_ENABLED: "1"' in compose
    assert "NEXT_PUBLIC_TRANSCRIBE_PROVIDER: elevenlabs" in compose
    assert "NEXT_PUBLIC_TRANSCRIBE_MODE: pro" in compose
    assert "NEXT_PUBLIC_MAX_VIDEO_DURATION_SECONDS: ${SUBFRAME_MAX_VIDEO_DURATION_SECONDS:-180}" in compose
    assert "external: true" in compose
    assert "name: mizai_mizai-private" in compose


def test_feedback_mailer_is_isolated_and_gates_public_cutover() -> None:
    compose = deployment_text("docker-compose.production.yml")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    caddyfile = deployment_text("Caddyfile")
    main_environment = deployment_text("subframe.env.example")
    api_environment = deployment_text("feedback-api.env.example")
    worker_environment = deployment_text("feedback-worker.env.example")

    db = compose.split("  db:", 1)[1].split("\n  backend:", 1)[0]
    worker = compose.split("  feedback-worker:", 1)[1].split("\n  frontend:", 1)[0]
    backend = compose.split("  backend:", 1)[1].split("\n  feedback-worker:", 1)[0]
    app_edge = compose.split("  app-edge:", 1)[1].split("\n  edge:", 1)[0]
    assert 'command: ["python", "-m", "backend.cli", "feedback-worker"]' in worker
    assert 'test: ["CMD", "python", "-m", "backend.cli", "check-feedback-worker"]' in worker
    assert "provider_egress" in worker
    assert "provider_egress" not in backend
    assert "ports:" not in worker
    assert "read_only: true" in worker
    assert "SUBFRAME_ENV_FILE" not in worker
    assert "SUBFRAME_FEEDBACK_WORKER_ENV_FILE" in worker
    assert "SUBFRAME_FEEDBACK_WORKER_ENV_FILE is required" in worker
    assert 'GSP_FEEDBACK_RETENTION_DAYS: "180"' in worker
    assert "SUBFRAME_FEEDBACK_API_ENV_FILE" in backend
    assert "SUBFRAME_FEEDBACK_API_ENV_FILE" not in worker
    assert "SUBFRAME_FEEDBACK_API_ENV_FILE" not in db
    assert "feedback-worker:" in app_edge
    assert "condition: service_healthy" in app_edge
    assert "GSP_FEEDBACK_SMTP_PASSWORD" not in backend
    assert "GSP_FEEDBACK_SMTP_PASSWORD" not in main_environment
    assert "GSP_FEEDBACK_SMTP_PASSWORD" not in api_environment
    assert "GSP_FEEDBACK_SMTP_PASSWORD" in worker_environment
    assert "GSP_DATABASE_URL" not in api_environment
    assert "GSP_DATABASE_URL" in worker_environment
    assert "GSP_FEEDBACK_HASH_SECRET" in api_environment
    assert "GSP_DOWNLOAD_GRANT_SECRET" in api_environment
    assert "GSP_FEEDBACK_HASH_SECRET" not in main_environment
    assert "GSP_DOWNLOAD_GRANT_SECRET" not in main_environment
    assert "GSP_FEEDBACK_HASH_SECRET" not in worker_environment
    assert "GSP_DOWNLOAD_GRANT_SECRET" not in worker_environment
    for provider_secret in (
        "ELEVENLABS_API_KEY",
        "GSP_STRIPE_RESTRICTED_KEY",
        "GSP_STRIPE_WEBHOOK_SECRET",
        "GOOGLE_CLIENT_SECRET",
        "OPENAI_API_KEY",
        "GROQ_API_KEY",
    ):
        assert provider_secret not in worker_environment
    assert "/feedback" in caddyfile

    cutover = deploy_script.split('install -d -m 700 "$STATE_DIR"', 1)[1]
    core_start = cutover.index("compose up -d backend frontend")
    worker_start = cutover.index("compose up -d feedback-worker")
    app_edge_start = cutover.index("compose up -d --no-deps --force-recreate app-edge")
    assert core_start < worker_start < app_edge_start
    assert "Feedback notification worker is unhealthy" in deploy_script
    assert "Feedback $feedback_env_label env permissions must be 0600" in deploy_script
    assert "SUBFRAME_FEEDBACK_API_ENV_FILE" in deploy_script
    assert "SUBFRAME_FEEDBACK_WORKER_ENV_FILE" in deploy_script
    assert "feedback-worker" in verifier
    assert "Feedback $feedback_env_label env permissions must be 0600" in verifier
    assert "public API must not have general provider egress" in verifier
    assert "SMTP credentials must remain isolated" in verifier
    assert "database container must not receive API-only signing secrets" in verifier
    assert "Backend download-grant signing secret is missing or too short" in verifier
    assert "GSP_DOWNLOAD_GRANT_TTL_SECONDS=300" in verifier
    assert "Feedback worker retention must be pinned to 180 days" in verifier
    assert "GSP_DISABLE_RATELIMIT=0" in verifier
    assert "GSP_USE_MEMORY_RATELIMIT=0" in verifier
    assert "Production feedback honeypot canary" in verifier


def test_production_media_storage_is_local_to_the_existing_vm_root_disk() -> None:
    compose = deployment_text("docker-compose.production.yml")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    top_level_volumes = compose.split("\nvolumes:\n", 1)[1]
    anchor_preparation = deploy_script.split("prepare_erasure_anchor_directory() {", 1)[1].split(
        "\n}\n\ninitialize_or_verify_privacy_continuity()", 1
    )[0]

    # REGRESSION: private media storage must not silently provision a Hetzner
    # block volume, NFS mount, or other separately billed storage backend.
    assert "driver:" not in top_level_volumes
    assert "driver_opts:" not in top_level_volumes
    assert "external:" not in top_level_volumes
    assert "name: subframe-app-data" in top_level_volumes
    assert "name: subframe-erasure-journal" in top_level_volumes
    assert "docker volume inspect" in verifier
    assert verifier.count("assert_existing_vm_local_volume() {") == 1
    assert "Existing-VM storage volume must use Docker's local driver" in verifier
    assert "Existing-VM storage volume is not on the host root filesystem" in verifier
    assert "subframe-app-data" in verifier
    assert "subframe-erasure-journal" in verifier
    assert 'ERASURE_ANCHOR_DIR="$STATE_DIR/privacy-erasure-anchor"' in deploy_script
    assert 'ERASURE_ANCHOR_DIR="$ROOT_DIR/.runtime/privacy-erasure-anchor"' in verifier
    assert 'SUBFRAME_ERASURE_ANCHOR_DIR="$ERASURE_ANCHOR_DIR"' in deploy_script
    assert 'SUBFRAME_ERASURE_ANCHOR_DIR="$ERASURE_ANCHOR_DIR"' in verifier
    install_anchor = 'install -d -m 700 "$ERASURE_ANCHOR_DIR"'
    chown_anchor = 'chown 10001:10001 "$ERASURE_ANCHOR_DIR"'
    assert install_anchor in anchor_preparation
    assert chown_anchor in anchor_preparation
    assert "install -d -m 700 -o 10001 -g 10001" not in anchor_preparation
    assert anchor_preparation.index(install_anchor) < anchor_preparation.index(chown_anchor)
    assert anchor_preparation.index(chown_anchor) < anchor_preparation.index("portable_owner")
    assert "assert_existing_vm_anchor_bind" in verifier
    assert "Erasure-journal anchor is not on the host root filesystem" in verifier
    assert "Backend erasure-journal anchor must use its dedicated writable host bind" in verifier
    assert "api.hetzner" not in compose
    assert "api.hetzner" not in deploy_script


def test_production_provider_budget_is_launch_capacity_not_demo_capacity() -> None:
    # REGRESSION: the original $0.25/day and $0.75/month trial ceilings could
    # stop paid customer work after only a handful of videos even though every
    # provider request is already prepaid and protected by the 3x economics
    # guard. Keep the per-request circuit breaker tight while giving the
    # global emergency ceilings enough capacity for a controlled public launch.
    per_request = production_compose_decimal(
        "GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD",
    )
    daily = production_compose_decimal(
        "GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD",
    )
    monthly = production_compose_decimal(
        "GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD",
    )
    safety_multiplier = production_compose_decimal(
        "GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER",
    )

    guarded_ten_minute_scribe_cost = Decimal("10") / Decimal("60") * Decimal("0.22") * safety_multiplier
    assert guarded_ten_minute_scribe_cost <= per_request
    assert per_request < guarded_ten_minute_scribe_cost * Decimal("1.10")
    assert daily / guarded_ten_minute_scribe_cost >= Decimal("200")
    assert monthly / guarded_ten_minute_scribe_cost >= Decimal("2000")
    assert monthly == daily * Decimal("10")


def test_production_verifier_requires_every_fail_closed_runtime_setting() -> None:
    verifier = deployment_text("verify-production.sh")

    for expected in (
        "GSP_APP_ENV=production",
        "APP_ENV=production",
        "GSP_MOCK_EXTERNAL_SERVICES=0",
        "GSP_ELEVENLABS_ENABLED=1",
        "GSP_ELEVENLABS_API_BASE=http://app-edge:8081/elevenlabs",
        "GSP_PAID_CREDITS_ENABLED=1",
        "GSP_CONSUMER_POLICY_APPROVED=1",
        "GSP_DURABLE_CONFIRMATION_CHANNEL_READY=1",
        "GSP_ADJUSTMENT_WORKFLOW_READY=1",
        "GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0",
        "GSP_STRIPE_API_BASE=http://app-edge:8081/stripe",
        "GSP_BILLING_ADMIN_USER_IDS=",
        "GSP_OBSERVABILITY_ENABLED=1",
        "GSP_OBSERVABILITY_RETENTION_HOURS=168",
        "GSP_OBSERVABILITY_PRESENCE_TTL_SECONDS=90",
        "STRIPE_SECRET_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
        "OPENAI_API_KEY=",
        "GROQ_API_KEY=",
        "GOOGLE_CLIENT_SECRET=",
        "GOOGLE_REDIRECT_URI=",
        "GSP_GOOGLE_OAUTH_CERTS_URL=http://app-edge:8081/oauth2/v1/certs",
        "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600",
        "GSP_BETA_LOGIN_PROMOTION_ENABLED=1",
        "GSP_MAX_VIDEO_DURATION_SECONDS=180",
        "GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=100",
        "GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=10",
        "GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0.05",
        "GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER=1.25",
        "GSP_MAX_ACTIVE_MEDIA_JOBS=5",
        "GSP_MEDIA_RENDER_SLOTS=2",
        "GSP_MEDIA_RENDER_THREADS_PER_SLOT=2",
        "GSP_MEDIA_EXTRACTION_SLOTS=1",
        "GSP_MEDIA_EXTRACTION_THREADS_PER_SLOT=1",
        "GSP_PROVIDER_TRANSCRIPTION_SLOTS=8",
        "GSP_UPLOAD_INACTIVITY_TIMEOUT_SECONDS=30",
        "GSP_WORKSPACE_RETENTION_HOURS=24",
        "GSP_STALE_JOB_RETENTION_HOURS=6",
        "GSP_ORPHAN_RETENTION_HOURS=1",
        "GSP_CLEANUP_INTERVAL_MINUTES=15",
        "GSP_STORAGE_MIN_FREE_MB=2048",
        "GSP_RETENTION_CLEANUP_ENABLED=1",
        "GSP_ERASURE_JOURNAL_DIR=/privacy-erasure-journal",
        "GSP_ERASURE_JOURNAL_RETENTION_DAYS=30",
    ):
        assert expected in verifier
    assert "GSP_ERASURE_JOURNAL_CONTINUITY_ID=" in verifier
    assert "{{.HostConfig.NanoCpus}}" in verifier
    assert '"3000000000"' in verifier
    assert "{{.HostConfig.Memory}}" in verifier
    assert '"3221225472"' in verifier
    assert "{{.HostConfig.PidsLimit}}" in verifier
    assert '"256"' in verifier
    assert "Retired GCS settings remain in the production env" in verifier
    assert "Backend container still exposes retired GCS settings" in verifier
    assert "settings.assert_paid_credits_configuration()" in verifier
    assert "settings.assert_download_grant_configuration()" in verifier
    assert "Production CORS requires an explicit origin allow-list" in verifier
    assert "Production CORS origins must be exact HTTPS origins" in verifier
    assert '"*" in origin' in verifier
    assert 'origin != f"https://{parsed.netloc}"' in verifier
    assert 'catalog.get("checkout_enabled") is not True' in verifier
    assert 'catalog.get("consumer_contract_status") != "approved"' in verifier
    assert "Running provider relay contract is unsafe" in verifier
    assert "Provider relay local default-deny checks failed" in verifier
    assert "assert_beta_login_promotion_contract" in verifier
    assert "campaign_max_claims IS DISTINCT FROM 20" in verifier
    assert "campaign_credit_amount IS DISTINCT FROM 30" in verifier
    assert "slot_number > campaign_claimed_count" in verifier
    assert "Beta login promotion contract failed after database migration." in verifier


def test_release_scripts_reject_retired_gcs_environment_keys(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    for script_name in ("deploy-production.sh", "verify-production.sh"):
        copy_release_script(script_name, deployment_root)

    for retired_assignment in (
        "GSP_GCS_BUCKET=obsolete-bucket",
        "GOOGLE_APPLICATION_CREDENTIALS=/obsolete/key.json",
    ):
        env_file = repository / ".env.production"
        env_file.write_text(f"{retired_assignment}\n", encoding="utf-8")
        environment = os.environ.copy()
        environment["SUBFRAME_ENV_FILE"] = str(env_file)

        for script_name in ("deploy-production.sh", "verify-production.sh"):
            completed = subprocess.run(
                [str(deployment_root / script_name)],
                check=False,
                capture_output=True,
                env=environment,
                text=True,
                timeout=10,
            )

            assert completed.returncode == 1
            assert "GCS settings" in completed.stderr


def test_release_blocks_legacy_gcs_reference_loss_before_migration() -> None:
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    retirement_verifier = deployment_text("verify-gcs-retirement.sh")

    # REGRESSION: the original retirement migration could destroy the only
    # remaining object-name evidence before provider cleanup was established.
    assert "assert_no_legacy_gcs_references()" in deploy_script
    assert "SELECT to_regclass('public.gcs_uploads') IS NOT NULL;" in deploy_script
    assert "SELECT count(*) FROM gcs_uploads;" in deploy_script
    assert "result_data ? 'source_gcs_object'" in deploy_script
    assert "Legacy GCS retirement preflight failed before database migration." in deploy_script
    assert deploy_script.index("if ! assert_no_legacy_gcs_references; then") < deploy_script.index(
        "if ! compose stop app-edge; then",
    )

    assert "assert_legacy_gcs_retirement_complete()" in verifier
    assert "to_regclass('public.gcs_uploads') IS NOT NULL" in verifier
    assert "result_data ? 'source_gcs_object'" in verifier
    assert "Legacy GCS retirement invariant failed after database migration." in verifier

    for script in (deploy_script, verifier):
        assert "verify-gcs-retirement.sh" in script
    assert "gcs-retirement-receipt" in retirement_verifier
    assert "gcs-retirement-evidence" in retirement_verifier
    assert "provider_inventory_zero" in retirement_verifier
    assert "never_configured_on_hetzner" in retirement_verifier
    assert "evidence_sha256" in retirement_verifier
    assert "credentials_revoked" in retirement_verifier
    assert "objects_after" in retirement_verifier
    assert "GCS retirement receipt is invalid" in retirement_verifier


def test_gcs_retirement_receipt_binds_exact_private_evidence(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    verifier = deployment_root / "verify-gcs-retirement.sh"
    shutil.copy2(DEPLOYMENT_ROOT / verifier.name, verifier)
    write_gcs_retirement_evidence(repository)
    runtime = repository / ".runtime"
    evidence = runtime / "gcs-retirement-evidence"

    valid = subprocess.run(
        [str(verifier)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert valid.returncode == 0, valid.stderr

    # REGRESSION: a receipt must not remain valid after its underlying audit
    # evidence is modified, substituted, or partially overwritten.
    evidence.write_text("tampered=true\n", encoding="utf-8")
    invalid = subprocess.run(
        [str(verifier)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert invalid.returncode == 1
    assert "evidence digest does not match" in invalid.stderr


def test_production_environment_defaults_do_not_prune_shared_cache() -> None:
    environment = deployment_text("subframe.env.example")
    compose = deployment_text("docker-compose.production.yml")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    frontend_dockerfile = (REPOSITORY_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert "SUBFRAME_HOSTNAME=gsubs.gr" in environment
    # REGRESSION: the browser and backend production ceilings both used 95 MB
    # while other runtime defaults silently allowed 1 GiB.
    assert "SUBFRAME_MAX_UPLOAD_MB=500" in environment
    assert "GSP_MAX_UPLOAD_MB=500" in environment
    assert "GSP_MAX_ACTIVE_MEDIA_JOBS=5" in environment
    assert "GSP_MEDIA_RENDER_SLOTS=2" in environment
    assert "GSP_MEDIA_RENDER_THREADS_PER_SLOT=2" in environment
    assert "GSP_MEDIA_EXTRACTION_SLOTS=1" in environment
    assert "GSP_MEDIA_EXTRACTION_THREADS_PER_SLOT=1" in environment
    assert "GSP_PROVIDER_TRANSCRIPTION_SLOTS=8" in environment
    assert "SUBFRAME_BACKEND_CPUS=3.0" in environment
    assert "SUBFRAME_BACKEND_MEMORY_LIMIT=3g" in environment
    assert "GSP_WORKSPACE_RETENTION_HOURS=24" in environment
    assert "GSP_STALE_JOB_RETENTION_HOURS=6" in environment
    assert "GSP_ORPHAN_RETENTION_HOURS=1" in environment
    assert "GSP_CLEANUP_INTERVAL_MINUTES=15" in environment
    assert "GSP_STORAGE_MIN_FREE_MB=2048" in environment
    assert "GSP_RETENTION_CLEANUP_ENABLED=1" in environment
    assert "GSP_ERASURE_JOURNAL_DIR=/privacy-erasure-journal" in environment
    assert "GSP_ERASURE_JOURNAL_RETENTION_DAYS=30" in environment
    assert not any(line.startswith("GSP_ERASURE_JOURNAL_CONTINUITY_ID=") for line in environment.splitlines())
    assert "GOOGLE_CLIENT_ID=replace-with-google-web-client-id" in environment
    assert "GOOGLE_CLIENT_SECRET=" in environment
    assert "GOOGLE_REDIRECT_URI=" in environment
    assert "GSP_GOOGLE_OAUTH_CERTS_URL=http://app-edge:8081/oauth2/v1/certs" in environment
    assert "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600" in environment
    assert "GSP_CONSUMER_POLICY_APPROVED=0" in environment
    assert "GSP_DURABLE_CONFIRMATION_CHANNEL_READY=0" in environment
    assert "GSP_ADJUSTMENT_WORKFLOW_READY=0" in environment
    assert "GSP_STRIPE_API_BASE=http://app-edge:8081/stripe" in environment
    assert "GSP_BILLING_ADMIN_USER_IDS=" in environment
    assert "GSP_OBSERVABILITY_ENABLED=0" in environment
    assert "GSP_OBSERVABILITY_RETENTION_HOURS=168" in environment
    assert "GSP_OBSERVABILITY_PRESENCE_TTL_SECONDS=90" in environment
    assert "GSP_OBSERVABILITY_ADMIN_USER_IDS=" in environment
    assert "GSP_MOCK_EXTERNAL_SERVICES=0" in environment
    assert "GSP_ELEVENLABS_ENABLED=1" in environment
    assert "GSP_ELEVENLABS_API_BASE=http://app-edge:8081/elevenlabs" in environment
    assert "ELEVENLABS_API_KEY=" in environment
    assert "GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=100" in environment
    assert "GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=10" in environment
    assert "GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0.05" in environment
    assert "google_client_id=$(env_value GOOGLE_CLIENT_ID)" in verifier
    assert "billing_admin_user_ids=$(env_value GSP_BILLING_ADMIN_USER_IDS)" not in verifier
    assert "observability_admin_user_ids=$(env_value GSP_OBSERVABILITY_ADMIN_USER_IDS)" in verifier
    assert "NEXT_PUBLIC_MAX_UPLOAD_MB: ${SUBFRAME_MAX_UPLOAD_MB:-500}" in compose
    assert "ARG NEXT_PUBLIC_MAX_UPLOAD_MB=500" in frontend_dockerfile
    assert "ARG NEXT_PUBLIC_TRANSCRIBE_PROVIDER=mock" in frontend_dockerfile
    assert "ARG NEXT_PUBLIC_TRANSCRIBE_MODE=standard" in frontend_dockerfile
    assert "GSP_ALLOWED_ORIGINS=https://gsubs.gr,https://www.gsubs.gr" in environment
    assert "GSP_TRUSTED_HOSTS=gsubs.gr,www.gsubs.gr,backend,localhost,127.0.0.1" in environment
    assert "subframe.mizai.gr" not in environment
    assert "SUBFRAME_PREVIEW_PORT=18090" in environment
    assert "SUBFRAME_PRUNE_BUILD_CACHE=0" in environment
    assert "SUBFRAME_BACKUP_AGE_IDENTITY_FILE=" in environment
    assert "SUBFRAME_OFF_SERVER_SHA256SUMS_SHA256" not in environment
    assert "${SUBFRAME_PRUNE_BUILD_CACHE:-0}" in deploy_script
    assert "status --porcelain --untracked-files=normal" in deploy_script
    assert "${SUBFRAME_ALLOW_SCHEMA_COMPATIBLE_ROLLBACK:-0}" in deploy_script
    assert "automatic rollback is disabled because the database schema may have advanced" in (deploy_script)
    assert "SUBFRAME_ALLOW_SCHEMA_COMPATIBLE_ROLLBACK must be 0 or 1" in deploy_script
    rollback_body = deploy_script.split("rollback() {", 1)[1].split("\n}\n", 1)[0]
    assert "compose stop app-edge" in rollback_body
    assert "compose up -d --no-build db backend frontend" in rollback_body
    assert "compose up -d --no-build;" not in rollback_body
    assert "the public application remains behind maintenance mode" in rollback_body


def test_erasure_journal_is_separate_and_reconciled_before_public_cutover() -> None:
    # REGRESSION: restoring database/app-data backups could resurrect a user
    # deletion because no durable record survived outside those restore units.
    compose = deployment_text("docker-compose.production.yml")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    privacy_caddyfile = deployment_text("ElevenLabsErasureCaddyfile")

    assert 'GSP_ERASURE_JOURNAL_DIR: "/privacy-erasure-journal"' in compose
    assert 'GSP_ERASURE_JOURNAL_RETENTION_DAYS: "30"' in compose
    assert 'GSP_ERASURE_JOURNAL_CONTINUITY_ID: "${SUBFRAME_PRIVACY_CONTINUITY_ID:-}"' in compose
    assert 'GSP_ERASURE_JOURNAL_ANCHOR_PATH: "/privacy-erasure-anchor/checkpoint.json"' in compose
    assert "- erasure_journal:/privacy-erasure-journal" in compose
    assert (
        "- ${SUBFRAME_ERASURE_ANCHOR_DIR:-../../.runtime/privacy-erasure-anchor}:/privacy-erasure-anchor"
    ) in compose
    assert "name: subframe-erasure-journal" in compose
    assert compose.count("erasure_journal:/privacy-erasure-journal") == 1
    assert compose.count("/privacy-erasure-anchor") == 3
    assert "app_logs" not in compose

    privacy_service = compose.split("  privacy-relay:", 1)[1].split("\nnetworks:", 1)[0]
    assert "privacy-maintenance" in privacy_service
    assert "ElevenLabsErasureCaddyfile" in privacy_service
    assert "provider_egress" in privacy_service
    assert "ports:" not in privacy_service
    assert "provider_egress:" in compose
    assert "internal: true" not in compose.split("  provider_egress:", 1)[1].split("\n\n", 1)[0]
    assert "method DELETE" in privacy_caddyfile
    assert "method POST" not in privacy_caddyfile
    assert "reverse_proxy https://api.elevenlabs.io" in privacy_caddyfile
    assert "path /elevenlabs/*" not in privacy_caddyfile
    assert "log {" not in privacy_caddyfile

    cutover = deploy_script.split('install -d -m 700 "$STATE_DIR"', 1)[1]
    app_edge_stop = cutover.index("compose stop app-edge")
    db_start = cutover.index("compose up -d db")
    continuity_gate = cutover.index("initialize_or_verify_privacy_continuity")
    core_start = cutover.index("compose up -d backend frontend")
    # The app worker delays its first scheduled pass, so cutover must retain
    # this synchronous retention gate while the public app is in maintenance.
    retention = cutover.index("python -m backend.cli run-retention")
    relay_start = cutover.index("compose up -d privacy-relay")
    reconcile = cutover.index("python -m backend.cli reconcile-erasures")
    relay_stop = cutover.index("compose stop privacy-relay")
    receipt = cutover.index('mv -f -- "$erasure_receipt_temp"')
    app_edge_start = cutover.index("compose up -d --no-deps --force-recreate app-edge")
    assert (
        app_edge_stop
        < db_start
        < continuity_gate
        < core_start
        < relay_start
        < retention
        < reconcile
        < relay_stop
        < receipt
        < app_edge_start
    )
    assert (
        cutover.count(
            "GSP_ELEVENLABS_API_BASE=http://privacy-relay:8082/elevenlabs",
        )
        == 2
    )
    assert "Local retention reconciliation failed" in deploy_script
    assert "the public application remains safely in maintenance mode" in deploy_script
    assert "A successful erasure reconciliation receipt is required" in verifier
    assert "reconciled_epoch" in verifier
    assert "backend_started_epoch" in verifier
    assert "subframe-erasure-journal|true" in verifier
    assert "Erasure journal retention must cover" in verifier
    assert "Temporary privacy relay must be stopped" in verifier
    assert "privacy-continuity-id" in deploy_script
    assert "privacy-continuity-id" in verifier
    assert "continuity-aware release" in deploy_script
    assert "Refusing to initialize a new erasure journal beside restored user data" in deploy_script
    assert "Refusing to initialize a new erasure journal beside restored media" in deploy_script
    assert "configured_erasure_journal().initialize()" in deploy_script
    assert deploy_script.count("configured_erasure_journal().initialize()") == 1
    assert deploy_script.count("configured_erasure_journal().read_all()") == 1
    assert 'INITIALIZE_CONTINUITY="$privacy_continuity_bootstrap"' in deploy_script
    assert "Live erasure journal continuity marker does not match" in verifier
    assert "configured_erasure_journal().read_all()" in verifier
    assert "Erasure-journal integrity validation failed" in verifier
    assert "10001:10001" in deploy_script
    assert "10001:10001" in verifier
    assert "Erasure-journal anchor directory permissions are unsafe" in verifier
    assert "Erasure-journal anchor directory ownership is unsafe" in verifier


def test_production_verifier_requires_payment_intent_write_access() -> None:
    verifier = deployment_text("verify-production.sh")
    permission_probe = "StripeSdkGateway().assert_payment_intent_write_access()"

    # REGRESSION: Checkout creation used to pass every release gate even when
    # the live restricted key could only read, not capture, PaymentIntents.
    assert permission_probe in verifier
    assert "Payment Intents Write access is unavailable" in verifier
    assert verifier.index(permission_probe) < verifier.index('health_json=""')


def test_production_verifier_multiline_python_is_dedented_and_compiles() -> None:
    opening = 'python -c \'import textwrap; exec(compile(textwrap.dedent("""\\'
    closing = '"""), "<gsubs-production-verifier>", "exec"))\''
    scripts = (
        DEPLOYMENT_ROOT / "lib" / "verify-contracts.sh",
        DEPLOYMENT_ROOT / "lib" / "verify-edge.sh",
    )

    discovered = 0
    compiled = 0
    for script in scripts:
        lines = script.read_text(encoding="utf-8").splitlines()
        index = 0
        while index < len(lines):
            line = lines[index]
            if "python -c '" not in line:
                index += 1
                continue
            discovered += 1
            assert opening in line, f"{script}:{index + 1} does not dedent inline Python"
            source_lines: list[str] = []
            index += 1
            while index < len(lines) and closing not in lines[index]:
                source_lines.append(lines[index])
                index += 1
            assert index < len(lines), f"{script} has an unterminated inline Python block"
            compile(
                textwrap.dedent("\n".join(source_lines)),
                f"{script}:{index + 1}",
                "exec",
            )
            compiled += 1
            index += 1

    assert discovered == 9
    assert compiled == discovered
