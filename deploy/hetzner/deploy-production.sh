#!/bin/sh
set -eu
umask 077

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"
STATE_DIR="$ROOT_DIR/.runtime"
STATE_FILE="$STATE_DIR/last-successful-release"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing production env: $ENV_FILE" >&2
  exit 1
fi

release_sha=$(git -C "$ROOT_DIR" rev-parse HEAD)
configured_sha=$(sed -n 's/^SUBFRAME_RELEASE_SHA=//p' "$ENV_FILE" | tail -n 1)
if [ "$configured_sha" != "$release_sha" ]; then
  echo "SUBFRAME_RELEASE_SHA must equal checked-out HEAD ($release_sha)." >&2
  exit 1
fi

export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="$release_sha"
previous_sha=""
if [ -f "$STATE_FILE" ]; then
  previous_sha=$(cat "$STATE_FILE")
fi

compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

rollback() {
  if [ -n "$previous_sha" ] && docker image inspect "subframe-backend:$previous_sha" >/dev/null 2>&1; then
    echo "Deployment failed; rolling back to $previous_sha" >&2
    SUBFRAME_RELEASE_SHA="$previous_sha" compose up -d --no-build
  fi
}
trap rollback INT TERM HUP

compose config --quiet
if ! compose build --pull backend frontend; then
  rollback
  exit 1
fi
if ! compose up -d db backend frontend edge; then
  rollback
  exit 1
fi

attempt=0
while [ "$attempt" -lt 60 ]; do
  backend_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-backend-1 2>/dev/null || true)
  frontend_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-frontend-1 2>/dev/null || true)
  edge_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-edge-1 2>/dev/null || true)
  if [ "$backend_health" = healthy ] && [ "$frontend_health" = healthy ] && [ "$edge_health" = healthy ]; then
    install -d -m 700 "$STATE_DIR"
    printf '%s\n' "$release_sha" > "$STATE_FILE"
    trap - INT TERM HUP
    compose ps
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 2
done

compose ps >&2
compose logs --tail=120 backend frontend edge >&2
rollback
exit 1
