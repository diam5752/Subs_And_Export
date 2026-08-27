from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = REPOSITORY_ROOT / "deploy" / "hetzner"
SUBPROCESS_START_TIMEOUT_SECONDS = 15.0


def deployment_text(filename: str) -> str:
    return (DEPLOYMENT_ROOT / filename).read_text(encoding="utf-8")


def relay_validator_source(verifier: str) -> str:
    marker = 'docker exec "$app_edge_id" cat /etc/caddy/Caddyfile | docker exec -i "$backend_id" python -c \'\n'
    validator = verifier.split(marker, 1)[1].split("\n'; then", 1)[0]
    assert validator.startswith("from __future__ import annotations\n")
    return validator


def production_compose_decimal(name: str) -> Decimal:
    compose = deployment_text("docker-compose.production.yml")
    match = re.search(
        rf"^\s+{re.escape(name)}: \"([0-9]+(?:\.[0-9]+)?)\"$",
        compose,
        flags=re.MULTILINE,
    )
    if match is None:
        raise AssertionError(f"Missing production budget setting: {name}")
    return Decimal(match.group(1))


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def run_public_edge_verifier(
    tmp_path: Path,
    *,
    protocol: str = "2",
    status: str = "200",
    content_type: str = "application/json",
    alt_svc: str = "",
    curl_exit: str = "0",
) -> subprocess.CompletedProcess[str]:
    fake_curl = tmp_path / "fake-curl"
    write_executable(
        fake_curl,
        """#!/bin/sh
set -eu
header_path=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--dump-header" ]; then
    shift
    header_path=$1
  fi
  shift
done
[ -n "$header_path" ]
{
  printf 'HTTP/2 200\\r\\n'
  printf 'content-type: %s\\r\\n' "$FAKE_CONTENT_TYPE"
  if [ -n "$FAKE_ALT_SVC" ]; then
    printf 'alt-svc: %s\\r\\n' "$FAKE_ALT_SVC"
  fi
  printf '\\r\\n'
} > "$header_path"
if [ "$FAKE_CURL_EXIT" != 0 ]; then
  exit "$FAKE_CURL_EXIT"
fi
printf '%s|%s' "$FAKE_PROTOCOL" "$FAKE_STATUS"
""",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "CURL_BIN": str(fake_curl),
            "FAKE_PROTOCOL": protocol,
            "FAKE_STATUS": status,
            "FAKE_CONTENT_TYPE": content_type,
            "FAKE_ALT_SVC": alt_svc,
            "FAKE_CURL_EXIT": curl_exit,
        }
    )
    return subprocess.run(
        [str(DEPLOYMENT_ROOT / "verify-public-edge.sh")],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10,
    )


def install_passing_public_edge_fixture(
    deployment_root: Path,
    fake_bin: Path,
) -> None:
    shutil.copy2(DEPLOYMENT_ROOT / "verify-public-edge.sh", deployment_root)
    write_executable(
        fake_bin / "curl",
        """#!/bin/sh
set -eu
header_path=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--dump-header" ]; then
    shift
    header_path=$1
  fi
  shift
done
[ -n "$header_path" ]
printf 'HTTP/2 200\\r\\ncontent-type: application/json\\r\\n\\r\\n' > "$header_path"
printf '2|200'
""",
    )


def write_gcs_retirement_evidence(repository: Path) -> None:
    runtime = repository / ".runtime"
    runtime.mkdir(exist_ok=True)
    evidence = runtime / "gcs-retirement-evidence"
    evidence.write_text(
        "tracked_hetzner_gcs_configuration=never-enabled\nlegacy_database_references=0\n",
        encoding="utf-8",
    )
    evidence.chmod(0o600)
    evidence_digest = hashlib.sha256(evidence.read_bytes()).hexdigest()
    receipt = runtime / "gcs-retirement-receipt"
    receipt.write_text(
        "\n".join(
            (
                "retired=true",
                "scope=hetzner-production-whole-storage",
                "retirement_basis=never_configured_on_hetzner",
                "retirement_base_sha=d0d47ac774995d7eb06f1942c7e5eeacff69b1e1",
                "objects_after=0",
                "credentials_revoked=true",
                "bucket_identity_sha256=none",
                f"evidence_sha256={evidence_digest}",
                "verified_at_utc=20260805T120000Z",
                "",
            ),
        ),
        encoding="utf-8",
    )
    receipt.chmod(0o600)


def backup_verifier_fixture(tmp_path: Path) -> dict[str, Path]:
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    shutil.copy2(DEPLOYMENT_ROOT / "verify-backup.sh", deployment_root)
    (deployment_root / "docker-compose.production.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )

    release_sha = "a" * 40
    env_file = repository / ".env.production"
    env_file.write_text(
        (f"POSTGRES_USER=subframe\nSUBFRAME_RELEASE_SHA={release_sha}\nSUBFRAME_BACKUP_RETENTION_DAYS=14\n"),
        encoding="utf-8",
    )
    identity_file = tmp_path / "age-identity.txt"
    identity_file.write_text("AGE-SECRET-KEY-TEST\n", encoding="utf-8")
    docker_root = tmp_path / "docker-root"
    docker_root.mkdir()

    backup_id = "20260726T120000Z"
    server_backup = tmp_path / "server-backups" / backup_id
    independent_backup = tmp_path / "independent-backups" / backup_id
    server_backup.mkdir(parents=True)
    independent_backup.mkdir(parents=True)
    (server_backup / "postgres.dump.age").write_bytes(b"database archive")
    (server_backup / "app-data.tgz.age").write_bytes(b"app archive")
    (server_backup / "manifest.txt").write_text(
        "\n".join(
            (
                f"created_at_utc={backup_id}",
                f"release_sha={release_sha}",
                "encrypted=true",
                "retention_days=14",
                "database_size_bytes=1024",
                "app_data_size_bytes=2048",
                "",
            )
        ),
        encoding="utf-8",
    )
    checksums = []
    for filename in ("postgres.dump.age", "app-data.tgz.age", "manifest.txt"):
        digest = hashlib.sha256((server_backup / filename).read_bytes()).hexdigest()
        checksums.append(f"{digest}  {filename}")
    (server_backup / "SHA256SUMS").write_text(
        "\n".join((*checksums, "")),
        encoding="utf-8",
    )
    for filename in (
        "postgres.dump.age",
        "app-data.tgz.age",
        "manifest.txt",
        "SHA256SUMS",
    ):
        shutil.copy2(server_backup / filename, independent_backup / filename)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    command_log = tmp_path / "docker-commands.log"
    write_executable(
        fake_bin / "git",
        """#!/bin/sh
case "$*" in
  *"rev-parse HEAD"*) printf '%s\\n' "$FAKE_RELEASE_SHA" ;;
  *) exit 1 ;;
esac
""",
    )
    write_executable(
        fake_bin / "stat",
        """#!/bin/sh
last_argument=
for argument
do
  last_argument=$argument
done
if [ "$last_argument" = "$FAKE_INDEPENDENT_BACKUP_DIR" ]; then
  printf '222\\n'
else
  printf '111\\n'
fi
""",
    )
    write_executable(
        fake_bin / "df",
        """#!/bin/sh
printf 'Filesystem 1024-blocks Used Available Capacity Mounted-on\\n'
printf 'fake 99999999 1 %s 1%% /fake\\n' "$FAKE_AVAILABLE_KIB"
""",
    )
    write_executable(
        fake_bin / "findmnt",
        """#!/bin/sh
case "${FAKE_FINDMNT_MODE:-read-only}" in
  read-only) printf 'ro,nosuid,nodev,relatime\\n' ;;
  writable) printf 'rw,nosuid,nodev,relatime\\n' ;;
  missing) exit 1 ;;
  unknown) printf 'nosuid,nodev,relatime\\n' ;;
  *) exit 2 ;;
esac
""",
    )
    write_executable(
        fake_bin / "date",
        """#!/bin/sh
case "$*" in
  *"days ago"*) printf '%s\n' "${FAKE_RETENTION_CUTOFF:-20260722T120000Z}" ;;
  *) printf '20260805T120000Z\n' ;;
esac
""",
    )
    write_executable(
        fake_bin / "age",
        """#!/bin/sh
if [ -n "${FAKE_AGE_MARKER:-}" ]; then
  : > "$FAKE_AGE_MARKER"
  exec sleep 30
fi
encrypted_file=
for argument
do
  encrypted_file=$argument
done
cat "$encrypted_file"
""",
    )
    write_executable(
        fake_bin / "tar",
        """#!/bin/sh
cat >/dev/null
""",
    )
    write_executable(
        fake_bin / "docker",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_COMMAND_LOG"
case " $* " in
  *" info --format "*)
    printf '%s\\n' "$FAKE_DOCKER_ROOT"
    ;;
  *" volume inspect "*)
    exit 1
    ;;
  *" volume create "*|*" volume rm "*)
    ;;
  *" pg_restore --list "*|*" pg_restore --username "*)
    cat >/dev/null
    ;;
  *"SELECT 1;"*)
    printf '1\\n'
    ;;
  *"pg_database"*)
    ;;
  *" run "*"-i "*)
    cat >/dev/null
    ;;
