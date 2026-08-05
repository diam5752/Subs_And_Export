#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 [--candidate]" >&2
  exit 2
}

candidate_mode=0
if [ "${1:-}" = "--candidate" ]; then
  candidate_mode=1
  shift
fi
[ "$#" -eq 0 ] || usage

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"
STATE_FILE="$ROOT_DIR/.runtime/last-successful-release"
ERASURE_RECEIPT_FILE="$ROOT_DIR/.runtime/last-erasure-reconciliation"
CONTINUITY_STATE_FILE="$ROOT_DIR/.runtime/privacy-continuity-id"
ERASURE_ANCHOR_DIR="$ROOT_DIR/.runtime/privacy-erasure-anchor"
export SUBFRAME_ERASURE_ANCHOR_DIR="$ERASURE_ANCHOR_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo "Production env is required: $ENV_FILE" >&2
  exit 1
fi
if grep -Eq \
  '^[[:space:]]*(export[[:space:]]+)?(GSP_GCS_[A-Z0-9_]*|GOOGLE_APPLICATION_CREDENTIALS)[[:space:]]*=' \
  "$ENV_FILE"; then
  echo "Retired GCS settings remain in the production env." >&2
  exit 1
fi
if ! "$ROOT_DIR/deploy/hetzner/verify-gcs-retirement.sh"; then
  echo "Legacy GCS retirement evidence is missing or invalid." >&2
  exit 1
fi
if [ ! -f "$CONTINUITY_STATE_FILE" ] || [ -L "$CONTINUITY_STATE_FILE" ]; then
  echo "Live privacy continuity state is required: $CONTINUITY_STATE_FILE" >&2
  exit 1
fi
privacy_continuity_id=$(cat "$CONTINUITY_STATE_FILE")
if ! printf '%s\n' "$privacy_continuity_id" | grep -Eq '^[0-9a-f]{64}$'; then
  echo "Live privacy continuity state is malformed." >&2
  exit 1
fi
export SUBFRAME_PRIVACY_CONTINUITY_ID="$privacy_continuity_id"

env_value() {
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

release_sha="${SUBFRAME_RELEASE_SHA:-$(env_value SUBFRAME_RELEASE_SHA)}"
preview_port="${SUBFRAME_PREVIEW_PORT:-$(env_value SUBFRAME_PREVIEW_PORT)}"
preview_port="${preview_port:-18090}"
case "$preview_port" in
  *[!0-9]*|'')
    echo "SUBFRAME_PREVIEW_PORT must be numeric." >&2
    exit 1
    ;;
esac
if [ -z "$release_sha" ]; then
  echo "SUBFRAME_RELEASE_SHA is required." >&2
  exit 1
fi
google_client_id=$(env_value GOOGLE_CLIENT_ID)
if [ -z "$google_client_id" ]; then
  echo "Google client ID is required." >&2
  exit 1
fi
if [ -z "$(env_value ELEVENLABS_API_KEY)" ]; then
  echo "ElevenLabs production API key is required." >&2
  exit 1
fi
export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="$release_sha"

compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

assert_no_open_stripe_purchases_without_consumer_contract() {
  compose exec -T db sh -eu -c \
    'exec psql -X --no-password -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO $preflight$
DECLARE
    unsafe_count BIGINT;
BEGIN
    SELECT count(*)
    INTO unsafe_count
    FROM credit_purchases
    WHERE provider = 'stripe'
      AND fulfilled_at IS NULL
      AND status NOT IN ('expired', 'failed')
      AND (
          jsonb_typeof((snapshot::jsonb)->'consumer_contract')
              IS DISTINCT FROM 'object'
          OR COALESCE(
              (snapshot::jsonb)->>'consumer_contract_sha256',
              ''
          ) !~ '^[0-9a-f]{64}$'
      );

    IF unsafe_count <> 0 THEN
        RAISE EXCEPTION
            'Open Stripe purchase evidence preflight found % incompatible row(s).',
            unsafe_count;
    END IF;
END
$preflight$;
COMMIT;
SQL
}

assert_legacy_gcs_retirement_complete() {
  compose exec -T db sh -eu -c \
    'exec psql -X --no-password -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO $retirement$
DECLARE
    legacy_job_references BIGINT;
BEGIN
    IF to_regclass('public.gcs_uploads') IS NOT NULL THEN
        RAISE EXCEPTION 'Retired GCS upload-session table still exists.';
    END IF;

    SELECT count(*)
    INTO legacy_job_references
    FROM jobs
    WHERE result_data ? 'source_gcs_object';

    IF legacy_job_references <> 0 THEN
        RAISE EXCEPTION
            'Retired GCS job evidence remains in % row(s).',
            legacy_job_references;
    END IF;
END
$retirement$;
COMMIT;
SQL
}

