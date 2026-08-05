#!/bin/sh
set -eu
umask 077

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"
STATE_DIR="$ROOT_DIR/.runtime"
STATE_FILE="$STATE_DIR/last-successful-release"
ERASURE_RECEIPT_FILE="$STATE_DIR/last-erasure-reconciliation"
CONTINUITY_STATE_FILE="$STATE_DIR/privacy-continuity-id"
ERASURE_ANCHOR_DIR="$STATE_DIR/privacy-erasure-anchor"
export SUBFRAME_ERASURE_ANCHOR_DIR="$ERASURE_ANCHOR_DIR"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing production env: $ENV_FILE" >&2
  exit 1
fi
if grep -Eq \
  '^[[:space:]]*(export[[:space:]]+)?(GSP_GCS_[A-Z0-9_]*|GOOGLE_APPLICATION_CREDENTIALS)[[:space:]]*=' \
  "$ENV_FILE"; then
  echo "Remove retired GCS settings from the production env before deploying." >&2
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

privacy_continuity_bootstrap=0
privacy_continuity_id=""
if [ -e "$CONTINUITY_STATE_FILE" ] || [ -L "$CONTINUITY_STATE_FILE" ]; then
  if [ ! -f "$CONTINUITY_STATE_FILE" ] || [ -L "$CONTINUITY_STATE_FILE" ]; then
    echo "Privacy continuity state must be a regular file: $CONTINUITY_STATE_FILE" >&2
    exit 1
  fi
  privacy_continuity_id=$(cat "$CONTINUITY_STATE_FILE")
  if ! printf '%s\n' "$privacy_continuity_id" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "Privacy continuity state is malformed." >&2
    exit 1
  fi
else
  # Only the one-time transition from a release that predates the continuity
  # gate may initialize a journal beside existing data. Any later missing
  # state is treated as whole-host/journal loss and must remain offline.
  if [ -n "$previous_sha" ]; then
    if ! git -C "$ROOT_DIR" cat-file -e "$previous_sha^{commit}" 2>/dev/null; then
      echo "Cannot prove the release that predates the missing privacy continuity state." >&2
      exit 1
    fi
    if ! previous_compose=$(git -C "$ROOT_DIR" show \
      "$previous_sha:deploy/hetzner/docker-compose.production.yml" 2>/dev/null); then
      echo "Cannot inspect the previous release privacy contract." >&2
      exit 1
    fi
    if printf '%s\n' "$previous_compose" | grep -q \
      'GSP_ERASURE_JOURNAL_CONTINUITY_ID'; then
      echo "Privacy continuity state is missing for a continuity-aware release." >&2
      echo "Do not restore or publish user data without the current live erasure journal." >&2
      exit 1
    fi
  fi
  privacy_continuity_id=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  if ! printf '%s\n' "$privacy_continuity_id" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "Could not generate privacy continuity state." >&2
    exit 1
  fi
  privacy_continuity_bootstrap=1
fi
export SUBFRAME_PRIVACY_CONTINUITY_ID="$privacy_continuity_id"

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

database_scalar() {
  sql=$1
  compose exec -T db sh -eu -c \
    'exec psql -X --no-password --tuples-only --no-align --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --command "$1"' \
    sh "$sql" | tr -d '[:space:]'
}

assert_no_legacy_gcs_references() {
  legacy_table_exists=$(database_scalar \
    "SELECT to_regclass('public.gcs_uploads') IS NOT NULL;")
  case "$legacy_table_exists" in
    f) legacy_upload_rows=0 ;;
    t)
      legacy_upload_rows=$(database_scalar "SELECT count(*) FROM gcs_uploads;")
      ;;
    *)
      echo "Could not determine whether the retired GCS table exists." >&2
      return 1
      ;;
  esac
  legacy_job_references=$(database_scalar \
    "SELECT count(*) FROM jobs WHERE result_data ? 'source_gcs_object';")
  for legacy_count in "$legacy_upload_rows" "$legacy_job_references"
  do
    case "$legacy_count" in
      ''|*[!0-9]*)
        echo "Could not validate retired GCS object-reference counts." >&2
        return 1
        ;;
    esac
  done
  if [ "$legacy_upload_rows" -ne 0 ] || [ "$legacy_job_references" -ne 0 ]; then
    echo "Retired GCS object references remain; preserve them and complete provider deletion first." >&2
    return 1
  fi
}

portable_mode() {
  stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"
}