esac
""",
    )

    return {
        "repository": repository,
        "verifier": deployment_root / "verify-backup.sh",
        "env_file": env_file,
        "identity_file": identity_file,
        "docker_root": docker_root,
        "server_backup": server_backup,
        "independent_backup": independent_backup,
        "fake_bin": fake_bin,
        "command_log": command_log,
    }


def backup_verifier_environment(
    fixture: dict[str, Path],
    *,
    available_kib: int,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fixture['fake_bin']}:{environment['PATH']}",
            "SUBFRAME_ENV_FILE": str(fixture["env_file"]),
            "SUBFRAME_BACKUP_AGE_IDENTITY_FILE": str(fixture["identity_file"]),
            "FAKE_RELEASE_SHA": "a" * 40,
            "FAKE_INDEPENDENT_BACKUP_DIR": str(fixture["independent_backup"]),
            "FAKE_DOCKER_ROOT": str(fixture["docker_root"]),
            "FAKE_AVAILABLE_KIB": str(available_kib),
            "FAKE_COMMAND_LOG": str(fixture["command_log"]),
            "FAKE_FINDMNT_MODE": "read-only",
            "FAKE_RETENTION_CUTOFF": "20260722T120000Z",
        }
    )
    return environment


def test_production_compose_enables_reviewed_paid_credits_and_budgeted_scribe() -> None:
    compose = deployment_text("docker-compose.production.yml")

    assert '"127.0.0.1:${SUBFRAME_PREVIEW_PORT:-18090}:8080"' in compose
    assert "GSP_APP_ENV: production" in compose
    assert "APP_ENV: production" in compose
    assert 'GSP_MOCK_EXTERNAL_SERVICES: "0"' in compose
    assert 'GSP_ELEVENLABS_ENABLED: "1"' in compose
    assert 'GSP_ELEVENLABS_API_BASE: "http://edge:8081/elevenlabs"' in compose
    assert 'GSP_PAID_CREDITS_ENABLED: "1"' in compose
    assert 'GSP_CONSUMER_POLICY_APPROVED: "1"' in compose
    assert 'GSP_DURABLE_CONFIRMATION_CHANNEL_READY: "1"' in compose
    assert 'GSP_ADJUSTMENT_WORKFLOW_READY: "1"' in compose
    assert 'GSP_STRIPE_AUTOMATIC_TAX_ENABLED: "0"' in compose
    assert 'GSP_STRIPE_API_BASE: "http://edge:8081/stripe"' in compose
    assert 'GSP_STRIPE_RESTRICTED_KEY: "${GSP_STRIPE_RESTRICTED_KEY:-}"' in compose
    assert 'GSP_STRIPE_WEBHOOK_SECRET: "${GSP_STRIPE_WEBHOOK_SECRET:-}"' in compose
    assert 'GSP_STRIPE_PRICE_STARTER: "${GSP_STRIPE_PRICE_STARTER:-}"' in compose
    assert 'GSP_STRIPE_PRICE_CORE: "${GSP_STRIPE_PRICE_CORE:-}"' in compose
    assert 'GSP_STRIPE_PRICE_PRO: "${GSP_STRIPE_PRICE_PRO:-}"' in compose
    assert 'GSP_BILLING_ADMIN_USER_IDS: ""' in compose
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
    assert 'GSP_GOOGLE_OAUTH_CERTS_URL: "http://edge:8081/oauth2/v1/certs"' in compose
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
    anchor_preparation = deploy_script.split(
        "prepare_erasure_anchor_directory() {", 1
    )[1].split("\n}\n\ninitialize_or_verify_privacy_continuity()", 1)[0]

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
    assert 'install -d -m 700 -o 10001 -g 10001' not in anchor_preparation
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
        "GSP_ELEVENLABS_API_BASE=http://edge:8081/elevenlabs",
        "GSP_PAID_CREDITS_ENABLED=1",
        "GSP_CONSUMER_POLICY_APPROVED=1",
        "GSP_DURABLE_CONFIRMATION_CHANNEL_READY=1",
        "GSP_ADJUSTMENT_WORKFLOW_READY=1",
        "GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0",
        "GSP_STRIPE_API_BASE=http://edge:8081/stripe",
        "GSP_BILLING_ADMIN_USER_IDS=",
        "STRIPE_SECRET_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
        "OPENAI_API_KEY=",
        "GROQ_API_KEY=",
        "GOOGLE_CLIENT_SECRET=",
        "GOOGLE_REDIRECT_URI=",
        "GSP_GOOGLE_OAUTH_CERTS_URL=http://edge:8081/oauth2/v1/certs",
        "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600",
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


def test_release_scripts_reject_retired_gcs_environment_keys(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    for script_name in ("deploy-production.sh", "verify-production.sh"):
        shutil.copy2(DEPLOYMENT_ROOT / script_name, deployment_root)

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
    assert "GSP_GOOGLE_OAUTH_CERTS_URL=http://edge:8081/oauth2/v1/certs" in environment
    assert "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600" in environment
    assert "GSP_CONSUMER_POLICY_APPROVED=0" in environment
    assert "GSP_DURABLE_CONFIRMATION_CHANNEL_READY=0" in environment
    assert "GSP_ADJUSTMENT_WORKFLOW_READY=0" in environment
    assert "GSP_STRIPE_API_BASE=http://edge:8081/stripe" in environment
    assert "GSP_BILLING_ADMIN_USER_IDS=" in environment
    assert "GSP_MOCK_EXTERNAL_SERVICES=0" in environment
    assert "GSP_ELEVENLABS_ENABLED=1" in environment
    assert "GSP_ELEVENLABS_API_BASE=http://edge:8081/elevenlabs" in environment
    assert "ELEVENLABS_API_KEY=" in environment
    assert "GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=100" in environment
    assert "GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=10" in environment
    assert "GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0.05" in environment
    assert "google_client_id=$(env_value GOOGLE_CLIENT_ID)" in verifier
    assert "billing_admin_user_ids=$(env_value GSP_BILLING_ADMIN_USER_IDS)" not in verifier
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


def test_schema_changing_deploy_requires_a_matching_restore_drill_receipt() -> None:
    deploy_script = deployment_text("deploy-production.sh")

    assert "backend/alembic/versions" in deploy_script
    assert "last-backup-restore-drill" in deploy_script
    assert "target_release_sha" in deploy_script
    assert "receipt_value backup_release_sha" in deploy_script
    assert "receipt_value backup_created_at_utc" in deploy_script
    assert "receipt_value verified_at_utc" in deploy_script
    assert "receipt_value restore_drill" in deploy_script
    assert "receipt_value independent_backup_copy_verified" in deploy_script
    assert "receipt_value database_removed_before_app_restore" in deploy_script
    assert "receipt_value sequential_restore" in deploy_script
    assert "receipt_value restore_size_multiplier" in deploy_script
    assert "receipt_value restore_fixed_reserve_bytes" in deploy_script
    assert "receipt_value schema_rollback_evidence" in deploy_script
    assert "receipt_value app_data_authoritative" in deploy_script
    assert "receipt_timestamp_epoch" in deploy_script
    assert 'date -u -d "$iso_timestamp" +%s' in deploy_script
    assert "max_restore_drill_age_seconds=86400" in deploy_script
    assert "Restore-drill receipt timestamps cannot be in the future" in deploy_script
    assert "Restore-drill receipt timestamps are not ordered" in deploy_script
    assert "Restore-drill receipt is older than 24 hours" in deploy_script
    assert "Schema-changing releases require a successful backup restore drill" in deploy_script


def legacy_journal_transition_fixture(tmp_path: Path) -> dict[str, Path | str]:
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    shutil.copy2(DEPLOYMENT_ROOT / "deploy-production.sh", deployment_root)
    (deployment_root / "docker-compose.production.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )

    previous_sha = "a" * 40
    release_sha = "b" * 40
    env_file = repository / ".env.production"
    env_file.write_text(
        f"SUBFRAME_RELEASE_SHA={release_sha}\n",
        encoding="utf-8",
    )
    state_dir = repository / ".runtime"
    state_dir.mkdir()
    (state_dir / "last-successful-release").write_text(
        f"{previous_sha}\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    install_passing_public_edge_fixture(deployment_root, fake_bin)
    docker_log = tmp_path / "docker.log"
    write_executable(
        fake_bin / "git",
        """#!/bin/sh