compose config --quiet
for service in db backend frontend edge; do
  container_id=$(compose ps -q "$service")
  if [ -z "$container_id" ]; then
    echo "Missing container for service: $service" >&2
    exit 1
  fi
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")
  if [ "$health" != healthy ]; then
    echo "Service $service is not healthy: $health" >&2
    exit 1
  fi
done

backend_id=$(compose ps -q backend)
frontend_id=$(compose ps -q frontend)
backend_image=$(docker inspect --format '{{.Config.Image}}' "$backend_id")
frontend_image=$(docker inspect --format '{{.Config.Image}}' "$frontend_id")
[ "$backend_image" = "subframe-backend:$release_sha" ] || {
  echo "Backend image does not match release $release_sha." >&2
  exit 1
}
[ "$frontend_image" = "subframe-frontend:$release_sha" ] || {
  echo "Frontend image does not match release $release_sha." >&2
  exit 1
}

backend_environment=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$backend_id")
if printf '%s\n' "$backend_environment" | grep -Eq \
  '^(GSP_GCS_[A-Z0-9_]*|GOOGLE_APPLICATION_CREDENTIALS)='; then
  echo "Backend container still exposes retired GCS settings." >&2
  exit 1
fi
for expected in \
  GSP_APP_ENV=production \
  APP_ENV=production \
  GSP_MOCK_EXTERNAL_SERVICES=0 \
  GSP_ELEVENLABS_ENABLED=1 \
  GSP_ELEVENLABS_API_BASE=http://edge:8081/elevenlabs \
  GSP_PAID_CREDITS_ENABLED=1 \
  GSP_CONSUMER_POLICY_APPROVED=1 \
  GSP_DURABLE_CONFIRMATION_CHANNEL_READY=1 \
  GSP_ADJUSTMENT_WORKFLOW_READY=1 \
  GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0 \
  GSP_STRIPE_API_BASE=http://edge:8081/stripe \
  GSP_BILLING_ADMIN_USER_IDS= \
  STRIPE_SECRET_KEY= \
  STRIPE_WEBHOOK_SECRET= \
  OPENAI_API_KEY= \
  GROQ_API_KEY= \
  GOOGLE_CLIENT_SECRET= \
  GOOGLE_REDIRECT_URI= \
  GSP_GOOGLE_OAUTH_CERTS_URL=http://edge:8081/oauth2/v1/certs \
  GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600 \
  GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=100 \
  GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=10 \
  GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0.05 \
  GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER=1.25 \
  GSP_WORKSPACE_RETENTION_HOURS=24 \
  GSP_STALE_JOB_RETENTION_HOURS=6 \
  GSP_ORPHAN_RETENTION_HOURS=1 \
  GSP_CLEANUP_INTERVAL_MINUTES=15 \
  GSP_STORAGE_MIN_FREE_MB=2048 \
  GSP_RETENTION_CLEANUP_ENABLED=1 \
  GSP_ERASURE_JOURNAL_DIR=/privacy-erasure-journal \
  GSP_ERASURE_JOURNAL_RETENTION_DAYS=30 \
  GSP_ERASURE_JOURNAL_ANCHOR_PATH=/privacy-erasure-anchor/checkpoint.json \
  "GSP_ERASURE_JOURNAL_CONTINUITY_ID=$privacy_continuity_id"
do
  printf '%s\n' "$backend_environment" | grep -Fqx "$expected" || {
    echo "Missing safe runtime setting: $expected" >&2
    exit 1
  }
done

assert_existing_vm_local_volume() {
  volume_name=$1
  volume_driver=$(docker volume inspect --format '{{.Driver}}' "$volume_name") || {
    echo "Existing-VM storage volume is missing: $volume_name" >&2
    exit 1
  }
  if [ "$volume_driver" != local ]; then
    echo "Existing-VM storage volume must use Docker's local driver: $volume_name" >&2
    exit 1
  fi
  volume_options=$(docker volume inspect --format '{{json .Options}}' "$volume_name")
  case "$volume_options" in
    null|'{}') ;;
    *)
      echo "Existing-VM storage volume must not use external driver options: $volume_name" >&2
      exit 1
      ;;
  esac
  volume_mountpoint=$(docker volume inspect --format '{{.Mountpoint}}' "$volume_name")
  if [ ! -d "$volume_mountpoint" ] || [ -L "$volume_mountpoint" ]; then
    echo "Existing-VM storage volume mountpoint is invalid: $volume_name" >&2
    exit 1
  fi
  host_root_device=$(stat -c %d /)
  volume_device=$(stat -c %d "$volume_mountpoint")
  if [ "$volume_device" != "$host_root_device" ]; then
    echo "Existing-VM storage volume is not on the host root filesystem: $volume_name" >&2
    exit 1
  fi
}

