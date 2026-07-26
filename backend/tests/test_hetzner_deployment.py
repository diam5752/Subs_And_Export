from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = REPOSITORY_ROOT / "deploy" / "hetzner"


def deployment_text(filename: str) -> str:
    return (DEPLOYMENT_ROOT / filename).read_text(encoding="utf-8")


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


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
        f"POSTGRES_USER=subframe\nSUBFRAME_RELEASE_SHA={release_sha}\n",
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
        }
    )
    return environment


def test_production_compose_is_mock_only_and_loopback_bound() -> None:
    compose = deployment_text("docker-compose.production.yml")

    assert '"127.0.0.1:${SUBFRAME_PREVIEW_PORT:-18090}:8080"' in compose
    assert "GSP_APP_ENV: production" in compose
    assert "APP_ENV: production" in compose
    assert 'GSP_MOCK_EXTERNAL_SERVICES: "1"' in compose
    assert 'GSP_ELEVENLABS_ENABLED: "0"' in compose
    assert 'GSP_PAID_CREDITS_ENABLED: "0"' in compose
    assert 'GSP_CONSUMER_POLICY_APPROVED: "0"' in compose
    assert 'GSP_DURABLE_CONFIRMATION_CHANNEL_READY: "0"' in compose
    assert 'GSP_ADJUSTMENT_WORKFLOW_READY: "0"' in compose
    assert 'GSP_STRIPE_AUTOMATIC_TAX_ENABLED: "0"' in compose
    assert 'GSP_STRIPE_RESTRICTED_KEY: ""' in compose
    assert 'GSP_STRIPE_WEBHOOK_SECRET: ""' in compose
    assert 'GSP_STRIPE_PRICE_STARTER: ""' in compose
    assert 'GSP_STRIPE_PRICE_CORE: ""' in compose
    assert 'GSP_STRIPE_PRICE_PRO: ""' in compose
    assert 'GSP_BILLING_ADMIN_USER_IDS: ""' in compose
    assert 'STRIPE_SECRET_KEY: ""' in compose
    assert 'STRIPE_WEBHOOK_SECRET: ""' in compose
    assert 'OPENAI_API_KEY: ""' in compose
    assert 'GROQ_API_KEY: ""' in compose
    assert 'ELEVENLABS_API_KEY: ""' in compose
    assert 'GSP_GCS_BUCKET: ""' in compose
    assert 'GOOGLE_APPLICATION_CREDENTIALS: ""' in compose
    assert 'GOOGLE_CLIENT_SECRET: ""' in compose
    assert 'GOOGLE_REDIRECT_URI: ""' in compose
    assert 'GSP_GOOGLE_OAUTH_CERTS_URL: "http://edge:8081/oauth2/v1/certs"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD: "0"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD: "0"' in compose
    assert 'GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD: "0"' in compose
    assert "external: true" in compose
    assert "name: mizai_mizai-private" in compose


