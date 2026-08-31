from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from backend.tests.hetzner_deployment_test_support import (
    DEPLOYMENT_ROOT,
    REPOSITORY_ROOT,
    copy_release_script,
    deployment_text,
    install_passing_public_edge_fixture,
    relay_validator_source,
    run_public_edge_verifier,
    write_executable,
    write_gcs_retirement_evidence,
)


def test_candidate_verifier_failure_preserves_previous_release_state(
    tmp_path: Path,
) -> None:
    repository = tmp_path / "repository"
    deployment_root = repository / "deploy" / "hetzner"
    deployment_root.mkdir(parents=True)
    copy_release_script("deploy-production.sh", deployment_root)
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

    assert (
        'test: ["CMD", "wget", "-q", "-O", "/dev/null", "http://localhost:8080/.well-known/gsubs-edge-health"]'
        in healthcheck
    )
    assert "--spider" not in healthcheck


def test_stable_gateway_serves_maintenance_while_the_private_app_edge_is_closed() -> None:
    """REGRESSION: privacy-safe deploy cutovers surfaced a raw tunnel 502."""
    compose = deployment_text("docker-compose.production.yml")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")
    gateway = deployment_text("gateway/Caddyfile")

    backend = compose.split("  backend:", 1)[1].split("\n  feedback-worker:", 1)[0]
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

    # REGRESSION: after the stable gateway split, the backend still addressed
    # provider relays through `edge`; that service intentionally left the
    # private network, so DNS resolution and every relay canary failed.
    assert "      - private" in backend
    assert "      - private" in app_edge
    assert 'GSP_GOOGLE_OAUTH_CERTS_URL: "http://app-edge:8081/oauth2/v1/certs"' in backend
    assert 'GSP_STRIPE_API_BASE: "http://app-edge:8081/stripe"' in backend
    assert 'GSP_ELEVENLABS_API_BASE: "http://app-edge:8081/elevenlabs"' in backend
    assert "http://edge:8081" not in backend
    assert 'base = "http://app-edge:8081"' in verifier
    assert 'base = "http://edge:8081"' not in verifier


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
    backend_matcher = next(line.strip() for line in caddyfile.splitlines() if line.strip().startswith("@backend path "))
    assert caddyfile.count(feedback_matcher) == 1
    assert caddyfile.index(feedback_matcher) < caddyfile.index("@backend path")
    feedback_handler = caddyfile.split(feedback_matcher, 1)[1].split(
        "@observability_events",
        1,
    )[0]
    assert "request_body" in feedback_handler
    assert "max_size 16KB" in feedback_handler
    assert feedback_handler.count("reverse_proxy backend:8080") == 1
    assert "/feedback" not in backend_matcher
    assert "Public feedback request-body cap must be exactly 16KB" in verifier
    assert "Feedback must not bypass its body cap" in verifier


def test_edge_caps_observability_events_before_the_generic_backend_proxy() -> None:
    caddyfile = deployment_text("Caddyfile")
    verifier = deployment_text("verify-production.sh")

    matcher = "@observability_events path /observability/events"
    assert caddyfile.count(matcher) == 1
    assert caddyfile.index(matcher) < caddyfile.index("@backend path")
    handler = caddyfile.split(matcher, 1)[1].split("@backend path", 1)[0]
    assert "request_body" in handler
    assert "max_size 4KB" in handler
    assert handler.count("reverse_proxy backend:8080") == 1
    assert "Operational telemetry request-body cap must be exactly 4KB" in verifier


def test_google_oauth_certificates_use_a_scoped_internal_edge_relay() -> None:
    """REGRESSION: the internal-only backend could not resolve Google's cert host."""
    compose = deployment_text("docker-compose.production.yml")
    caddyfile = deployment_text("Caddyfile")
    deploy_script = deployment_text("deploy-production.sh")
    verifier = deployment_text("verify-production.sh")

    assert "internal: true" in compose
    assert 'GSP_GOOGLE_OAUTH_CERTS_URL: "http://app-edge:8081/oauth2/v1/certs"' in compose
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
    assert 'GSP_STRIPE_API_BASE: "http://app-edge:8081/stripe"' in compose
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
    assert 'GSP_ELEVENLABS_API_BASE: "http://app-edge:8081/elevenlabs"' in compose
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
        '  \'from pathlib import Path; import os; root = Path("/app"); '
        "assert all(os.access(path, os.R_OK | (os.X_OK if path.is_dir() else 0)) "
        'for path in (root, *root.rglob("*"))); import main\''
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
    nightly = (REPOSITORY_ROOT / ".github" / "workflows" / "nightly-quality.yml").read_text(encoding="utf-8")
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
        "lib/deploy-guards.sh",
        "lib/deploy-transition.sh",
        "lib/verify-contracts.sh",
        "lib/verify-edge.sh",
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