case "$*" in
  *"status --porcelain --untracked-files=normal"*) ;;
  *"rev-parse HEAD"*) printf '%s\n' "$FAKE_RELEASE_SHA" ;;
  *"cat-file -e"*) ;;
  *"show "*) printf 'services:\n  backend:\n    environment: {}\n' ;;
  *"diff --quiet"*) exit 1 ;;
  *) exit 1 ;;
esac
""",
    )
    write_executable(
        fake_bin / "docker",
        """#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
case "$*" in
  "inspect --format {{.Id}} subframe-edge-1") printf '%s\n' "$FAKE_EDGE_ID" ;;
  "inspect --format {{.Id}} subframe-backend-1") printf '%s\n' "$FAKE_BACKEND_ID" ;;
  "inspect --format {{.State.Running}} $FAKE_EDGE_ID") printf '%s\n' "${FAKE_EDGE_RUNNING:-false}" ;;
  "inspect --format {{.State.Running}} $FAKE_BACKEND_ID") printf '%s\n' "${FAKE_BACKEND_RUNNING:-false}" ;;
  "inspect --format {{.Id}}|{{.State.Running}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|{{.RestartCount}} $FAKE_EDGE_ID")
    printf '%s|%s|2026-08-05T11:00:00Z|2026-08-05T12:00:00Z|0\n' \
      "$FAKE_EDGE_ID" "${FAKE_EDGE_RUNNING:-false}"
    ;;
  "inspect --format {{.Id}}|{{.State.Running}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|{{.RestartCount}} $FAKE_BACKEND_ID")
    printf '%s|%s|2026-08-05T11:00:00Z|2026-08-05T12:00:00Z|0\n' \
      "$FAKE_BACKEND_ID" "${FAKE_BACKEND_RUNNING:-false}"
    ;;
esac
""",
    )
    write_executable(
        fake_bin / "date",
        """#!/bin/sh
case "$*" in
  "-u +%Y%m%dT%H%M%SZ") printf '20260805T120000Z\n' ;;
  "-u -d 2026-08-05T11:59:59Z +%s") printf '1785931199\n' ;;
  "-u -d @1785931199 +%Y%m%dT%H%M%SZ") printf '20260805T115959Z\n' ;;
  "-u -d 2026-08-05T12:00:00Z +%s") printf '1785931200\n' ;;
  "-u -d @1785931200 +%Y%m%dT%H%M%SZ") printf '20260805T120000Z\n' ;;
  "-u -d 2026-08-05T12:00:01Z +%s") printf '1785931201\n' ;;
  "-u -d @1785931201 +%Y%m%dT%H%M%SZ") printf '20260805T120001Z\n' ;;
  "-u +%s") printf '1785934800\n' ;;
  *) exit 1 ;;
esac
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "SUBFRAME_ENV_FILE": str(env_file),
            "FAKE_RELEASE_SHA": release_sha,
            "FAKE_EDGE_ID": "c" * 64,
            "FAKE_BACKEND_ID": "e" * 64,
            "FAKE_DOCKER_LOG": str(docker_log),
        },
    )
    return {
        "repository": repository,
        "script": deployment_root / "deploy-production.sh",
        "state_dir": state_dir,
        "docker_log": docker_log,
        "environment": json.dumps(environment),
        "previous_sha": previous_sha,
        "release_sha": release_sha,
    }


def run_legacy_journal_transition_fixture(
    fixture: dict[str, Path | str],
    *,
    edge_running: bool = False,
    backend_running: bool = False,
) -> subprocess.CompletedProcess[str]:
    environment = json.loads(str(fixture["environment"]))
    if edge_running:
        environment["FAKE_EDGE_RUNNING"] = "true"
    if backend_running:
        environment["FAKE_BACKEND_RUNNING"] = "true"
    return subprocess.run(
        [str(fixture["script"])],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )


def test_first_legacy_journal_transition_quiesces_writers_and_requires_fresh_backup(
    tmp_path: Path,
) -> None:
    # REGRESSION: the old flow could accept a backup created before an account
    # deletion and initialize the first journal after that deletion.
    fixture = legacy_journal_transition_fixture(tmp_path)

    completed = run_legacy_journal_transition_fixture(fixture)

    assert completed.returncode == 1
    marker = Path(fixture["state_dir"]) / "legacy-journal-bootstrap-transition"
    assert marker.is_file()
    assert marker.stat().st_mode & 0o777 == 0o600
    marker_text = marker.read_text(encoding="utf-8")
    assert "schema_version=2" in marker_text
    assert f"previous_release_sha={fixture['previous_sha']}" in marker_text
    assert f"target_release_sha={fixture['release_sha']}" in marker_text
    assert "edge_container_id=" in marker_text
    assert "backend_container_id=" in marker_text
    assert re.search(r"^services_stopped_at_utc=[0-9]{8}T[0-9]{6}Z$", marker_text, re.MULTILINE)
    assert "Create a fresh backup" in completed.stderr
    docker_commands = Path(fixture["docker_log"]).read_text(encoding="utf-8")
    assert "stop edge app-edge backend" in docker_commands
    assert " build " not in f" {docker_commands} "


def test_legacy_journal_transition_rejects_tampering_and_restarted_writers(
    tmp_path: Path,
) -> None:
    fixture = legacy_journal_transition_fixture(tmp_path)
    first_run = run_legacy_journal_transition_fixture(fixture)
    assert first_run.returncode == 1
    marker = Path(fixture["state_dir"]) / "legacy-journal-bootstrap-transition"
    original_marker = marker.read_text(encoding="utf-8")

    marker.write_text(
        original_marker.replace(str(fixture["release_sha"]), "d" * 40),
        encoding="utf-8",
    )
    marker.chmod(0o600)
    docker_log = Path(fixture["docker_log"])
    docker_log.write_text("", encoding="utf-8")
    tampered = run_legacy_journal_transition_fixture(fixture)
    assert tampered.returncode == 1
    assert "marker is malformed or belongs to another release" in tampered.stderr
    assert "transition validation failed; edge and backend remain closed" in tampered.stderr
    tampered_commands = docker_log.read_text(encoding="utf-8")
    assert "stop edge app-edge backend" in tampered_commands
    assert "stop subframe-edge-1 subframe-app-edge-1 subframe-backend-1" in tampered_commands
    assert "ps --status running -q edge app-edge backend" in tampered_commands

    marker.write_text(original_marker, encoding="utf-8")
    marker.chmod(0o600)
    docker_log.write_text("", encoding="utf-8")
    restarted = run_legacy_journal_transition_fixture(fixture, edge_running=True)
    assert restarted.returncode == 1
    assert "edge or backend restarted after the transition marker" in restarted.stderr
    restarted_commands = docker_log.read_text(encoding="utf-8")
    assert "stop edge app-edge backend" in restarted_commands
    assert "stop subframe-edge-1 subframe-app-edge-1 subframe-backend-1" in restarted_commands
    assert "ps --status running -q edge app-edge backend" in restarted_commands

    docker_log.write_text("", encoding="utf-8")
    backend_restarted = run_legacy_journal_transition_fixture(
        fixture,
        backend_running=True,
    )
    assert backend_restarted.returncode == 1
    assert "edge or backend restarted after the transition marker" in backend_restarted.stderr
    backend_commands = docker_log.read_text(encoding="utf-8")
    assert "stop edge app-edge backend" in backend_commands
    assert "stop subframe-edge-1 subframe-app-edge-1 subframe-backend-1" in backend_commands
    assert "ps --status running -q edge app-edge backend" in backend_commands


def test_legacy_journal_transition_rejects_a_pre_quiescence_backup(
    tmp_path: Path,
) -> None:
    fixture = legacy_journal_transition_fixture(tmp_path)
    first_run = run_legacy_journal_transition_fixture(fixture)
    assert first_run.returncode == 1
    receipt = Path(fixture["state_dir"]) / "last-backup-restore-drill"
    receipt.write_text(
        "\n".join(
            (
                f"backup_release_sha={fixture['release_sha']}",
                "backup_created_at_utc=20260805T115959Z",
                f"target_release_sha={fixture['release_sha']}",
                "verified_at_utc=20260805T120001Z",
                "restore_drill=true",
                "independent_backup_copy_verified=true",
                "ciphertext_checksums=true",
                "age_decrypt=true",
                "pg_restore_archive=true",
                "tar_archive=true",
                "database_restore=true",
                "database_removed_before_app_restore=true",
                "volume_restore=true",
                "sequential_restore=true",
                "restore_size_multiplier=2",
                "restore_fixed_reserve_bytes=10737418240",
                "schema_rollback_evidence=postgres_dump",
                "app_data_authoritative=false",
                "cleanup=true",
                "",
            ),
        ),
        encoding="utf-8",
    )
    receipt.chmod(0o600)

    second_run = run_legacy_journal_transition_fixture(fixture)

    assert second_run.returncode == 1
    assert "backup must be created after the legacy edge is quiesced" in second_run.stderr


