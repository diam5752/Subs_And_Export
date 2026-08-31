from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import textwrap
from decimal import Decimal
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEPLOYMENT_ROOT = REPOSITORY_ROOT / "deploy" / "hetzner"
SUBPROCESS_START_TIMEOUT_SECONDS = 15.0

RELEASE_SCRIPT_LIBRARIES = {
    "deploy-production.sh": (
        "deploy-transition.sh",
        "deploy-guards.sh",
    ),
    "verify-production.sh": (
        "verify-contracts.sh",
        "verify-edge.sh",
    ),
}


def deployment_text(filename: str) -> str:
    source = (DEPLOYMENT_ROOT / filename).read_text(encoding="utf-8")
    for library_name in RELEASE_SCRIPT_LIBRARIES.get(filename, ()):
        library_source = (DEPLOYMENT_ROOT / "lib" / library_name).read_text(
            encoding="utf-8",
        )
        source = f"{source}\n{library_source}"
    return source


def copy_release_script(filename: str, deployment_root: Path) -> None:
    shutil.copy2(DEPLOYMENT_ROOT / filename, deployment_root)
    libraries = RELEASE_SCRIPT_LIBRARIES.get(filename, ())
    if not libraries:
        return
    target_library_root = deployment_root / "lib"
    target_library_root.mkdir(exist_ok=True)
    for library_name in libraries:
        shutil.copy2(
            DEPLOYMENT_ROOT / "lib" / library_name,
            target_library_root / library_name,
        )


def relay_validator_source(verifier: str) -> str:
    marker = (
        'docker exec "$app_edge_id" cat /etc/caddy/Caddyfile | '
        'docker exec -i "$backend_id" python -c '
        '\'import textwrap; exec(compile(textwrap.dedent("""\\\n'
    )
    terminator = '\n  """), "<gsubs-production-verifier>", "exec"))\'; then'
    validator = textwrap.dedent(verifier.split(marker, 1)[1].split(terminator, 1)[0])
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
    maintenance: bool = False,
    protocol: str = "2",
    status: str = "200",
    content_type: str = "application/json",
    retry_after: str = "",
    cache_control: str = "",
    body: str = '{"status":"ok"}',
    alt_svc: str = "",
    curl_exit: str = "0",
) -> subprocess.CompletedProcess[str]:
    fake_curl = tmp_path / "fake-curl"
    write_executable(
        fake_curl,
        """#!/bin/sh
set -eu
header_path=""
output_path=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dump-header) shift; header_path=$1 ;;
    --output) shift; output_path=$1 ;;
  esac
  shift
done
[ -n "$header_path" ]
[ -n "$output_path" ]
{
  printf 'HTTP/%s %s\\r\\n' "$FAKE_PROTOCOL" "$FAKE_STATUS"
  printf 'content-type: %s\\r\\n' "$FAKE_CONTENT_TYPE"
  if [ -n "$FAKE_RETRY_AFTER" ]; then
    printf 'retry-after: %s\\r\\n' "$FAKE_RETRY_AFTER"
  fi
  if [ -n "$FAKE_CACHE_CONTROL" ]; then
    printf 'cache-control: %s\\r\\n' "$FAKE_CACHE_CONTROL"
  fi
  if [ -n "$FAKE_ALT_SVC" ]; then
    printf 'alt-svc: %s\\r\\n' "$FAKE_ALT_SVC"
  fi
  printf '\\r\\n'
} > "$header_path"
printf '%s' "$FAKE_BODY" > "$output_path"
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
            "FAKE_RETRY_AFTER": retry_after,
            "FAKE_CACHE_CONTROL": cache_control,
            "FAKE_BODY": body,
            "FAKE_ALT_SVC": alt_svc,
            "FAKE_CURL_EXIT": curl_exit,
        }
    )
    return subprocess.run(
        [
            str(DEPLOYMENT_ROOT / "verify-public-edge.sh"),
            *(["--maintenance"] if maintenance else []),
        ],
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
output_path=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dump-header) shift; header_path=$1 ;;
    --output) shift; output_path=$1 ;;
  esac
  shift
done
[ -n "$header_path" ]
[ -n "$output_path" ]
printf 'HTTP/2 200\\r\\ncontent-type: application/json\\r\\n\\r\\n' > "$header_path"
printf '{"status":"ok"}' > "$output_path"
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