assert_existing_vm_local_volume subframe-app-data
assert_existing_vm_local_volume subframe-erasure-journal

assert_existing_vm_anchor_bind() {
  if [ ! -d "$ERASURE_ANCHOR_DIR" ] || [ -L "$ERASURE_ANCHOR_DIR" ]; then
    echo "Erasure-journal anchor source must be a real host directory." >&2
    exit 1
  fi
  canonical_anchor_dir=$(readlink -f -- "$ERASURE_ANCHOR_DIR") || {
    echo "Erasure-journal anchor source cannot be resolved." >&2
    exit 1
  }
  if [ "$canonical_anchor_dir" != "$ERASURE_ANCHOR_DIR" ]; then
    echo "Erasure-journal anchor source must not traverse a symlink." >&2
    exit 1
  fi
  if [ "$(stat -c %a "$ERASURE_ANCHOR_DIR")" != 700 ]; then
    echo "Erasure-journal anchor directory permissions are unsafe." >&2
    exit 1
  fi
  if [ "$(stat -c %u:%g "$ERASURE_ANCHOR_DIR")" != 10001:10001 ]; then
    echo "Erasure-journal anchor directory ownership is unsafe." >&2
    exit 1
  fi
  host_root_device=$(stat -c %d /)
  anchor_device=$(stat -c %d "$ERASURE_ANCHOR_DIR")
  if [ "$anchor_device" != "$host_root_device" ]; then
    echo "Erasure-journal anchor is not on the host root filesystem." >&2
    exit 1
  fi
  anchor_mount=$(docker inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/privacy-erasure-anchor"}}{{.Type}}|{{.Source}}|{{.RW}}{{end}}{{end}}' \
    "$backend_id")
  if [ "$anchor_mount" != "bind|$ERASURE_ANCHOR_DIR|true" ]; then
    echo "Backend erasure-journal anchor must use its dedicated writable host bind." >&2
    exit 1
  fi
}

assert_existing_vm_anchor_bind

journal_mount=$(docker inspect --format \
  '{{range .Mounts}}{{if eq .Destination "/privacy-erasure-journal"}}{{.Name}}|{{.RW}}{{end}}{{end}}' \
  "$backend_id")
if [ "$journal_mount" != "subframe-erasure-journal|true" ]; then
  echo "Backend erasure journal must use its dedicated writable volume." >&2
  exit 1
fi
if ! docker exec "$backend_id" python -c '
import os
from pathlib import Path

from backend.app.core.erasure_journal import configured_erasure_journal

expected = os.environ["GSP_ERASURE_JOURNAL_CONTINUITY_ID"]
marker = Path("/privacy-erasure-journal/.continuity-id")
if marker.is_symlink() or not marker.is_file():
    raise SystemExit("Live erasure journal continuity marker is missing.")
if marker.read_text(encoding="ascii").strip() != expected:
    raise SystemExit("Live erasure journal continuity marker does not match.")
configured_erasure_journal().read_all()
'; then
  echo "Erasure-journal integrity validation failed in the running backend." >&2
  exit 1
fi
privacy_relay_id=$(compose ps -q privacy-relay)
if [ -n "$privacy_relay_id" ]; then
  echo "Temporary privacy relay must be stopped after erasure reconciliation." >&2
  exit 1
fi
backup_retention_days="${SUBFRAME_BACKUP_RETENTION_DAYS:-$(env_value SUBFRAME_BACKUP_RETENTION_DAYS)}"
backup_retention_days="${backup_retention_days:-14}"
case "$backup_retention_days" in
  ''|*[!0-9]*)
    echo "SUBFRAME_BACKUP_RETENTION_DAYS must be a positive integer." >&2
    exit 1
    ;;
esac
if [ "$backup_retention_days" -eq 0 ] || [ 30 -lt "$backup_retention_days" ]; then
  echo "Erasure journal retention must cover the complete backup retention window." >&2
  exit 1