def test_legacy_journal_transition_requires_post_quiescence_restore_receipt() -> None:
    deploy_script = deployment_text("deploy-production.sh")
    runbook = deployment_text("README.md")

    assert 'TRANSITION_STATE_FILE="$STATE_DIR/legacy-journal-bootstrap-transition"' in deploy_script
    assert 'backup_created_epoch" -le "$transition_stopped_epoch' in deploy_script
    assert "backup must be created after the legacy edge is quiesced" in deploy_script
    assert "first invocation" in runbook
    assert "second invocation" in runbook
    assert "legacy-journal-bootstrap-transition" in runbook
    assert "edge and backend" in runbook


def test_deploy_and_verifier_reject_open_stripe_rows_without_consumer_contract_evidence() -> None:
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    function_name = "assert_no_open_stripe_purchases_without_consumer_contract"
    required_sql = (
        "BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;",
        "FROM credit_purchases",
        "provider = 'stripe'",
        "fulfilled_at IS NULL",
        "status NOT IN ('expired', 'failed')",
        "jsonb_typeof((snapshot::jsonb)->'consumer_contract')",
        "IS DISTINCT FROM 'object'",
        "consumer_contract_sha256",
        "!~ '^[0-9a-f]{64}$'",
        "RAISE EXCEPTION",
    )

    for script in (deploy_script, verifier):
        assert f"{function_name}()" in script
        assert "psql -X --no-password -v ON_ERROR_STOP=1" in script
        assert "compose exec -T db" in script
        for sql_fragment in required_sql:
            assert sql_fragment in script
    deploy_sql = deploy_script.split("<<'SQL'\n", 1)[1].split("\nSQL\n", 1)[0]
    verifier_sql = verifier.split("<<'SQL'\n", 1)[1].split("\nSQL\n", 1)[0]
    assert verifier_sql == deploy_sql

    deploy_preflight = deploy_script.index(f"if ! {function_name}; then")
    deploy_cutover = deploy_script.index("compose up -d db")
    assert deploy_preflight < deploy_cutover
    assert "Open Stripe purchase preflight failed before database migration." in deploy_script

    alembic_head_check = verifier.index("alembic current --check-heads")
    verifier_preflight = verifier.index(f"if ! {function_name}; then")
    assert alembic_head_check < verifier_preflight
    assert "Open Stripe purchase invariant failed after database migration." in verifier