portable_owner() {
  owner_uid=$(stat -c %u "$1" 2>/dev/null || stat -f %u "$1")
  owner_gid=$(stat -c %g "$1" 2>/dev/null || stat -f %g "$1")
  printf '%s:%s\n' "$owner_uid" "$owner_gid"
}

prepare_erasure_anchor_directory() {
  if [ "$privacy_continuity_bootstrap" -eq 1 ]; then
    if [ -e "$ERASURE_ANCHOR_DIR" ] || [ -L "$ERASURE_ANCHOR_DIR" ]; then
      if [ ! -d "$ERASURE_ANCHOR_DIR" ] || [ -L "$ERASURE_ANCHOR_DIR" ]; then
        echo "Erasure-journal anchor path must be a real directory." >&2
        return 1
      fi
      if find "$ERASURE_ANCHOR_DIR" -mindepth 1 -print -quit | grep -q .; then
        echo "Refusing to initialize a non-empty erasure-journal anchor directory." >&2
        return 1
      fi
    fi
    if ! install -d -m 700 -o 10001 -g 10001 "$ERASURE_ANCHOR_DIR"; then
      echo "Could not create the private erasure-journal anchor directory." >&2
      return 1
    fi
  fi

  if [ ! -d "$ERASURE_ANCHOR_DIR" ] || [ -L "$ERASURE_ANCHOR_DIR" ]; then
    echo "Live erasure-journal anchor directory is missing or invalid." >&2
    return 1
  fi
  anchor_parent=$(CDPATH= cd -- "$ERASURE_ANCHOR_DIR/.." && pwd -P) || return 1
  if [ "$anchor_parent/$(basename -- "$ERASURE_ANCHOR_DIR")" != "$ERASURE_ANCHOR_DIR" ]; then
    echo "Erasure-journal anchor directory must not traverse a symlink." >&2
    return 1
  fi
  if [ "$(portable_mode "$ERASURE_ANCHOR_DIR")" != 700 ]; then
    echo "Erasure-journal anchor directory permissions are unsafe." >&2
    return 1
  fi
  if [ "$(portable_owner "$ERASURE_ANCHOR_DIR")" != 10001:10001 ]; then
    echo "Erasure-journal anchor directory ownership is unsafe." >&2
    return 1
  fi
}

