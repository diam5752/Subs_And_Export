#!/bin/sh
set -eu
umask 077

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"
STATE_DIR="$ROOT_DIR/.runtime"
STATE_FILE="$STATE_DIR/last-successful-release"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing production env: $ENV_FILE" >&2
  exit 1
fi

worktree_status=$(git -C "$ROOT_DIR" status --porcelain --untracked-files=normal)
if [ -n "$worktree_status" ]; then
  echo "Refusing to deploy a dirty worktree; commit or remove tracked and non-ignored untracked changes first." >&2
  printf '%s\n' "$worktree_status" >&2
  exit 1
fi

release_sha=$(git -C "$ROOT_DIR" rev-parse HEAD)
configured_sha=$(sed -n 's/^SUBFRAME_RELEASE_SHA=//p' "$ENV_FILE" | tail -n 1)
if [ "$configured_sha" != "$release_sha" ]; then
  echo "SUBFRAME_RELEASE_SHA must equal checked-out HEAD ($release_sha)." >&2
  exit 1
fi

allow_schema_compatible_rollback="${SUBFRAME_ALLOW_SCHEMA_COMPATIBLE_ROLLBACK:-0}"
case "$allow_schema_compatible_rollback" in
  0|1) ;;
  *)
    echo "SUBFRAME_ALLOW_SCHEMA_COMPATIBLE_ROLLBACK must be 0 or 1." >&2
    exit 1
    ;;
esac

export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="$release_sha"
previous_sha=""
if [ -e "$STATE_FILE" ] || [ -L "$STATE_FILE" ]; then
  if [ ! -f "$STATE_FILE" ] || [ -L "$STATE_FILE" ]; then
    echo "Previous release state must be a regular file: $STATE_FILE" >&2
    exit 1
  fi
  previous_sha=$(cat "$STATE_FILE")
  if ! printf '%s\n' "$previous_sha" | grep -Eq '^[0-9A-Fa-f]{40}$'; then
    echo "Previous release state does not contain a valid Git SHA." >&2
    exit 1
  fi
fi

restore_drill_receipt="$STATE_DIR/last-backup-restore-drill"
schema_change=1
if [ -n "$previous_sha" ] && \
  git -C "$ROOT_DIR" cat-file -e "$previous_sha^{commit}" 2>/dev/null &&
  git -C "$ROOT_DIR" diff --quiet "$previous_sha" "$release_sha" -- \
    backend/alembic/versions; then
  schema_change=0
fi

receipt_value() {
  sed -n "s/^$1=//p" "$restore_drill_receipt" | tail -n 1
}

receipt_timestamp_epoch() (
  raw_timestamp=$1
  if ! printf '%s\n' "$raw_timestamp" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'; then
    return 1
  fi
  iso_timestamp=$(printf '%s\n' "$raw_timestamp" | sed \
    's/^\(....\)\(..\)\(..\)T\(..\)\(..\)\(..\)Z$/\1-\2-\3T\4:\5:\6Z/')
  timestamp_epoch=$(date -u -d "$iso_timestamp" +%s 2>/dev/null) || return 1
  roundtrip_timestamp=$(date -u -d "@$timestamp_epoch" +%Y%m%dT%H%M%SZ 2>/dev/null) ||
    return 1
  [ "$roundtrip_timestamp" = "$raw_timestamp" ] || return 1
  printf '%s\n' "$timestamp_epoch"
)

if [ "$schema_change" -eq 1 ]; then
  if [ ! -f "$restore_drill_receipt" ] || [ -L "$restore_drill_receipt" ]; then
    echo "Schema-changing releases require a successful backup restore drill." >&2
    echo "Run verify-backup.sh --drill for this exact release first." >&2
    exit 1
  fi
  backup_release_sha=$(receipt_value backup_release_sha)
  backup_created_at=$(receipt_value backup_created_at_utc)
  verified_at=$(receipt_value verified_at_utc)
  if [ "$backup_release_sha" != "$release_sha" ] ||
    [ "$(receipt_value target_release_sha)" != "$release_sha" ] ||
    [ "$(receipt_value restore_drill)" != true ] ||
    [ "$(receipt_value independent_backup_copy_verified)" != true ] ||
    [ "$(receipt_value ciphertext_checksums)" != true ] ||
    [ "$(receipt_value age_decrypt)" != true ] ||
    [ "$(receipt_value pg_restore_archive)" != true ] ||
    [ "$(receipt_value tar_archive)" != true ] ||
    [ "$(receipt_value database_restore)" != true ] ||
    [ "$(receipt_value database_removed_before_app_restore)" != true ] ||
    [ "$(receipt_value volume_restore)" != true ] ||
    [ "$(receipt_value sequential_restore)" != true ] ||
    [ "$(receipt_value restore_size_multiplier)" != 2 ] ||
    [ "$(receipt_value restore_fixed_reserve_bytes)" != 10737418240 ] ||
    [ "$(receipt_value schema_rollback_evidence)" != postgres_dump ] ||
    [ "$(receipt_value app_data_authoritative)" != false ] ||
    [ "$(receipt_value cleanup)" != true ]; then
    echo "Schema-changing releases require a successful backup restore drill receipt for $release_sha." >&2
    exit 1
  fi
  if ! backup_created_epoch=$(receipt_timestamp_epoch "$backup_created_at") ||
    ! verified_epoch=$(receipt_timestamp_epoch "$verified_at"); then
    echo "Restore-drill receipt timestamps are invalid; GNU/Linux UTC date semantics are required." >&2
    exit 1
  fi
  now_epoch=$(date -u +%s)
  if [ "$backup_created_epoch" -gt "$now_epoch" ] ||
    [ "$verified_epoch" -gt "$now_epoch" ]; then
    echo "Restore-drill receipt timestamps cannot be in the future." >&2
    exit 1
  fi
  if [ "$backup_created_epoch" -gt "$verified_epoch" ]; then
    echo "Restore-drill receipt timestamps are not ordered: backup must precede verification." >&2
    exit 1
  fi
  max_restore_drill_age_seconds=86400
  backup_age_seconds=$((now_epoch - backup_created_epoch))
  verification_age_seconds=$((now_epoch - verified_epoch))
  if [ "$backup_age_seconds" -gt "$max_restore_drill_age_seconds" ] ||
    [ "$verification_age_seconds" -gt "$max_restore_drill_age_seconds" ]; then
    echo "Restore-drill receipt is older than 24 hours; create and verify a fresh backup." >&2
    exit 1
  fi