def test_deploy_aborts_before_cutover_when_current_database_preflight_is_unavailable(
    tmp_path: Path,
) -> None:
    """REGRESSION: the first consumer-contract migration could start without inspecting open payments."""
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    shutil.copy2(DEPLOYMENT_ROOT / "deploy-production.sh", deployment_root)
    shutil.copy2(DEPLOYMENT_ROOT / "verify-gcs-retirement.sh", deployment_root)
    (deployment_root / "docker-compose.production.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )
    write_executable(
        deployment_root / "verify-production.sh",
        "#!/bin/sh\nexit 0\n",
    )

    old_release_sha = "d" * 40
    new_release_sha = "e" * 40
    env_file = repository / ".env.production"
    env_file.write_text(
        f"SUBFRAME_RELEASE_SHA={new_release_sha}\n",
        encoding="utf-8",
    )
    state_dir = repository / ".runtime"
    state_dir.mkdir()
    state_file = state_dir / "last-successful-release"
    state_file.write_text(f"{old_release_sha}\n", encoding="utf-8")
    (state_dir / "privacy-continuity-id").write_text(
        f"{'1' * 64}\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    install_passing_public_edge_fixture(deployment_root, fake_bin)
    command_log = tmp_path / "docker-commands.log"
    write_executable(
        fake_bin / "git",
        """#!/bin/sh
case "$*" in
  *"status --porcelain --untracked-files=normal"*) ;;
  *"rev-parse HEAD"*) printf '%s\\n' "$FAKE_NEW_RELEASE_SHA" ;;
  *"cat-file -e"*) ;;
  *"diff --quiet"*) ;;
  *) exit 1 ;;
esac
""",
    )
    write_executable(
        fake_bin / "docker",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_COMMAND_LOG"
case "$*" in
  *"compose "*"exec -T db"*) exit 1 ;;
esac
if [ "${1:-}" = "inspect" ]; then
  printf 'healthy\\n'
fi
""",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "SUBFRAME_ENV_FILE": str(env_file),
            "FAKE_NEW_RELEASE_SHA": new_release_sha,
            "FAKE_COMMAND_LOG": str(command_log),
        }
    )

    completed = subprocess.run(
        [str(deployment_root / "deploy-production.sh")],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert state_file.read_text(encoding="utf-8").strip() == old_release_sha
    assert "preflight failed before database migration" in completed.stderr
    commands = command_log.read_text(encoding="utf-8")
    assert "exec -T db" in commands
    assert "up -d db" not in commands


def test_backup_verifier_authenticates_and_validates_every_archive() -> None:
    backup_script = deployment_text("backup.sh")
    verifier = deployment_text("verify-backup.sh")

    assert "sha256sums_sha256=" in backup_script
    assert "cd /data && tar -czf - ." in backup_script
    assert "INDEPENDENT_BACKUP_DIRECTORY" in verifier
    assert "Independent backup copy must be mounted on a different filesystem device" in verifier
    assert "Independent backup copy differs from server file" in verifier
    assert 'age --decrypt --identity "$IDENTITY_FILE"' in verifier
    assert "pg_restore --list" in verifier
    assert "tar -tzf -" in verifier
    assert "postgres.dump.age" in verifier
    assert "app-data.tgz.age" in verifier
    assert "manifest.txt" in verifier
    assert 'manifest_value "$BACKUP_DIR/manifest.txt" retention_days' in verifier
    assert "Backup is older than its configured retention period" in verifier


def test_backup_verifier_rejects_an_expired_backup(tmp_path: Path) -> None:
    # REGRESSION: a valid encrypted copy could previously be restored after its
    # declared GDPR backup-retention window had elapsed.
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )
    environment["FAKE_RETENTION_CUTOFF"] = "20260727T000000Z"

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "older than its configured retention period" in completed.stderr


def test_backup_verifier_requires_a_read_only_independent_mount() -> None:
    verifier = deployment_text("verify-backup.sh")

    assert 'findmnt --noheadings --raw --target "$1" --output OPTIONS' in verifier
    assert "Independent backup directory is on a writable mount" in verifier
    assert "Independent backup mount options do not prove read-only access" in verifier
    assert "server_backup_copy_device=$server_device" in verifier
    assert "independent_backup_copy_device=$independent_device" in verifier
    assert "independent_backup_copy_distinct_filesystem=true" in verifier
    assert "independent_backup_copy_mount_detected=true" in verifier
    assert "independent_backup_copy_mount_read_only=true" in verifier


def test_backup_verifier_rejects_a_copy_on_the_same_filesystem(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )
    environment["FAKE_INDEPENDENT_BACKUP_DIR"] = "/not-the-independent-path"

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "must be mounted on a different filesystem device" in completed.stderr


def test_backup_verifier_rejects_a_writable_independent_mount(
    tmp_path: Path,
) -> None:
    """REGRESSION: a distinct filesystem could still be writable during verification."""
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )
    environment["FAKE_FINDMNT_MODE"] = "writable"

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "Independent backup directory is on a writable mount" in completed.stderr


def test_backup_verifier_rejects_an_absent_independent_mount(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )
    environment["FAKE_FINDMNT_MODE"] = "missing"

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "Could not resolve the independent backup mount with findmnt" in completed.stderr


def test_backup_verifier_rejects_unknown_independent_mount_options(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )
    environment["FAKE_FINDMNT_MODE"] = "unknown"

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "Independent backup mount options do not prove read-only access" in completed.stderr


def test_backup_verifier_rejects_a_self_consistent_but_different_copy(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    independent_backup = fixture["independent_backup"]
    (independent_backup / "postgres.dump.age").write_bytes(b"different archive")
    checksums = []
    for filename in ("postgres.dump.age", "app-data.tgz.age", "manifest.txt"):
        digest = hashlib.sha256((independent_backup / filename).read_bytes()).hexdigest()
        checksums.append(f"{digest}  {filename}")
    (independent_backup / "SHA256SUMS").write_text(
        "\n".join((*checksums, "")),
        encoding="utf-8",
    )
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            str(fixture["server_backup"]),
            str(independent_backup),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "Independent backup copy differs from server file" in completed.stderr


def test_backup_root_preflight_rejects_broad_or_ambiguous_targets(
    tmp_path: Path,
) -> None:
    """REGRESSION: an env-controlled root could make retention recursively delete broadly."""
    env_file = tmp_path / "production.env"
    env_file.write_text(
        "\n".join(
            (
                "SUBFRAME_BACKUP_RETENTION_DAYS=14",
                "SUBFRAME_BACKUP_AGE_RECIPIENT=age1test",
                "POSTGRES_USER=subframe",
                "POSTGRES_DB=subframe",
            )
        ),
        encoding="utf-8",
    )
    dedicated_parent = tmp_path / "dedicated-parent"
    dedicated_parent.mkdir()
    dedicated_root = dedicated_parent / "production"
    dedicated_root.mkdir()
    symlink_root = tmp_path / "backup-root-link"
    symlink_root.symlink_to(dedicated_root, target_is_directory=True)

    unsafe_roots = (
        "",
        "relative/backups",
        "/",
        str(REPOSITORY_ROOT),
        str(Path.home()),
        str(symlink_root),
        str(tmp_path / "missing-parent" / "production"),
        str(dedicated_parent / ".." / dedicated_parent.name / "production"),
    )
    for unsafe_root in unsafe_roots:
        environment = os.environ.copy()
        environment["SUBFRAME_ENV_FILE"] = str(env_file)
        environment["SUBFRAME_BACKUP_ROOT"] = unsafe_root
        completed = subprocess.run(
            [str(DEPLOYMENT_ROOT / "backup.sh")],
            check=False,
            capture_output=True,
            env=environment,
            text=True,
        )

        assert completed.returncode == 1, unsafe_root
        assert "Unsafe SUBFRAME_BACKUP_ROOT" in completed.stderr


def test_backup_retention_prunes_only_exact_complete_backup_directories() -> None:
    backup_script = deployment_text("backup.sh")
    prune_script = deployment_text("prune-backups.sh")

    assert 'prune-backups.sh" "$BACKUP_ROOT" "$RETENTION_DAYS"' in backup_script
    assert 'prune_backup_directory "$candidate"' in prune_script
    assert "actual_candidate_parent" in prune_script
    assert "created_at_utc=$backup_name" in prune_script
    assert 'rm -f -- "$candidate/postgres.dump.age"' in prune_script
    assert 'rmdir -- "$candidate"' in prune_script
    assert "-exec rm -rf" not in prune_script
    assert "rm -rf" not in prune_script


def test_backup_pruner_applies_the_same_exact_policy_to_any_backup_root(
    tmp_path: Path,
) -> None:
    # REGRESSION: only the server copy was pruned; the independent encrypted
    # copy could retain erased media indefinitely.
    backup_root = tmp_path / "independent-backups"
    backup_root.mkdir()

    def create_backup(name: str, *, extra_file: bool = False) -> Path:
        directory = backup_root / name
        directory.mkdir()
        for filename in (
            "postgres.dump.age",
            "app-data.tgz.age",
            "SHA256SUMS",
        ):
            (directory / filename).write_text(filename, encoding="utf-8")
        (directory / "manifest.txt").write_text(
            f"created_at_utc={name}\n",
            encoding="utf-8",
        )
        if extra_file:
            (directory / "unexpected.txt").write_text("preserve", encoding="utf-8")
        return directory

    expired = create_backup("20260701T000000Z")
    current = create_backup("20260730T000000Z")
    noncanonical = create_backup("20260702T000000Z", extra_file=True)
    incomplete = backup_root / "20260703T000000Z"
    incomplete.mkdir()

    fake_bin = tmp_path / "fake-pruner-bin"
    fake_bin.mkdir()
    write_executable(
        fake_bin / "date",
        "#!/bin/sh\nprintf '20260722T000000Z\\n'\n",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

    completed = subprocess.run(
        [str(DEPLOYMENT_ROOT / "prune-backups.sh"), str(backup_root), "14"],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not expired.exists()
    assert current.is_dir()
    assert noncanonical.is_dir()
    assert incomplete.is_dir()


def test_backup_verifier_rejects_expired_independent_sibling(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    independent_root = fixture["independent_backup"].parent
    (independent_root / "20260701T000000Z").mkdir()
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "contains an expired timestamp: 20260701T000000Z" in completed.stderr


def test_restore_drill_uses_exact_disposable_resources_and_safe_cleanup() -> None:
    verifier = deployment_text("verify-backup.sh")

    assert 'DRILL_DATABASE="subframe_restore_drill_$backup_token"' in verifier
    assert 'DRILL_VOLUME="subframe-restore-drill-$backup_token-app-data"' in verifier
    assert "Refusing to use existing restore-drill database" in verifier
    assert "Refusing to use existing restore-drill volume" in verifier
    assert 'dropdb --username "$POSTGRES_USER"' in verifier
    assert '--if-exists --force "$DRILL_DATABASE"' in verifier
    assert 'docker volume rm "$DRILL_VOLUME"' in verifier
    assert "database_restore=true" in verifier
    assert "database_removed_before_app_restore=true" in verifier
    assert "volume_restore=true" in verifier
    assert "sequential_restore=true" in verifier
    assert "restore_size_multiplier=$RESTORE_SIZE_MULTIPLIER" in verifier
    assert "restore_fixed_reserve_bytes=$RESTORE_FIXED_RESERVE_BYTES" in verifier
    assert "schema_rollback_evidence=postgres_dump" in verifier
    assert "app_data_authoritative=false" in verifier
    assert "cleanup=true" in verifier
    assert 'rm -f -- "$RECEIPT_FILE"' in verifier
    assert "docker volume prune" not in verifier
    assert "rm -rf" not in verifier


def test_restore_drill_rejects_low_space_before_creating_resources(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(fixture, available_kib=1)

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            "--drill",
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert "Insufficient Docker filesystem space for database restore drill" in (completed.stderr)
    command_log = fixture["command_log"].read_text(encoding="utf-8")
    assert " createdb " not in f" {command_log} "
    assert " volume create " not in f" {command_log} "
    assert not (fixture["repository"] / ".runtime" / "last-backup-restore-drill").exists()


def test_restore_drill_drops_database_before_creating_app_volume(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )

    completed = subprocess.run(
        [
            str(fixture["verifier"]),
            "--drill",
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, completed.stderr
    command_log = fixture["command_log"].read_text(encoding="utf-8")
    assert command_log.index("dropdb ") < command_log.index("volume create ")
    receipt = (fixture["repository"] / ".runtime" / "last-backup-restore-drill").read_text(encoding="utf-8")
    assert "database_removed_before_app_restore=true" in receipt
    assert "sequential_restore=true" in receipt
    assert "restore_size_multiplier=2" in receipt
    assert "restore_fixed_reserve_bytes=10737418240" in receipt
    assert "app_data_authoritative=false" in receipt
    assert "server_backup_copy_device=111" in receipt
    assert "independent_backup_copy_device=222" in receipt
    assert "independent_backup_copy_distinct_filesystem=true" in receipt
    assert "independent_backup_copy_mount_detected=true" in receipt
    assert "independent_backup_copy_mount_read_only=true" in receipt


def test_restore_drill_signal_exits_nonzero_without_a_receipt(
    tmp_path: Path,
) -> None:
    fixture = backup_verifier_fixture(tmp_path)
    environment = backup_verifier_environment(
        fixture,
        available_kib=30_000_000,
    )
    marker = tmp_path / "age-started"
    environment["FAKE_AGE_MARKER"] = str(marker)
    process = subprocess.Popen(
        [
            str(fixture["verifier"]),
            "--drill",
            str(fixture["server_backup"]),
            str(fixture["independent_backup"]),
        ],
        env=environment,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    try:
        # REGRESSION: Five seconds was too tight for the verifier's checksum
        # preflight on a loaded local runner, before the fake age process starts.
        deadline = time.monotonic() + SUBPROCESS_START_TIMEOUT_SECONDS
        while not marker.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        assert marker.exists()
        process.terminate()
        _, stderr = process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    assert process.returncode not in (0, None), stderr
    assert not (fixture["repository"] / ".runtime" / "last-backup-restore-drill").exists()
    command_log = fixture["command_log"].read_text(encoding="utf-8")
    assert " createdb " not in f" {command_log} "
    assert " volume create " not in f" {command_log} "


def test_backup_signal_handler_cleans_up_and_returns_failure(tmp_path: Path) -> None:
    backup_script = deployment_text("backup.sh")

    assert "cleanup_on_signal()" in backup_script
    assert "trap - EXIT HUP INT TERM" in backup_script
    assert "trap cleanup_on_signal HUP INT TERM" in backup_script
    assert "terminate_active_stream" in backup_script

    env_file = tmp_path / "production.env"
    env_file.write_text(
        "\n".join(
            (
                "SUBFRAME_BACKUP_RETENTION_DAYS=14",
                "SUBFRAME_BACKUP_AGE_RECIPIENT=age1test",
                "POSTGRES_USER=subframe",
                "POSTGRES_DB=subframe",
                "",
            )
        ),
        encoding="utf-8",
    )
    backup_parent = tmp_path / "backup-parent"
    backup_parent.mkdir()
    backup_root = backup_parent / "production"
    fake_bin = tmp_path / "fake-backup-bin"
    fake_bin.mkdir()
    marker = tmp_path / "backup-age-started"
    write_executable(
        fake_bin / "git",
        """#!/bin/sh
printf '%040d\\n' 1
""",
    )
    write_executable(
        fake_bin / "docker",
        """#!/bin/sh
case "$*" in
  *"pg_database_size"*) printf '1024\\n' ;;
  *"du -sk"*) printf '1024\\n' ;;
  *"pg_dump"*) printf 'database archive' ;;