initialize_or_verify_privacy_continuity() {
  allow_existing_data=0
  if [ "$privacy_continuity_bootstrap" -eq 1 ] && [ -n "$previous_sha" ]; then
    # One-time in-place upgrade from the legacy release. The edge is already
    # stopped and the old backend is stopped below before this runs.
    allow_existing_data=1
  fi

  if [ "$privacy_continuity_bootstrap" -eq 1 ] && [ "$allow_existing_data" -ne 1 ]; then
    for privacy_table in users jobs
    do
      table_exists=$(database_scalar "SELECT to_regclass('public.$privacy_table') IS NOT NULL;")
      case "$table_exists" in
        f) ;;
        t)
          row_count=$(database_scalar "SELECT count(*) FROM $privacy_table;")
          case "$row_count" in
            ''|*[!0-9]*)
              echo "Could not validate empty privacy table: $privacy_table" >&2
              return 1
              ;;
          esac
          if [ "$row_count" -ne 0 ]; then
            echo "Refusing to initialize a new erasure journal beside restored user data." >&2
            return 1
          fi
          ;;
        *)
          echo "Could not validate privacy table state: $privacy_table" >&2
          return 1
          ;;
      esac
    done
  fi

  if ! prepare_erasure_anchor_directory; then
    return 1
  fi

  if ! compose run --rm --no-deps --user 0:0 --entrypoint sh \
    -e EXPECTED_CONTINUITY_ID="$privacy_continuity_id" \
    -e INITIALIZE_CONTINUITY="$privacy_continuity_bootstrap" \
    -e ALLOW_EXISTING_DATA="$allow_existing_data" \
    backend -eu -c '
      root=/privacy-erasure-journal
      marker=$root/.continuity-id
      if [ "$INITIALIZE_CONTINUITY" = 1 ]; then
        if [ -e "$marker" ] || [ -L "$marker" ]; then
          echo "Erasure journal marker already exists while host continuity state is missing." >&2
          exit 1
        fi
        if [ "$ALLOW_EXISTING_DATA" != 1 ] &&
          find /data -mindepth 1 \( -type f -o -type l \) -print -quit | grep -q .; then
          echo "Refusing to initialize a new erasure journal beside restored media." >&2
          exit 1
        fi
        if find "$root" -mindepth 1 -print -quit | grep -q .; then
          echo "Refusing to initialize a non-empty erasure journal volume." >&2
          exit 1
        fi
        chown 10001:10001 "$root"
        chmod 700 "$root"
        temporary=$root/.continuity-id.tmp.$$
        printf "%s\n" "$EXPECTED_CONTINUITY_ID" > "$temporary"
        chown 10001:10001 "$temporary"
        chmod 600 "$temporary"
        mv "$temporary" "$marker"
        sync "$marker" "$root"
      else
        [ -f "$marker" ] && [ ! -L "$marker" ] || {
          echo "Live erasure journal continuity marker is missing." >&2
          exit 1
        }
        [ "$(cat "$marker")" = "$EXPECTED_CONTINUITY_ID" ] || {
          echo "Live erasure journal continuity marker does not match this host." >&2
          exit 1
        }
        [ "$(stat -c %a "$root")" = 700 ] || {
          echo "Erasure journal directory permissions are unsafe." >&2
          exit 1
        }
        [ "$(stat -c %u:%g "$root")" = 10001:10001 ] || {
          echo "Erasure journal directory ownership is unsafe." >&2
          exit 1
        }
      fi
    '; then
    return 1
  fi

  if [ "$privacy_continuity_bootstrap" -eq 1 ]; then
    if ! compose run --rm --no-deps --entrypoint python backend -c \
      'from backend.app.core.erasure_journal import configured_erasure_journal; configured_erasure_journal().initialize()'; then
      echo "Could not initialize the erasure-journal integrity anchors." >&2
      return 1
    fi
  fi
  if ! compose run --rm --no-deps --entrypoint python backend -c \
    'from backend.app.core.erasure_journal import configured_erasure_journal; configured_erasure_journal().read_all()'; then
    echo "Erasure-journal integrity validation failed before application startup." >&2
    return 1
  fi

  if [ "$privacy_continuity_bootstrap" -eq 1 ]; then
    continuity_state_temp=$(mktemp "$STATE_DIR/.privacy-continuity-id.XXXXXX")
    printf '%s\n' "$privacy_continuity_id" > "$continuity_state_temp"
    chmod 600 "$continuity_state_temp"
    mv -f -- "$continuity_state_temp" "$CONTINUITY_STATE_FILE"
    continuity_state_temp=""
    privacy_continuity_bootstrap=0
  fi
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
  # A failed candidate may already have restored files or migrated the DB.
  # Never let a rollback reopen public traffic without a fresh privacy gate.
  if ! compose stop edge >/dev/null 2>&1; then
    docker stop subframe-edge-1 >/dev/null 2>&1 || true
  fi
  compose stop privacy-relay >/dev/null 2>&1 || true
  rm -f -- "$ERASURE_RECEIPT_FILE"
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

  echo "Explicit schema-compatible rollback requested; restoring core services for $previous_sha." >&2
  if ! SUBFRAME_RELEASE_SHA="$previous_sha" compose up -d --no-build db backend frontend; then
    echo "Schema-compatible rollback failed; manual recovery is required." >&2
    return 0
  fi
  echo "Rollback core services are restored, but the public edge remains stopped." >&2
  echo "Complete retention and erasure reconciliation, then deploy a verified roll-forward release." >&2
  return 0
}

state_temp=""
erasure_receipt_temp=""
continuity_state_temp=""

cleanup_state_temp() {
  if [ -n "$state_temp" ]; then
    rm -f -- "$state_temp"
    state_temp=""
  fi
  if [ -n "$erasure_receipt_temp" ]; then
    rm -f -- "$erasure_receipt_temp"
    erasure_receipt_temp=""
  fi
  if [ -n "$continuity_state_temp" ]; then
    rm -f -- "$continuity_state_temp"
    continuity_state_temp=""
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
if ! compose run --rm --no-deps --entrypoint caddy privacy-relay validate \
  --config /etc/caddy/Caddyfile --adapter caddyfile; then
  echo "Private erasure-relay configuration validation failed." >&2
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
if ! assert_no_legacy_gcs_references; then
  echo "Legacy GCS retirement preflight failed before database migration." >&2
  exit 1
fi
if ! "$ROOT_DIR/deploy/hetzner/verify-gcs-retirement.sh"; then
  echo "Legacy GCS retirement evidence is required before database migration." >&2
  exit 1
fi
trap on_signal INT TERM HUP
install -d -m 700 "$STATE_DIR"
rm -f -- "$ERASURE_RECEIPT_FILE"
if ! compose stop edge; then
  echo "Could not close the public edge before erasure reconciliation." >&2
  rollback
  exit 1
fi
if ! compose stop backend frontend; then
  echo "Could not stop the old application before privacy continuity validation." >&2
  rollback
  exit 1
fi
if ! compose up -d db; then
  rollback
  exit 1
fi

attempt=0
db_healthy=0
while [ "$attempt" -lt 60 ]; do
  db_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-db-1 2>/dev/null || true)
  if [ "$db_health" = healthy ]; then
    db_healthy=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if [ "$db_healthy" -ne 1 ] || ! initialize_or_verify_privacy_continuity; then
  echo "Privacy continuity validation failed; the public edge remains stopped." >&2
  rollback
  exit 1