fi
printf '%s\n' "$backend_environment" | grep -Fqx "GOOGLE_CLIENT_ID=$google_client_id" || {
  echo "Backend Google client ID does not match the release environment." >&2
  exit 1
}
if ! docker exec "$backend_id" python -c '
from backend.app.core.config import settings
from backend.app.services.llm_utils import resolve_elevenlabs_api_key

if not settings.paid_credit_checkout_enabled:
    raise SystemExit("Paid Checkout and every independent launch gate must be enabled.")
if settings.stripe_automatic_tax_enabled:
    raise SystemExit("Stripe Automatic Tax must remain disabled for the reviewed tax-inclusive catalog.")
if settings.mock_external_services:
    raise SystemExit("Production Scribe must not run in mock mode.")
if not settings.elevenlabs_enabled:
    raise SystemExit("Production Scribe must be enabled.")
if settings.elevenlabs_api_base != "http://edge:8081/elevenlabs":
    raise SystemExit("Production Scribe must use the scoped internal relay.")
expected_budgets = (100.0, 10.0, 0.05, 1.25)
actual_budgets = (
    settings.external_provider_monthly_budget_usd,
    settings.external_provider_daily_budget_usd,
    settings.external_provider_per_request_budget_usd,
    settings.external_provider_price_safety_multiplier,
)
if actual_budgets != expected_budgets:
    raise SystemExit("Production Scribe budget caps do not match the reviewed release.")
if not resolve_elevenlabs_api_key():
    raise SystemExit("Production Scribe API key is unavailable.")
settings.assert_paid_credits_configuration()
'; then
  echo "Production provider or Stripe staging configuration is incomplete or unsafe." >&2
  exit 1
fi
if ! docker exec "$backend_id" alembic current --check-heads >/dev/null; then
  echo "Production database is not at the Alembic head revision." >&2
  exit 1
fi
if ! assert_legacy_gcs_retirement_complete; then
  echo "Legacy GCS retirement invariant failed after database migration." >&2
  exit 1
fi
if ! assert_no_open_stripe_purchases_without_consumer_contract; then
  echo "Open Stripe purchase invariant failed after database migration." >&2
  exit 1
fi

receipt_value() {
  sed -n "s/^$1=//p" "$ERASURE_RECEIPT_FILE" | tail -n 1
}

timestamp_epoch() (
  raw_timestamp=$1
  if ! printf '%s\n' "$raw_timestamp" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'; then
    return 1
  fi
  iso_timestamp=$(printf '%s\n' "$raw_timestamp" | sed \
    's/^\(....\)\(..\)\(..\)T\(..\)\(..\)\(..\)Z$/\1-\2-\3T\4:\5:\6Z/')
  date -u -d "$iso_timestamp" +%s 2>/dev/null
)

if [ ! -f "$ERASURE_RECEIPT_FILE" ] || [ -L "$ERASURE_RECEIPT_FILE" ]; then
  echo "A successful erasure reconciliation receipt is required." >&2
  exit 1
fi
receipt_line_count=$(awk 'NF { count += 1 } END { print count + 0 }' \
  "$ERASURE_RECEIPT_FILE")
if [ "$receipt_line_count" -ne 4 ] ||
  [ "$(receipt_value reconciled)" != true ] ||
  [ "$(receipt_value release_sha)" != "$release_sha" ] ||
  [ "$(receipt_value journal_path)" != /privacy-erasure-journal ]; then
  echo "Erasure reconciliation receipt is malformed or belongs to another release." >&2
  exit 1
fi
reconciled_at=$(receipt_value completed_at_utc)
if ! reconciled_epoch=$(timestamp_epoch "$reconciled_at"); then
  echo "Erasure reconciliation receipt timestamp is invalid." >&2
  exit 1
fi
backend_started_at=$(docker inspect --format '{{.State.StartedAt}}' "$backend_id")
if ! backend_started_epoch=$(date -u -d "$backend_started_at" +%s 2>/dev/null); then
  echo "Could not validate backend start time for erasure reconciliation." >&2
  exit 1
fi
now_epoch=$(date -u +%s)
if [ "$reconciled_epoch" -lt "$backend_started_epoch" ] ||
  [ "$reconciled_epoch" -gt "$now_epoch" ]; then
  echo "Erasure reconciliation must complete after the current backend starts and before verification." >&2
  exit 1
fi
google_oauth_certs_http=$(docker exec "$backend_id" python -c \
  'import os, urllib.request; response = urllib.request.urlopen(os.environ["GSP_GOOGLE_OAUTH_CERTS_URL"], timeout=10); print(response.status)')
