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
TRANSITION_STATE_FILE="$STATE_DIR/legacy-journal-bootstrap-transition"
export SUBFRAME_ERASURE_ANCHOR_DIR="$ERASURE_ANCHOR_DIR"

. "$ROOT_DIR/deploy/hetzner/lib/deploy-transition.sh"
. "$ROOT_DIR/deploy/hetzner/lib/deploy-guards.sh"


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
feedback_api_env_file=""
feedback_worker_env_file=""
if grep -Eq '^  feedback-worker:' "$COMPOSE_FILE"; then
  feedback_api_env_file="${SUBFRAME_FEEDBACK_API_ENV_FILE:-$(sed -n 's/^SUBFRAME_FEEDBACK_API_ENV_FILE=//p' "$ENV_FILE" | tail -n 1)}"
  feedback_worker_env_file="${SUBFRAME_FEEDBACK_WORKER_ENV_FILE:-$(sed -n 's/^SUBFRAME_FEEDBACK_WORKER_ENV_FILE=//p' "$ENV_FILE" | tail -n 1)}"
  for private_feedback_env in \
    "api:$feedback_api_env_file" \
    "worker:$feedback_worker_env_file"
  do
    feedback_env_label=${private_feedback_env%%:*}
    feedback_env_path=${private_feedback_env#*:}
    case "$feedback_env_path" in
      /*) ;;
      *)
        echo "Feedback $feedback_env_label env path must be absolute." >&2
        exit 1
        ;;
    esac
    if [ ! -f "$feedback_env_path" ] || [ -L "$feedback_env_path" ]; then
      echo "Feedback $feedback_env_label env must be a regular non-symlink file: $feedback_env_path" >&2
      exit 1
    fi
    feedback_env_parent=$(CDPATH= cd -- "$(dirname -- "$feedback_env_path")" && pwd -P)
    if [ "$feedback_env_parent/$(basename -- "$feedback_env_path")" != "$feedback_env_path" ]; then
      echo "Feedback $feedback_env_label env path must be canonical and must not traverse a symlink." >&2
      exit 1
    fi
    if [ "$(portable_mode "$feedback_env_path")" != 600 ]; then
      echo "Feedback $feedback_env_label env permissions must be 0600." >&2
      exit 1
    fi
  done
  export SUBFRAME_FEEDBACK_API_ENV_FILE="$feedback_api_env_file"
  export SUBFRAME_FEEDBACK_WORKER_ENV_FILE="$feedback_worker_env_file"
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

# REGRESSION: the shared public Caddy edge once advertised HTTP/3 even though
# its QUIC path delivered private media about 25x slower than HTTP/2. Verify
# the external transport contract before stopping or replacing any service. A
# prior failed candidate may already have closed app-edge; recognize only the
# exact reviewed fail-closed maintenance state so a corrected release can roll
# forward without an unsafe manual edge restart.
verified_maintenance_roll_forward=0
if [ -n "$previous_sha" ]; then
  if public_gateway_is_reviewed_maintenance; then
    if ! "$ROOT_DIR/deploy/hetzner/verify-public-edge.sh" --maintenance; then
      echo "Public maintenance transport preflight failed; production was not changed." >&2
      exit 1
    fi
    verified_maintenance_roll_forward=1
    echo "Verified the fail-closed maintenance gateway for this roll-forward release." >&2
  elif ! "$ROOT_DIR/deploy/hetzner/verify-public-edge.sh"; then
    echo "Public download transport preflight failed; production was not changed." >&2
    exit 1
  fi
fi

privacy_continuity_bootstrap=0
legacy_privacy_transition=0
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
    legacy_privacy_transition=1
  fi
  privacy_continuity_id=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
  if ! printf '%s\n' "$privacy_continuity_id" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "Could not generate privacy continuity state." >&2
    exit 1
  fi
  privacy_continuity_bootstrap=1
fi
export SUBFRAME_PRIVACY_CONTINUITY_ID="$privacy_continuity_id"

if [ "$legacy_privacy_transition" -eq 1 ]; then
  transition_status=0
  stage_or_validate_legacy_transition || transition_status=$?
  case "$transition_status" in
    0) ;;
    10) exit 1 ;;
    *)
      if ! stop_legacy_services_fail_closed; then
        echo "Legacy journal transition validation failed; closure could not be verified." >&2
        echo "Manual intervention is required to close the legacy writers." >&2
      else
        echo "Legacy journal transition validation failed; edge and backend remain closed." >&2
      fi
      exit 1
      ;;
  esac
fi

restore_drill_receipt="$STATE_DIR/last-backup-restore-drill"
schema_change=1
if [ -n "$previous_sha" ] && \
  git -C "$ROOT_DIR" cat-file -e "$previous_sha^{commit}" 2>/dev/null &&
  git -C "$ROOT_DIR" diff --quiet "$previous_sha" "$release_sha" -- \
    backend/alembic/versions; then
  schema_change=0
fi


restore_drill_required=$schema_change
if [ "$legacy_privacy_transition" -eq 1 ]; then
  restore_drill_required=1
fi
if [ "$restore_drill_required" -eq 1 ]; then
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
  if [ "$legacy_privacy_transition" -eq 1 ] &&
    [ "$backup_created_epoch" -le "$transition_stopped_epoch" ]; then
    echo "The backup must be created after the legacy edge is quiesced." >&2
    echo "Create and verify a fresh post-marker backup before continuing." >&2
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

state_temp=""
erasure_receipt_temp=""
continuity_state_temp=""
trap cleanup_state_temp EXIT

if [ "$legacy_privacy_transition" -eq 1 ] &&
  ! assert_legacy_transition_services_quiesced; then
  exit 1
fi
compose config --quiet
if ! compose run --rm --no-deps --entrypoint caddy edge validate \
  --config /etc/caddy/Caddyfile --adapter caddyfile; then
  echo "Public gateway configuration validation failed." >&2
  exit 1
fi
if ! compose run --rm --no-deps --entrypoint caddy app-edge validate \
  --config /etc/caddy/Caddyfile --adapter caddyfile; then
  echo "Application edge configuration validation failed." >&2
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
if ! compose run --rm --no-deps --entrypoint python backend -c \
  'from pathlib import Path; import os; root = Path("/app"); assert all(os.access(path, os.R_OK | (os.X_OK if path.is_dir() else 0)) for path in (root, *root.rglob("*"))); import main'; then
  echo "Backend source readability/import preflight failed; the running production release was not changed." >&2
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
if ! prepare_public_gateway; then
  exit 1
fi
trap on_signal INT TERM HUP
install -d -m 700 "$STATE_DIR"
rm -f -- "$ERASURE_RECEIPT_FILE"
if [ "$legacy_privacy_transition" -eq 1 ]; then
  if ! assert_legacy_transition_services_quiesced; then
    rollback
    exit 1
  fi
else
  if ! compose stop app-edge; then
    echo "Could not put the public application behind maintenance mode before erasure reconciliation." >&2
    rollback
    exit 1
  fi
  if ! docker exec "$(compose ps -q edge)" wget -q -O /dev/null \
    http://localhost:8080/.well-known/gsubs-edge-health; then
    echo "Stable maintenance gateway became unavailable during cutover." >&2
    rollback
    exit 1
  fi
fi
if ! compose stop backend frontend feedback-worker; then
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
  echo "Privacy continuity validation failed; the public application remains safely in maintenance mode." >&2
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

if ! compose up -d feedback-worker; then
  echo "Feedback notification worker failed to start; the public application remains safely in maintenance mode." >&2
  rollback
  exit 1
fi
feedback_worker_id=$(compose ps -q feedback-worker)
feedback_worker_healthy=0
attempt=0
while [ "$attempt" -lt 40 ]; do
  feedback_worker_health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$feedback_worker_id" 2>/dev/null || true)
  if [ "$feedback_worker_health" = healthy ]; then
    feedback_worker_healthy=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if [ "$feedback_worker_healthy" -ne 1 ]; then
  echo "Feedback notification worker is unhealthy; the public application remains safely in maintenance mode." >&2
  compose logs --tail=120 feedback-worker >&2
  rollback
  exit 1
fi

if ! compose up -d privacy-relay; then
  echo "Private erasure relay failed to start; the public application remains safely in maintenance mode." >&2
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
  echo "Private erasure relay is unhealthy; the public application remains safely in maintenance mode." >&2
  rollback
  exit 1
fi
if ! compose exec -T \
  -e GSP_ELEVENLABS_API_BASE=http://privacy-relay:8082/elevenlabs \
  backend python -m backend.cli run-retention; then
  echo "Local retention reconciliation failed; the public application remains safely in maintenance mode." >&2
  rollback
  exit 1
fi
if ! compose exec -T \
  -e GSP_ELEVENLABS_API_BASE=http://privacy-relay:8082/elevenlabs \
  backend python -m backend.cli reconcile-erasures; then
  echo "Erasure reconciliation failed; the public application remains safely in maintenance mode." >&2
  rollback
  exit 1
fi
if ! compose stop privacy-relay; then
  echo "Could not stop the temporary erasure relay; the public application remains safely in maintenance mode." >&2
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

# Recreate only the private application edge after every durable erasure
# tombstone has been replayed. The stable public gateway remains online and
# dynamically discovers the restored app-edge without exposing the app early.
if ! compose up -d --no-deps --force-recreate app-edge; then
  rollback
  exit 1
fi
if ! wait_for_service_health app-edge 60 2; then
  compose ps >&2
  compose logs --tail=120 app-edge >&2
  rollback
  exit 1
fi
if ! compose up -d --no-deps edge ||
  ! wait_for_service_health edge 60 1 ||
  ! reload_public_gateway; then
  compose ps >&2
  compose logs --tail=120 edge app-edge >&2
  rollback
  exit 1
fi

if ! "$ROOT_DIR/deploy/hetzner/verify-production.sh" --candidate; then
  echo "Candidate production verification failed; the previous successful-release state was preserved." >&2
  compose ps >&2
  compose logs --tail=120 backend frontend feedback-worker app-edge edge >&2
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
