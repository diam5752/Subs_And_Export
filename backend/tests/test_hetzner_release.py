from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from backend.tests.hetzner_deployment_test_support import (
    DEPLOYMENT_ROOT,
    copy_release_script,
    deployment_text,
    install_passing_public_edge_fixture,
    write_executable,
)


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
    copy_release_script("deploy-production.sh", deployment_root)
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
    copy_release_script("deploy-production.sh", deployment_root)
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
