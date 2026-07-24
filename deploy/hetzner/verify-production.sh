#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
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

export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="$release_sha"

compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
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
  GSP_MOCK_EXTERNAL_SERVICES=1 \
  GSP_ELEVENLABS_ENABLED=0 \
  GSP_PAID_CREDITS_ENABLED=0 \
  GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0 \
  GSP_STRIPE_RESTRICTED_KEY= \
  GSP_STRIPE_WEBHOOK_SECRET= \
  GSP_STRIPE_PRICE_STARTER= \
  GSP_STRIPE_PRICE_CORE= \
  GSP_STRIPE_PRICE_PRO= \
  STRIPE_SECRET_KEY= \
  STRIPE_WEBHOOK_SECRET= \
  OPENAI_API_KEY= \
  GROQ_API_KEY= \
  ELEVENLABS_API_KEY= \
  GSP_GCS_BUCKET= \
  GOOGLE_APPLICATION_CREDENTIALS= \
  GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0 \
  GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=0 \
  GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0
do
  printf '%s\n' "$backend_environment" | grep -Fqx "$expected" || {
    echo "Missing safe runtime setting: $expected" >&2
    exit 1
  }
done

if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:$preview_port/health" >/dev/null
  curl -fsS "http://127.0.0.1:$preview_port/billing/catalog" >/dev/null
  curl -fsS "http://127.0.0.1:$preview_port/" >/dev/null
elif command -v wget >/dev/null 2>&1; then
  wget -qO- "http://127.0.0.1:$preview_port/health" >/dev/null
  wget -qO- "http://127.0.0.1:$preview_port/billing/catalog" >/dev/null
  wget -qO- "http://127.0.0.1:$preview_port/" >/dev/null
else
  echo "curl or wget is required for loopback verification." >&2
  exit 1
fi

if [ ! -f "$STATE_FILE" ] || [ "$(cat "$STATE_FILE")" != "$release_sha" ]; then
  echo "Recorded release does not match $release_sha." >&2
  exit 1
fi

printf 'Verified SUBFRAME release %s on loopback port %s.\n' "$release_sha" "$preview_port"