esac
""",
    )
    write_executable(
        fake_bin / "age",
        """#!/bin/sh
: > "$FAKE_AGE_MARKER"
exec sleep 30
""",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "SUBFRAME_ENV_FILE": str(env_file),
            "SUBFRAME_BACKUP_ROOT": str(backup_root),
            "FAKE_AGE_MARKER": str(marker),
        }
    )
    process = subprocess.Popen(
        [str(DEPLOYMENT_ROOT / "backup.sh")],
        env=environment,
        stderr=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )

    try:
        deadline = time.monotonic() + SUBPROCESS_START_TIMEOUT_SECONDS
        while not marker.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        assert marker.exists()
        process.terminate()
        process.communicate(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)

    assert process.returncode not in (0, None)
    assert backup_root.is_dir()
    assert list(backup_root.iterdir()) == []


def test_candidate_verifier_failure_preserves_previous_release_state(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    shutil.copy2(DEPLOYMENT_ROOT / "deploy-production.sh", deployment_root)
    shutil.copy2(DEPLOYMENT_ROOT / "verify-gcs-retirement.sh", deployment_root)
    (deployment_root / "docker-compose.production.yml").write_text(
        "services: {}\n",
        encoding="utf-8",
    )
    verifier_log = tmp_path / "candidate-verifier.log"
    write_executable(
        deployment_root / "verify-production.sh",
        """#!/bin/sh
printf '%s\\n' "$*" > "$FAKE_VERIFIER_LOG"
exit 1
""",
    )

    old_release_sha = "b" * 40
    new_release_sha = "c" * 40
    env_file = repository / ".env.production"
    env_file.write_text(
        f"SUBFRAME_RELEASE_SHA={new_release_sha}\n",
        encoding="utf-8",
    )
    state_dir = repository / ".runtime"
    state_dir.mkdir()
    state_file = state_dir / "last-successful-release"
    state_file.write_text(f"{old_release_sha}\n", encoding="utf-8")
    (state_dir / "privacy-continuity-id").write_text(
        f"{'2' * 64}\n",
        encoding="utf-8",
    )
    anchor_dir = state_dir / "privacy-erasure-anchor"
    anchor_dir.mkdir(mode=0o700)
    write_gcs_retirement_evidence(repository)

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    install_passing_public_edge_fixture(deployment_root, fake_bin)
    docker_command_log = tmp_path / "docker-commands.log"
    write_executable(
        fake_bin / "git",
        """#!/bin/sh
case "$*" in
  *"status --porcelain --untracked-files=normal"*) ;;
  *"rev-parse HEAD"*) printf '%s\\n' "$FAKE_NEW_RELEASE_SHA" ;;
  *"cat-file -e"*) ;;
  *"diff --quiet"*) ;;
  *) exit 1 ;;
esac
""",
    )
    write_executable(
        fake_bin / "docker",
        """#!/bin/sh
printf '%s\n' "$*" >> "$FAKE_DOCKER_COMMAND_LOG"
case "$*" in
  *"to_regclass"*) printf 'f\n' ;;
  *"source_gcs_object"*) printf '0\n' ;;
  *"compose"*"ps -q app-edge"*) printf 'app-edge-container\n' ;;
  *"compose"*"ps -q edge"*) printf 'edge-container\n' ;;
esac
if [ "${1:-}" = "inspect" ]; then
  printf 'healthy\\n'
fi
""",
    )
    write_executable(
        fake_bin / "stat",
        """#!/bin/sh
case "$*" in
  *"%a"*privacy-erasure-anchor|*"%Lp"*privacy-erasure-anchor) printf '700\n' ;;
  *"%a"*|*"%Lp"*) printf '600\n' ;;
  *"%u"*|*"%g"*) printf '10001\n' ;;
  *) exec /usr/bin/stat "$@" ;;
