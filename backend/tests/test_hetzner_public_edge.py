from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from backend.tests.hetzner_deployment_test_support import (
    DEPLOYMENT_ROOT,
    REPOSITORY_ROOT,
    deployment_text,
    run_public_edge_verifier,
    write_executable,
)


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


def test_public_edge_verifier_accepts_only_the_reviewed_maintenance_page(
    tmp_path: Path,
) -> None:
    accepted = run_public_edge_verifier(
        tmp_path,
        maintenance=True,
        status="503",
        content_type="text/html; charset=utf-8",
        retry_after="5",
        cache_control="no-store, max-age=0",
        body="<h1>Κάνουμε μια σύντομη αναβάθμιση.</h1>",
    )
    assert accepted.returncode == 0, accepted.stderr
    assert "reviewed no-store response" in accepted.stdout

    rejected_cases = (
        {"protocol": "1.1"},
        {"status": "200"},
        {"content_type": "application/json"},
        {"retry_after": "30"},
        {"cache_control": "max-age=0"},
        {"body": "generic upstream outage"},
        {"alt_svc": 'h3=":443"; ma=2592000'},
        {"curl_exit": "7"},
    )
    defaults = {
        "maintenance": True,
        "status": "503",
        "content_type": "text/html; charset=utf-8",
        "retry_after": "5",
        "cache_control": "no-store, max-age=0",
        "body": "Κάνουμε μια σύντομη αναβάθμιση.",
    }
    for index, overrides in enumerate(rejected_cases):
        case_path = tmp_path / f"maintenance-case-{index}"
        case_path.mkdir()
        rejected = run_public_edge_verifier(
            case_path,
            **(defaults | overrides),
        )
        assert rejected.returncode != 0
        assert "Public GSubs transport policy is invalid" in rejected.stderr


def test_roll_forward_maintenance_guard_requires_exact_local_runtime(
    tmp_path: Path,
) -> None:
    guard_probe = tmp_path / "maintenance-guard-probe.sh"
    write_executable(
        guard_probe,
        f"""#!/bin/sh
set -eu
ROOT_DIR={REPOSITORY_ROOT}
compose() {{
  printf '%s\\n' "$*" >> "$FAKE_COMPOSE_LOG"
  case "$*" in
    "ps -q edge")
      [ "${{FAKE_EDGE_RUNNING:-1}}" = 1 ] && printf 'edge-container\\n'
      ;;
    "ps -a -q app-edge")
      [ "${{FAKE_APP_EDGE_EXISTS:-1}}" = 1 ] && printf 'app-edge-container\\n'
      ;;
    *) return 1 ;;
  esac
}}
docker() {{
  case "$*" in
    "inspect --format "*" app-edge-container")
      printf '%s\\n' "${{FAKE_APP_EDGE_RUNNING:-false}}"
      ;;
    "inspect --format "*" edge-container")
      printf '%s\\n' "${{FAKE_EDGE_HEALTH:-healthy}}"
      ;;
    "exec edge-container sha256sum /etc/caddy/Caddyfile")
      printf '%s  /etc/caddy/Caddyfile\\n' "$FAKE_RUNTIME_GATEWAY_SHA"
      ;;
    *) return 1 ;;
  esac
}}
. "$ROOT_DIR/deploy/hetzner/lib/deploy-guards.sh"
if [ "${{FAKE_PROBE_ACTION:-guard}}" = prepare ]; then
  verified_maintenance_roll_forward=1
  prepare_public_gateway
else
  public_gateway_is_reviewed_maintenance
fi
""",
    )
    reviewed_sha = hashlib.sha256(
        (DEPLOYMENT_ROOT / "gateway" / "Caddyfile").read_bytes(),
    ).hexdigest()
    environment = os.environ.copy()
    environment["FAKE_RUNTIME_GATEWAY_SHA"] = reviewed_sha
    environment["FAKE_COMPOSE_LOG"] = str(tmp_path / "compose.log")

    accepted = subprocess.run(
        [str(guard_probe)],
        check=False,
        capture_output=True,
        env=environment,
        text=True,
        timeout=10,
    )
    assert accepted.returncode == 0, accepted.stderr

    for index, overrides in enumerate(
        (
            {"FAKE_EDGE_RUNNING": "0"},
            {"FAKE_APP_EDGE_EXISTS": "0"},
            {"FAKE_APP_EDGE_RUNNING": "true"},
            {"FAKE_EDGE_HEALTH": "unhealthy"},
            {"FAKE_RUNTIME_GATEWAY_SHA": "0" * 64},
        ),
    ):
        rejected_environment = environment | overrides
        rejected = subprocess.run(
            [str(guard_probe)],
            check=False,
            capture_output=True,
            env=rejected_environment,
            text=True,
            timeout=10,
        )
        assert rejected.returncode != 0, f"unsafe case {index} was accepted"

    prepare_environment = environment | {
        "FAKE_PROBE_ACTION": "prepare",
        "FAKE_COMPOSE_LOG": str(tmp_path / "prepare-compose.log"),
    }
    prepared = subprocess.run(
        [str(guard_probe)],
        check=False,
        capture_output=True,
        env=prepare_environment,
        text=True,
        timeout=10,
    )
    assert prepared.returncode == 0, prepared.stderr
    prepare_commands = (tmp_path / "prepare-compose.log").read_text(encoding="utf-8")
    assert "up " not in prepare_commands
    assert "ps -a -q app-edge" in prepare_commands


def test_public_edge_policy_gates_deploy_verification_and_nightly_ci() -> None:
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    nightly = (REPOSITORY_ROOT / ".github" / "workflows" / "nightly-quality.yml").read_text(encoding="utf-8")
    gate = '"$ROOT_DIR/deploy/hetzner/verify-public-edge.sh"'

    # REGRESSION: loopback health and CI were green while the external QUIC
    # body path was unusably slow. Keep an externally observable guard before
    # production mutation, after candidate activation and every night.
    assert gate in deploy_script
    assert deploy_script.index(gate) < deploy_script.index(
        "privacy_continuity_bootstrap=0",
    )
    assert gate in verifier
    assert "./deploy/hetzner/verify-public-edge.sh" in nightly
    public_verifier = (DEPLOYMENT_ROOT / "verify-public-edge.sh").read_text(
        encoding="utf-8",
    )
    assert "--max-filesize 1048576" in public_verifier

    maintenance_gate = f"{gate} --maintenance"
    local_guard = "public_gateway_is_reviewed_maintenance"
    assert local_guard in deploy_script
    assert maintenance_gate in deploy_script
    assert deploy_script.index(local_guard) < deploy_script.index(maintenance_gate)
    guard_body = deploy_script.split(f"{local_guard}() {{", 1)[1].split("\n}", 1)[0]
    assert "compose ps -q edge" in guard_body
    assert "compose ps -a -q app-edge" in guard_body
    assert ".State.Running" in guard_body
    assert ".State.Health.Status" in guard_body
    assert "gateway/Caddyfile" in guard_body
    assert "sha256sum /etc/caddy/Caddyfile" in guard_body

    maintenance_flag = "verified_maintenance_roll_forward=1"
    prepare_body = deploy_script.split("prepare_public_gateway() {", 1)[1].split(
        "\n}",
        1,
    )[0]
    assert maintenance_flag in deploy_script
    assert deploy_script.index(maintenance_gate) < deploy_script.index(maintenance_flag)
    assert "public_gateway_is_reviewed_maintenance" in prepare_body
    assert "return 0" in prepare_body
    assert prepare_body.index("return 0") < prepare_body.index(
        "compose up -d --no-deps --force-recreate app-edge",
    )