fi

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

rollback() {
  if [ "$allow_schema_compatible_rollback" != 1 ]; then
    echo "Deployment failed; automatic rollback is disabled because the database schema may have advanced." >&2
    echo "Keep the current deployment state for diagnosis and deploy a corrected roll-forward release." >&2
    return 0
  fi

  if [ -z "$previous_sha" ]; then
    echo "Schema-compatible rollback was requested, but no previous release is recorded." >&2
    return 0
  fi
  if ! docker image inspect "subframe-backend:$previous_sha" >/dev/null 2>&1; then
    echo "Schema-compatible rollback was requested, but image subframe-backend:$previous_sha is unavailable." >&2
    return 0
  fi

  echo "Explicit schema-compatible rollback requested; restoring $previous_sha." >&2
  if ! SUBFRAME_RELEASE_SHA="$previous_sha" compose up -d --no-build; then
    echo "Schema-compatible rollback failed; manual recovery is required." >&2
  fi
  return 0
}

state_temp=""

cleanup_state_temp() {
  if [ -n "$state_temp" ]; then
    rm -f -- "$state_temp"
    state_temp=""
  fi
}

trap cleanup_state_temp EXIT

on_signal() {
  trap - INT TERM HUP
  cleanup_state_temp
  rollback
  exit 1
}

compose config --quiet
if ! compose run --rm --no-deps --entrypoint caddy edge validate \
  --config /etc/caddy/Caddyfile --adapter caddyfile; then
  echo "Caddy configuration validation failed." >&2
  exit 1
fi
if ! compose build --pull backend frontend; then
  echo "Image build failed; the running production release was not changed." >&2
  exit 1
fi
# Cache pruning affects every project on this shared VM, so it is opt-in and
# should be used only during an explicit disk-recovery operation.
if [ "${SUBFRAME_PRUNE_BUILD_CACHE:-0}" = 1 ]; then
  docker builder prune -af >/dev/null
fi
if ! assert_no_open_stripe_purchases_without_consumer_contract; then
  echo "Open Stripe purchase preflight failed before database migration." >&2
  exit 1
fi
trap on_signal INT TERM HUP
if ! compose up -d db backend frontend; then
  rollback
  exit 1
fi
# Bind-mounted Caddyfile content is not part of Docker Compose's service hash,
# so recreate the edge only after its new configuration validates.
if ! compose up -d --force-recreate edge; then
  rollback
  exit 1
fi

attempt=0
healthy=0
while [ "$attempt" -lt 60 ]; do
  backend_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-backend-1 2>/dev/null || true)
  frontend_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-frontend-1 2>/dev/null || true)
  edge_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-edge-1 2>/dev/null || true)
  if [ "$backend_health" = healthy ] && [ "$frontend_health" = healthy ] && [ "$edge_health" = healthy ]; then
    healthy=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done

if [ "$healthy" -ne 1 ]; then
  compose ps >&2
  compose logs --tail=120 backend frontend edge >&2
  rollback
  exit 1
fi

if ! "$ROOT_DIR/deploy/hetzner/verify-production.sh" --candidate; then
  echo "Candidate production verification failed; the previous successful-release state was preserved." >&2
  compose ps >&2
  compose logs --tail=120 backend frontend edge >&2
  rollback
  exit 1
fi

install -d -m 700 "$STATE_DIR"
state_temp=$(mktemp "$STATE_DIR/.last-successful-release.XXXXXX")
printf '%s\n' "$release_sha" > "$state_temp"
chmod 600 "$state_temp"
mv -f -- "$state_temp" "$STATE_FILE"
state_temp=""
trap - INT TERM HUP
compose ps
exit 0