esac
""",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "SUBFRAME_ENV_FILE": str(env_file),
            "FAKE_NEW_RELEASE_SHA": new_release_sha,
            "FAKE_VERIFIER_LOG": str(verifier_log),
            "FAKE_DOCKER_COMMAND_LOG": str(docker_command_log),
        }
    )

    completed = subprocess.run(
        [str(deployment_root / "deploy-production.sh")],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 1
    assert state_file.read_text(encoding="utf-8").strip() == old_release_sha
    assert verifier_log.read_text(encoding="utf-8").strip() == "--candidate"
    assert "previous successful-release state was preserved" in completed.stderr
    docker_commands = docker_command_log.read_text(encoding="utf-8")
    assert "configured_erasure_journal().read_all()" in docker_commands
    assert "configured_erasure_journal().initialize()" not in docker_commands
    assert docker_commands.index("configured_erasure_journal().read_all()") < docker_commands.index(
        "up -d backend frontend",
    )


def test_release_runbook_requires_off_server_copy_and_restore_drill() -> None:
    runbook = deployment_text("README.md")

    assert "off-server" in runbook
    assert "different Linux filesystem devices" in runbook
    assert 'findmnt --target "$independent_backup_dir"' in runbook
    assert "standalone `ro` mount option" in runbook
    assert "writable, absent" in runbook
    assert "or ambiguous mount fails closed" in runbook
    assert "independent_backup_copy_mount_read_only=true" in runbook
    assert "scalar checksum" in runbook
    assert "verify-backup.sh --drill" in runbook
    assert "twice that resource's manifest size plus a fixed 10 GiB reserve" in runbook
    assert "PostgreSQL dump is the authoritative schema rollback evidence" in runbook
    assert "app-data` archive" in runbook
    assert "non-authoritative" in runbook
    assert "schema-changing release" in runbook
    assert "last-backup-restore-drill" in runbook
    assert "same exact target release SHA" in runbook
    assert "24 hours" in runbook
    assert "prune-backups.sh" in runbook
    assert "Both\nlocations must use the same configured retention" in runbook
    assert "only until that backup's configured expiry" in runbook
    assert "subframe-erasure-journal" in runbook
    assert "reconcile-erasures" in runbook
    assert "last-erasure-reconciliation" in runbook


def test_edge_routes_billing_api_and_verifier_smokes_catalog() -> None:
    """REGRESSION: the deployed edge previously sent /billing to Next.js."""
    caddyfile = deployment_text("Caddyfile")
    verifier = deployment_text("verify-production.sh")

    assert "/billing /billing/*" in caddyfile
    assert "/health" in verifier
    assert 'health.get("status") != "ok"' in verifier
    assert 'health.get("app_env") != "production"' in verifier
    assert "/billing/catalog" in verifier
    assert 'catalog.get("checkout_enabled") is not True' in verifier
    assert "alembic current" in verifier
    assert "alembic current --check-heads" in verifier


def test_edge_never_recompresses_private_media_downloads() -> None:
    """MP4 byte ranges must pass through the edge without gzip/zstd work."""
    caddyfile = deployment_text("Caddyfile")

    assert "@compressible_response {" in caddyfile
    assert "not path /static/*" in caddyfile
    assert "encode @compressible_response zstd gzip" in caddyfile
    assert "\n\tencode zstd gzip" not in caddyfile


def test_edge_healthcheck_consumes_the_response_body() -> None:
    """REGRESSION: wget --spider made Caddy log an aborted response every 20s."""
    compose = deployment_text("docker-compose.production.yml")
    edge_service = compose.split("  edge:", 1)[1].split("\n  privacy-relay:", 1)[0]
    healthcheck = edge_service.split("    healthcheck:", 1)[1]

    assert 'test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:8080/.well-known/gsubs-edge-health"]' in healthcheck
    assert "--spider" not in healthcheck


def test_stable_gateway_serves_maintenance_while_the_private_app_edge_is_closed() -> None:
    """REGRESSION: privacy-safe deploy cutovers surfaced a raw tunnel 502."""
    compose = deployment_text("docker-compose.production.yml")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    gateway = deployment_text("gateway/Caddyfile")

    app_edge = compose.split("  app-edge:", 1)[1].split("\n  edge:", 1)[0]
    edge = compose.split("  edge:", 1)[1].split("\n  privacy-relay:", 1)[0]
    assert "ports:" not in app_edge
    assert "provider_egress" in app_edge
    assert "gateway_link" in app_edge
    assert "mizai_edge" not in app_edge
    assert "./Caddyfile:/etc/caddy/Caddyfile:ro" in app_edge
    assert "./gateway:/etc/caddy:ro" in edge
    assert "subframe-edge" in edge
    assert "gateway_link" in edge
    assert "private: {}" not in edge
    assert "provider_egress" not in edge
    assert "depends_on:" not in edge
    assert "/.well-known/gsubs-edge-health" in edge

    assert "admin 127.0.0.1:2019" in gateway
    assert gateway.count("name app-edge") == 2
    assert "dynamic a" in gateway
    assert "handle_errors" in gateway
    assert 'Retry-After "5"' in gateway
    assert "Κάνουμε μια σύντομη αναβάθμιση." in gateway
    assert "reverse_proxy backend:" not in gateway
    assert "reverse_proxy frontend:" not in gateway

    cutover = deploy_script.split('install -d -m 700 "$STATE_DIR"', 1)[1]
    app_stop = cutover.index("compose stop app-edge")
    app_start = cutover.index("compose up -d --no-deps --force-recreate app-edge")
    reconciliation = cutover.index("python -m backend.cli reconcile-erasures")
    assert app_stop < reconciliation < app_start
    assert "prepare_public_gateway" in deploy_script
    assert "reload_public_gateway" in deploy_script
    rollback_body = deploy_script.split("rollback() {", 1)[1].split("\n}\n", 1)[0]
    assert "compose stop app-edge" in rollback_body
    assert "compose up -d --no-deps edge" not in rollback_body
    assert "Running stable gateway contract is unsafe" in verifier
    assert "The application edge must not join the shared public tunnel network" in verifier
    assert "Stable gateway must not reach private application or provider networks directly" in verifier


def test_edge_caps_stripe_webhook_body_before_generic_billing_proxy() -> None:
    caddyfile = deployment_text("Caddyfile")

    stripe_matcher = "@stripe_webhook path /billing/webhook"
    assert stripe_matcher in caddyfile
    assert caddyfile.index(stripe_matcher) < caddyfile.index("@backend path")
    stripe_handler = caddyfile.split(stripe_matcher, 1)[1].split("@backend path", 1)[0]
    assert "request_body" in stripe_handler
    assert "max_size 1MB" in stripe_handler
    assert "reverse_proxy backend:8080" in stripe_handler


def test_edge_caps_the_only_streaming_video_upload_route() -> None:
    caddyfile = deployment_text("Caddyfile")

    stream_matcher = "@video_stream path /videos/process-stream"
    assert stream_matcher in caddyfile
    assert caddyfile.index(stream_matcher) < caddyfile.index("@backend path")
    stream_handler = caddyfile.split(stream_matcher, 1)[1].split(
        "@backend path",
        1,
    )[0]
    assert "request_body" in stream_handler
    assert "max_size 500MB" in stream_handler
    assert "reverse_proxy backend:8080" in stream_handler


def test_edge_caps_feedback_before_the_generic_backend_proxy() -> None:
    caddyfile = deployment_text("Caddyfile")
    verifier = deployment_text("verify-production.sh")

    feedback_matcher = "@feedback path /feedback"
    backend_matcher = next(
        line.strip()
        for line in caddyfile.splitlines()
        if line.strip().startswith("@backend path ")
    )
    assert caddyfile.count(feedback_matcher) == 1
    assert caddyfile.index(feedback_matcher) < caddyfile.index("@backend path")
    feedback_handler = caddyfile.split(feedback_matcher, 1)[1].split(
        "@backend path",
        1,
    )[0]
    assert "request_body" in feedback_handler
    assert "max_size 16KB" in feedback_handler
    assert feedback_handler.count("reverse_proxy backend:8080") == 1
    assert "/feedback" not in backend_matcher
    assert "Public feedback request-body cap must be exactly 16KB" in verifier
    assert "Feedback must not bypass its body cap" in verifier


def test_google_oauth_certificates_use_a_scoped_internal_edge_relay() -> None:
    """REGRESSION: the internal-only backend could not resolve Google's cert host."""
    compose = deployment_text("docker-compose.production.yml")
    caddyfile = deployment_text("Caddyfile")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")

    assert "internal: true" in compose
    assert 'GSP_GOOGLE_OAUTH_CERTS_URL: "http://edge:8081/oauth2/v1/certs"' in compose
    assert ":8081" in caddyfile
    assert "/oauth2/v1/certs" in caddyfile
    google_matcher = caddyfile.split("@google_oauth_certs {", 1)[1].split("}", 1)[0]
    assert "method GET" in google_matcher
    assert "method POST" not in google_matcher
    assert "reverse_proxy https://www.googleapis.com" in caddyfile
    assert "compose run --rm --no-deps --entrypoint caddy app-edge validate" in deploy_script
    assert "compose up -d --no-deps --force-recreate app-edge" in deploy_script
    assert '"@google_oauth_certs": (' in verifier
    assert '"path /oauth2/v1/certs"' in verifier


def test_stripe_api_uses_a_method_and_path_scoped_internal_edge_relay() -> None:
    compose = deployment_text("docker-compose.production.yml")
    caddyfile = deployment_text("Caddyfile")
    verifier = deployment_text("verify-production.sh")

    assert "internal: true" in compose
    assert 'GSP_STRIPE_API_BASE: "http://edge:8081/stripe"' in compose
    for matcher in (
        "@stripe_checkout_create",
        "@stripe_checkout_expire",
        "@stripe_payment_intent_retrieve",
        "@stripe_payment_intent_capture",
        "@stripe_payment_intent_cancel",
        "@stripe_refund_list",
    ):
        assert matcher in caddyfile
    assert "method POST" in caddyfile
    assert "method GET" in caddyfile
    assert "/stripe/v1/checkout/sessions" in caddyfile
    assert "/stripe/v1/payment_intents/" in caddyfile
    assert "^/stripe/v1/payment_intents/pi_[A-Za-z0-9_]+/capture$" in caddyfile
    assert "^/stripe/v1/payment_intents/pi_[A-Za-z0-9_]+/cancel$" in caddyfile
    assert "/stripe/v1/refunds" in caddyfile
    assert "uri strip_prefix /stripe" in caddyfile
    assert "reverse_proxy https://api.stripe.com" in caddyfile
    assert "header_up Host api.stripe.com" in caddyfile
    assert '"@stripe_payment_intent_retrieve": (' in verifier
    assert '"@stripe_payment_intent_capture": (' in verifier
    assert '"@stripe_payment_intent_cancel": (' in verifier
    assert '"https://api.stripe.com": 6' in verifier
    assert "GSP_STRIPE_RESTRICTED_KEY" not in caddyfile


def test_elevenlabs_scribe_uses_a_method_and_path_scoped_internal_edge_relay() -> None:
    compose = deployment_text("docker-compose.production.yml")
    caddyfile = deployment_text("Caddyfile")
    verifier = deployment_text("verify-production.sh")

    assert "internal: true" in compose
    assert 'GSP_ELEVENLABS_API_BASE: "http://edge:8081/elevenlabs"' in compose
    assert "@elevenlabs_scribe" in caddyfile
    assert "method POST" in caddyfile
    assert "path /elevenlabs/v1/speech-to-text" in caddyfile
    assert "method DELETE" in caddyfile
    assert (
        "path_regexp elevenlabs_transcript_delete "
        "^/elevenlabs/v1/speech-to-text/transcripts/"
        "[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
    ) in caddyfile
    assert "max_size 32MB" in caddyfile
    assert "uri strip_prefix /elevenlabs" in caddyfile
    assert "reverse_proxy https://api.elevenlabs.io" in caddyfile
    assert "header_up Host api.elevenlabs.io" in caddyfile
    assert '"@elevenlabs_scribe": (' in verifier
    assert '"@elevenlabs_transcript_delete": (' in verifier
    assert '"https://api.elevenlabs.io": 2' in verifier
    assert 'transcripts/invalid/path", "DELETE"' in verifier
    assert "path /elevenlabs/*" not in caddyfile
    assert "ELEVENLABS_API_KEY" not in caddyfile
    assert "log {" not in caddyfile
    assert "request>body" not in caddyfile
    scribe_matcher = caddyfile.split("@elevenlabs_scribe {", 1)[1].split("}", 1)[0]
    delete_matcher = caddyfile.split("@elevenlabs_transcript_delete {", 1)[1].split("}", 1)[0]
    assert "method POST" in scribe_matcher
    assert "method DELETE" not in scribe_matcher
    assert "path /elevenlabs/v1/speech-to-text" in scribe_matcher
    assert "method DELETE" in delete_matcher
    assert "method POST" not in delete_matcher


