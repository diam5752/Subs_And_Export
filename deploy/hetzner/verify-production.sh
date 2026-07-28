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

if [ ! -f "$ENV_FILE" ]; then
  echo "Production env is required: $ENV_FILE" >&2
  exit 1
fi

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
for expected in \
  GSP_APP_ENV=production \
  APP_ENV=production \
  GSP_MOCK_EXTERNAL_SERVICES=1 \
  GSP_ELEVENLABS_ENABLED=0 \
  GSP_PAID_CREDITS_ENABLED=0 \
  GSP_CONSUMER_POLICY_APPROVED=0 \
  GSP_DURABLE_CONFIRMATION_CHANNEL_READY=0 \
  GSP_ADJUSTMENT_WORKFLOW_READY=0 \
  GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0 \
  GSP_STRIPE_API_BASE=http://edge:8081/stripe \
  GSP_BILLING_ADMIN_USER_IDS= \
  STRIPE_SECRET_KEY= \
  STRIPE_WEBHOOK_SECRET= \
  OPENAI_API_KEY= \
  GROQ_API_KEY= \
  ELEVENLABS_API_KEY= \
  GSP_GCS_BUCKET= \
  GOOGLE_APPLICATION_CREDENTIALS= \
  GOOGLE_CLIENT_SECRET= \
  GOOGLE_REDIRECT_URI= \
  GSP_GOOGLE_OAUTH_CERTS_URL=http://edge:8081/oauth2/v1/certs \
  GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600 \
  GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0 \
  GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=0 \
  GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0 \
  GSP_WORKSPACE_RETENTION_HOURS=24 \
  GSP_STALE_JOB_RETENTION_HOURS=6 \
  GSP_ORPHAN_RETENTION_HOURS=1 \
  GSP_CLEANUP_INTERVAL_MINUTES=15 \
  GSP_STORAGE_MIN_FREE_MB=2048 \
  GSP_RETENTION_CLEANUP_ENABLED=1
do
  printf '%s\n' "$backend_environment" | grep -Fqx "$expected" || {
    echo "Missing safe runtime setting: $expected" >&2
    exit 1
  }
done
printf '%s\n' "$backend_environment" | grep -Fqx "GOOGLE_CLIENT_ID=$google_client_id" || {
  echo "Backend Google client ID does not match the release environment." >&2
  exit 1
}
if ! docker exec "$backend_id" python -c '
from backend.app.core.config import settings

if settings.paid_credits_enabled:
    raise SystemExit("Paid Checkout must remain disabled during Stripe staging.")
if settings.consumer_policy_approved:
    raise SystemExit("Consumer policy approval must remain disabled during Stripe staging.")
if settings.durable_confirmation_channel_ready:
    raise SystemExit("Durable confirmation approval must remain disabled during Stripe staging.")
if settings.adjustment_workflow_ready:
    raise SystemExit("Adjustment workflow approval must remain disabled during Stripe staging.")
if settings.stripe_automatic_tax_enabled:
    raise SystemExit("Stripe Automatic Tax must remain disabled during Stripe staging.")
settings.assert_stripe_stage_configuration()
'; then
  echo "Stripe staging configuration is incomplete or unsafe." >&2
  exit 1
fi
if ! docker exec "$backend_id" alembic current --check-heads >/dev/null; then
  echo "Production database is not at the Alembic head revision." >&2
  exit 1
fi
if ! assert_no_open_stripe_purchases_without_consumer_contract; then
  echo "Open Stripe purchase invariant failed after database migration." >&2
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
if catalog.get("checkout_enabled") is not False:
    raise SystemExit("Production billing catalog must keep checkout_enabled=false")
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