def test_production_verifier_requires_every_fail_closed_runtime_setting() -> None:
    verifier = deployment_text("verify-production.sh")

    for expected in (
        "GSP_APP_ENV=production",
        "APP_ENV=production",
        "GSP_MOCK_EXTERNAL_SERVICES=1",
        "GSP_ELEVENLABS_ENABLED=0",
        "GSP_PAID_CREDITS_ENABLED=0",
        "GSP_CONSUMER_POLICY_APPROVED=0",
        "GSP_DURABLE_CONFIRMATION_CHANNEL_READY=0",
        "GSP_ADJUSTMENT_WORKFLOW_READY=0",
        "GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0",
        "GSP_STRIPE_RESTRICTED_KEY=",
        "GSP_STRIPE_WEBHOOK_SECRET=",
        "GSP_STRIPE_PRICE_STARTER=",
        "GSP_STRIPE_PRICE_CORE=",
        "GSP_STRIPE_PRICE_PRO=",
        "GSP_BILLING_ADMIN_USER_IDS=",
        "STRIPE_SECRET_KEY=",
        "STRIPE_WEBHOOK_SECRET=",
        "OPENAI_API_KEY=",
        "GROQ_API_KEY=",
        "ELEVENLABS_API_KEY=",
        "GSP_GCS_BUCKET=",
        "GOOGLE_APPLICATION_CREDENTIALS=",
        "GOOGLE_CLIENT_SECRET=",
        "GOOGLE_REDIRECT_URI=",
        "GSP_GOOGLE_OAUTH_CERTS_URL=http://edge:8081/oauth2/v1/certs",
        "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600",
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
    verifier = deployment_text("verify-production.sh")
    frontend_dockerfile = (REPOSITORY_ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

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
    assert "GOOGLE_CLIENT_ID=replace-with-google-web-client-id" in environment
    assert "GOOGLE_CLIENT_SECRET=" in environment
    assert "GOOGLE_REDIRECT_URI=" in environment
    assert "GSP_GOOGLE_OAUTH_CERTS_URL=http://edge:8081/oauth2/v1/certs" in environment
    assert "GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600" in environment
    assert "GSP_CONSUMER_POLICY_APPROVED=0" in environment
    assert "GSP_DURABLE_CONFIRMATION_CHANNEL_READY=0" in environment
    assert "GSP_ADJUSTMENT_WORKFLOW_READY=0" in environment
    assert "GSP_BILLING_ADMIN_USER_IDS=" in environment
    assert "google_client_id=$(env_value GOOGLE_CLIENT_ID)" in verifier
    assert "billing_admin_user_ids=$(env_value GSP_BILLING_ADMIN_USER_IDS)" not in verifier
    assert "NEXT_PUBLIC_MAX_UPLOAD_MB: ${SUBFRAME_MAX_UPLOAD_MB:-500}" in compose
    assert "ARG NEXT_PUBLIC_MAX_UPLOAD_MB=500" in frontend_dockerfile
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
    deploy_cutover = deploy_script.index("compose up -d db backend frontend")
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

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
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
    assert "up -d db backend frontend" not in commands


def test_backup_verifier_authenticates_and_validates_every_archive() -> None:
    backup_script = deployment_text("backup.sh")
    verifier = deployment_text("verify-backup.sh")

    assert "sha256sums_sha256=" in backup_script
    assert "INDEPENDENT_BACKUP_DIRECTORY" in verifier
    assert "Independent backup copy must be mounted on a different filesystem device" in verifier
    assert "Independent backup copy differs from server file" in verifier
    assert 'age --decrypt --identity "$IDENTITY_FILE"' in verifier
    assert "pg_restore --list" in verifier
    assert "tar -tzf -" in verifier
    assert "postgres.dump.age" in verifier
    assert "app-data.tgz.age" in verifier
    assert "manifest.txt" in verifier


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

    assert 'prune_backup_directory "$candidate"' in backup_script
    assert 'candidate_parent="$BACKUP_ROOT"' in backup_script
    assert "created_at_utc=$backup_name" in backup_script
    assert 'rm -f -- "$candidate/postgres.dump.age"' in backup_script
    assert 'rmdir -- "$candidate"' in backup_script
    assert "-exec rm -rf" not in backup_script
    assert "rm -rf" not in backup_script


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
        deadline = time.monotonic() + 5
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
        deadline = time.monotonic() + 5
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

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
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
            "FAKE_VERIFIER_LOG": str(verifier_log),
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


def test_edge_routes_billing_api_and_verifier_smokes_catalog() -> None:
    """REGRESSION: the deployed edge previously sent /billing to Next.js."""
    caddyfile = deployment_text("Caddyfile")
    verifier = deployment_text("verify-production.sh")

    assert "/billing /billing/*" in caddyfile
    assert "/health" in verifier
    assert 'health.get("status") != "ok"' in verifier
    assert 'health.get("app_env") != "production"' in verifier
    assert "/billing/catalog" in verifier
    assert 'catalog.get("checkout_enabled") is not False' in verifier
    assert "alembic current" in verifier
    assert "alembic current --check-heads" in verifier


def test_edge_caps_stripe_webhook_body_before_generic_billing_proxy() -> None:
    caddyfile = deployment_text("Caddyfile")

    stripe_matcher = "@stripe_webhook path /billing/webhook"
    assert stripe_matcher in caddyfile
    assert caddyfile.index(stripe_matcher) < caddyfile.index("@backend path")
    stripe_handler = caddyfile.split(stripe_matcher, 1)[1].split("@backend path", 1)[0]
    assert "request_body" in stripe_handler
    assert "max_size 1MB" in stripe_handler
    assert "reverse_proxy backend:8080" in stripe_handler


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
    assert "reverse_proxy https://www.googleapis.com" in caddyfile
    assert "compose run --rm --no-deps --entrypoint caddy edge validate" in deploy_script
    assert "compose up -d --force-recreate edge" in deploy_script
    assert "google_oauth_certs_http=" in verifier


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


def test_deployment_shell_scripts_have_valid_syntax() -> None:
    for filename in (
        "backup.sh",
        "deploy-production.sh",
        "verify-backup.sh",
        "verify-production.sh",
    ):
        completed = subprocess.run(
            ["sh", "-n", str(DEPLOYMENT_ROOT / filename)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