def test_production_verifier_never_calls_an_allowed_third_party_relay_route() -> None:
    verifier = deployment_text("verify-production.sh")
    runbook = deployment_text("README.md")

    # REGRESSION: candidate verification used real Google, Stripe and
    # ElevenLabs endpoints as health checks. Even bogus IDs still disclosed a
    # request to a third party and made a release depend on provider state.
    assert "runtime_caddyfile_sha" in verifier
    assert "caddy validate" in verifier
    assert "expected_matchers" in verifier
    assert "actual_upstreams" in verifier
    assert "relay_deny_http=" in verifier
    assert '"404,404,404,404,404,404,404"' in verifier
    assert "google_oauth_certs_http=" not in verifier
    assert "stripe_relay_http=" not in verifier
    assert "elevenlabs_relay_http=" not in verifier
    assert "pi_gsubs_relay_probe" not in verifier
    assert 'transcripts/gsubs_relay_probe", "DELETE"' not in verifier
    assert '(f"{base}/v1/speech-to-text", "POST")' not in verifier
    assert "it never sends a verification request to a third-party" in runbook


def test_runtime_relay_contract_validator_accepts_only_the_reviewed_allow_list() -> None:
    verifier = deployment_text("verify-production.sh")
    caddyfile = deployment_text("Caddyfile")
    validator = relay_validator_source(verifier)

    accepted = subprocess.run(
        [sys.executable, "-c", validator],
        check=False,
        capture_output=True,
        input=caddyfile,
        text=True,
        timeout=10,
    )
    assert accepted.returncode == 0, accepted.stderr

    unsafe_variants = (
        caddyfile.replace(
            "@google_oauth_certs {\n\t\tmethod GET",
            "@google_oauth_certs {\n\t\tmethod POST",
            1,
        ),
        caddyfile.replace(
            "\trespond 404\n}",
            "\treverse_proxy https://unreviewed.invalid\n\n\trespond 404\n}",
            1,
        ),
        caddyfile.replace("max_size 16KB", "max_size 1MB", 1),
        caddyfile.replace("@backend path ", "@backend path /feedback ", 1),
    )
    for unsafe in unsafe_variants:
        rejected = subprocess.run(
            [sys.executable, "-c", validator],
            check=False,
            capture_output=True,
            input=unsafe,
            text=True,
            timeout=10,
        )
        assert rejected.returncode != 0


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
    assert "mkdir -p /data/uploads /data/artifacts /privacy-erasure-journal" in dockerfile
    assert "app_logs" not in dockerfile
    assert "/app/logs" not in dockerfile
    # REGRESSION: The selected waveform-to-subtitles watermark was replaced by
    # an unapproved compact-split asset.
    assert hashlib.sha256(watermark.read_bytes()).hexdigest() == (
        "9c71785c9716ad152b97d7691a7445fd0219d1da00f44fd691261cee35e874d0"
    )


def test_backend_image_normalizes_checkout_modes_before_non_root_runtime() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    source_copy = "COPY backend/ ."
    mode_normalization = "RUN chmod -R a=rX,u+w /app \\\n    && chmod 0644 /gsubs-logo.png"
    non_root_runtime = "USER appuser"

    # REGRESSION: a release checkout created under umask 077 gave modified
    # Python files mode 0600. Docker preserved those modes and the non-root
    # runtime failed to import cleanup.py before it could become healthy.
    assert source_copy in dockerfile
    assert mode_normalization in dockerfile
    assert non_root_runtime in dockerfile
    assert dockerfile.index(source_copy) < dockerfile.index(mode_normalization)
    assert dockerfile.index(mode_normalization) < dockerfile.index(non_root_runtime)
    assert "/data" not in mode_normalization
    assert "/models" not in mode_normalization
    assert "/privacy-erasure-journal" not in mode_normalization


def test_deploy_preflights_backend_import_before_public_cutover() -> None:
    deploy_script = deployment_text("deploy-production.sh")
    image_build = "compose build --pull backend frontend"
    probe = (
        "compose run --rm --no-deps --entrypoint python backend -c \\\n"
        "  'from pathlib import Path; import os; root = Path(\"/app\"); "
        "assert all(os.access(path, os.R_OK | (os.X_OK if path.is_dir() else 0)) "
        "for path in (root, *root.rglob(\"*\"))); import main'"
    )
    public_cutover = "if ! compose stop app-edge; then"

    # REGRESSION: candidate image startup was first exercised only after the
    # public edge had closed, turning a source-mode build defect into downtime.
    assert image_build in deploy_script
    assert probe in deploy_script
    assert public_cutover in deploy_script
    assert deploy_script.index(image_build) < deploy_script.index(probe)
    assert deploy_script.index(probe) < deploy_script.index(public_cutover)

    # The preflight may read packaged source and import the ASGI module only.
    # It must not start dependencies, enter lifespan, touch the database, or
    # issue a provider request while the current production release is live.
    assert "--no-deps" in probe
    assert "--entrypoint python" in probe
    assert "import main" in probe
    assert 'Path("/app")' in probe
    assert "os.R_OK" in probe
    assert "os.X_OK" in probe
    for unsafe_fragment in (
        "Database(",
        "lifespan(",
        "run_configured_retention",
        "reconcile_erasure_journal",
        "requests.",
        "stripe.",
        "http://",
        "https://",
    ):
        assert unsafe_fragment not in probe


def test_frontend_image_uses_native_patched_dependencies_without_postinstall_shim() -> None:
    dockerfile = (REPOSITORY_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    package = (REPOSITORY_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    package_lock = json.loads((REPOSITORY_ROOT / "frontend" / "package-lock.json").read_text(encoding="utf-8"))
    patch_script = REPOSITORY_ROOT / "frontend" / "scripts" / "patch-brace-expansion.cjs"
    script_copy = "COPY scripts/patch-brace-expansion.cjs"

    brace_versions = {
        metadata["version"]
        for path, metadata in package_lock["packages"].items()
        if path.endswith("node_modules/brace-expansion")
    }
    assert brace_versions == {"1.1.18", "2.1.4", "5.0.9"}
    assert '"postcss": "8.5.25"' in package
    assert '"brace-expansion"' not in package
    assert '"postinstall"' not in package
    assert not patch_script.exists()
    assert script_copy not in dockerfile


def test_frontend_build_context_excludes_generated_and_local_state() -> None:
    dockerignore = (
        (REPOSITORY_ROOT / "frontend" / ".dockerignore")
        .read_text(
            encoding="utf-8",
        )
        .splitlines()
    )

    for expected in (
        "node_modules/",
        ".next/",
        "coverage/",
        "test-results/",
        "playwright-report/",
        ".env*",
    ):
        assert expected in dockerignore


def test_public_edge_verifier_quarantines_the_slow_http3_path(
    tmp_path: Path,
) -> None:
    # REGRESSION: the public HTTP/3 path once took more than three minutes for
    # a 49 MiB download while the same authenticated file took under eight
    # seconds over HTTP/2.
    accepted = run_public_edge_verifier(tmp_path)
    assert accepted.returncode == 0, accepted.stderr
    assert "HTTP/2 200 with no HTTP/3 advertisement" in accepted.stdout

    rejected_cases = (
        {"protocol": "1.1"},
        {"status": "503"},
        {"content_type": "text/html"},
        {"alt_svc": 'h3=":443"; ma=2592000'},
        {"curl_exit": "7"},
    )
    for index, overrides in enumerate(rejected_cases):
        case_path = tmp_path / f"case-{index}"
        case_path.mkdir()
        rejected = run_public_edge_verifier(case_path, **overrides)
        assert rejected.returncode != 0
        assert "Public GSubs transport policy is invalid" in rejected.stderr


def test_public_edge_policy_gates_deploy_verification_and_nightly_ci() -> None:
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    nightly = (
        REPOSITORY_ROOT / ".github" / "workflows" / "nightly-quality.yml"
    ).read_text(encoding="utf-8")
    gate = '"$ROOT_DIR/deploy/hetzner/verify-public-edge.sh"'

    # REGRESSION: loopback health and CI were green while the external QUIC
    # body path was unusably slow. Keep an externally observable guard before
    # production mutation, after candidate activation and every night.
    assert gate in deploy_script
    assert deploy_script.index(gate) < deploy_script.index("privacy_continuity_bootstrap=0")
    assert gate in verifier
    assert "./deploy/hetzner/verify-public-edge.sh" in nightly


def test_deployment_shell_scripts_have_valid_syntax() -> None:
    for filename in (
        "backup.sh",
        "deploy-production.sh",
        "prune-backups.sh",
        "verify-backup.sh",
        "verify-public-edge.sh",
        "verify-production.sh",
    ):
        completed = subprocess.run(
            ["sh", "-n", str(DEPLOYMENT_ROOT / filename)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
