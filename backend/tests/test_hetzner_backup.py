from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

from backend.tests.hetzner_deployment_test_support import (
    DEPLOYMENT_ROOT,
    REPOSITORY_ROOT,
    SUBPROCESS_START_TIMEOUT_SECONDS,
    backup_verifier_environment,
    backup_verifier_fixture,
    deployment_text,
    write_executable,
)


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