[ "$google_oauth_certs_http" = 200 ] || {
  echo "Google OAuth certificate relay is unavailable: $google_oauth_certs_http" >&2
  exit 1
}
stripe_relay_http=$(docker exec "$backend_id" python -c '
import urllib.error
import urllib.request

base = "http://edge:8081/stripe/v1/payment_intents/pi_gsubs_relay_probe"
probes = ((base, "GET"), (f"{base}/capture", "POST"), (f"{base}/cancel", "POST"))
statuses = []
for url, method in probes:
    request = urllib.request.Request(url, data=(b"" if method == "POST" else None), method=method)
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        statuses.append(str(exc.code))
    except urllib.error.URLError:
        statuses.append("unavailable")
    else:
        statuses.append(str(response.status))
print(",".join(statuses))
')
[ "$stripe_relay_http" = "401,401,401" ] || {
  echo "Stripe API relay is unavailable or unexpectedly permissive: $stripe_relay_http" >&2
  exit 1
}
elevenlabs_relay_http=$(docker exec "$backend_id" python -c '
import urllib.error
import urllib.request

base = "http://edge:8081/elevenlabs"
probes = (
    (f"{base}/v1/speech-to-text", "POST"),
    (f"{base}/v1/speech-to-text", "GET"),
    (f"{base}/v1/models", "POST"),
    (f"{base}/v1/speech-to-text/transcripts/gsubs_relay_probe", "DELETE"),
    (f"{base}/v1/speech-to-text/transcripts/invalid/path", "DELETE"),
)
statuses = []
for url, method in probes:
    request = urllib.request.Request(
        url,
        data=(b"" if method == "POST" else None),
        method=method,
    )
    try:
        response = urllib.request.urlopen(request, timeout=15)
    except urllib.error.HTTPError as exc:
        statuses.append(str(exc.code))
    except urllib.error.URLError:
        statuses.append("unavailable")
    else:
        statuses.append(str(response.status))
print(",".join(statuses))
')
case "$elevenlabs_relay_http" in
  400,404,404,401,404|400,404,404,404,404|401,404,404,401,404|401,404,404,404,404|422,404,404,401,404|422,404,404,404,404)
    ;;
  *)
    echo "ElevenLabs API relay is unavailable or unexpectedly permissive: $elevenlabs_relay_http" >&2
    exit 1
    ;;
esac

health_json=""
catalog_json=""
if command -v curl >/dev/null 2>&1; then
  health_json=$(curl -fsS "http://127.0.0.1:$preview_port/health")
  catalog_json=$(curl -fsS "http://127.0.0.1:$preview_port/billing/catalog")
  curl -fsS "http://127.0.0.1:$preview_port/" >/dev/null
elif command -v wget >/dev/null 2>&1; then
  health_json=$(wget -qO- "http://127.0.0.1:$preview_port/health")
  catalog_json=$(wget -qO- "http://127.0.0.1:$preview_port/billing/catalog")
  wget -qO- "http://127.0.0.1:$preview_port/" >/dev/null
else
  echo "curl or wget is required for loopback verification." >&2
  exit 1
fi
printf '%s' "$health_json" | docker exec -i "$backend_id" python -c '
import json
import sys

health = json.load(sys.stdin)
if health.get("status") != "ok":
    raise SystemExit("Production health endpoint must report status=ok")
if health.get("app_env") != "production":
    raise SystemExit("Production health endpoint must report app_env=production")
'
printf '%s' "$catalog_json" | docker exec -i "$backend_id" python -c '
import json
import sys

catalog = json.load(sys.stdin)
if catalog.get("checkout_enabled") is not True:
    raise SystemExit("Production billing catalog must report checkout_enabled=true")
if catalog.get("consumer_contract_status") != "approved":
    raise SystemExit("Production billing catalog must expose the approved consumer contract")
if not isinstance(catalog.get("consumer_contract"), dict):
    raise SystemExit("Production billing catalog must publish the approved consumer contract")
'

if [ "$candidate_mode" -eq 0 ]; then
  if [ ! -f "$STATE_FILE" ] || [ -L "$STATE_FILE" ] ||
    [ "$(cat "$STATE_FILE")" != "$release_sha" ]; then
    echo "Recorded release does not match $release_sha." >&2
    exit 1
  fi
fi

if [ "$candidate_mode" -eq 1 ]; then
  printf 'Verified gsubs candidate release %s on loopback port %s.\n' \
    "$release_sha" \
    "$preview_port"
else
  printf 'Verified gsubs release %s on loopback port %s.\n' \
    "$release_sha" \
    "$preview_port"
fi