fi
if ! compose up -d backend frontend; then
  rollback
  exit 1
fi

attempt=0
healthy=0
while [ "$attempt" -lt 60 ]; do
  backend_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-backend-1 2>/dev/null || true)
  frontend_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-frontend-1 2>/dev/null || true)
  if [ "$backend_health" = healthy ] && [ "$frontend_health" = healthy ]; then
    healthy=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done

if [ "$healthy" -ne 1 ]; then
  compose ps >&2
  compose logs --tail=120 backend frontend >&2
  rollback
  exit 1
fi

if ! compose up -d privacy-relay; then
  echo "Private erasure relay failed to start; the public edge remains stopped." >&2
  rollback
  exit 1
fi
privacy_relay_id=$(compose ps -q privacy-relay)
privacy_relay_healthy=0
attempt=0
while [ "$attempt" -lt 20 ]; do
  privacy_relay_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$privacy_relay_id" 2>/dev/null || true)
  if [ "$privacy_relay_health" = healthy ]; then
    privacy_relay_healthy=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if [ "$privacy_relay_healthy" -ne 1 ]; then
  echo "Private erasure relay is unhealthy; the public edge remains stopped." >&2
  rollback
  exit 1
fi
if ! compose exec -T \
  -e GSP_ELEVENLABS_API_BASE=http://privacy-relay:8082/elevenlabs \
  backend python -m backend.cli run-retention; then
  echo "Local retention reconciliation failed; the public edge remains stopped." >&2
  rollback
  exit 1
fi
if ! compose exec -T \
  -e GSP_ELEVENLABS_API_BASE=http://privacy-relay:8082/elevenlabs \
  backend python -m backend.cli reconcile-erasures; then
  echo "Erasure reconciliation failed; the public edge remains stopped." >&2
  rollback
  exit 1
fi
if ! compose stop privacy-relay; then
  echo "Could not stop the temporary erasure relay; the public edge remains stopped." >&2
  rollback
  exit 1
fi
erasure_receipt_temp=$(mktemp "$STATE_DIR/.last-erasure-reconciliation.XXXXXX")
printf '%s\n' \
  "reconciled=true" \
  "release_sha=$release_sha" \
  "journal_path=/privacy-erasure-journal" \
  "completed_at_utc=$(date -u +%Y%m%dT%H%M%SZ)" > "$erasure_receipt_temp"
chmod 600 "$erasure_receipt_temp"
mv -f -- "$erasure_receipt_temp" "$ERASURE_RECEIPT_FILE"
erasure_receipt_temp=""

# Bind-mounted Caddyfile content is not part of Docker Compose's service hash,
# so recreate the edge only after its new configuration validates and every
# durable erasure tombstone has been replayed against the restored local state.
if ! compose up -d --force-recreate edge; then
  rollback
  exit 1
fi

attempt=0
edge_healthy=0
while [ "$attempt" -lt 60 ]; do
  edge_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' subframe-edge-1 2>/dev/null || true)
  if [ "$edge_health" = healthy ]; then
    edge_healthy=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 2
done
if [ "$edge_healthy" -ne 1 ]; then
  compose ps >&2
  compose logs --tail=120 edge >&2
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

state_temp=$(mktemp "$STATE_DIR/.last-successful-release.XXXXXX")
printf '%s\n' "$release_sha" > "$state_temp"
chmod 600 "$state_temp"
mv -f -- "$state_temp" "$STATE_FILE"
state_temp=""
trap - INT TERM HUP
compose ps
exit 0
