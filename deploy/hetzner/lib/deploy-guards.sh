# shellcheck shell=sh
# shellcheck disable=SC2034,SC2154
# Deployment verification and cutover helpers. This file is sourced by deploy-production.sh.

receipt_value() {
  sed -n "s/^$1=//p" "$restore_drill_receipt" | tail -n 1
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
    # Some install implementations resolve -o/-g through the host account
    # database. The container UID/GID intentionally need not exist there, so
    # create the private directory first and apply numeric ownership with
    # chown.
    if ! install -d -m 700 "$ERASURE_ANCHOR_DIR" ||
      ! chown 10001:10001 "$ERASURE_ANCHOR_DIR"; then
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
  compose stop app-edge >/dev/null 2>&1 || true
  docker stop subframe-app-edge-1 >/dev/null 2>&1 || true
  if [ "$legacy_privacy_transition" -eq 1 ]; then
    compose stop edge >/dev/null 2>&1 || true
    docker stop subframe-edge-1 >/dev/null 2>&1 || true
  fi
  compose stop privacy-relay >/dev/null 2>&1 || true
  compose stop feedback-worker >/dev/null 2>&1 || true
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
  echo "Rollback core services are restored, but the public application remains behind maintenance mode." >&2
  echo "Complete retention and erasure reconciliation, then deploy a verified roll-forward release." >&2
  return 0
}

wait_for_service_health() {
  service_name=$1
  max_attempts=$2
  delay_seconds=$3
  attempt=0
  while [ "$attempt" -lt "$max_attempts" ]; do
    service_id=$(compose ps -q "$service_name" 2>/dev/null || true)
    service_health=""
    if [ -n "$service_id" ]; then
      service_health=$(docker inspect --format \
        '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
        "$service_id" 2>/dev/null || true)
    fi
    if [ "$service_health" = healthy ]; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep "$delay_seconds"
  done
  return 1
}

public_gateway_is_reviewed_maintenance() {
  # A failed candidate deliberately leaves the data-blind gateway serving its
  # reviewed maintenance page while app-edge remains closed. Permit the next
  # roll-forward to recognize that state only from local runtime evidence; a
  # generic public 503 must never become an accepted deployment preflight.
  maintenance_edge_id=$(compose ps -q edge 2>/dev/null || true)
  maintenance_app_edge_id=$(compose ps -a -q app-edge 2>/dev/null || true)
  if [ -z "$maintenance_edge_id" ] || [ -z "$maintenance_app_edge_id" ]; then
    return 1
  fi
  maintenance_app_edge_running=$(docker inspect --format '{{.State.Running}}' \
    "$maintenance_app_edge_id" 2>/dev/null || true)
  if [ "$maintenance_app_edge_running" != false ]; then
    return 1
  fi
  maintenance_edge_health=$(docker inspect --format \
    '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' \
    "$maintenance_edge_id" 2>/dev/null || true)
  if [ "$maintenance_edge_health" != healthy ]; then
    return 1
  fi
  expected_gateway_caddyfile_sha=$(sha256sum \
    "$ROOT_DIR/deploy/hetzner/gateway/Caddyfile" | awk 'NR == 1 { print $1 }') || \
    return 1
  runtime_gateway_caddyfile_sha=$(docker exec "$maintenance_edge_id" \
    sha256sum /etc/caddy/Caddyfile 2>/dev/null | awk 'NR == 1 { print $1 }') || \
    return 1
  [ -n "$expected_gateway_caddyfile_sha" ] && \
    [ "$runtime_gateway_caddyfile_sha" = "$expected_gateway_caddyfile_sha" ]
}

reload_public_gateway() {
  edge_id=$(compose ps -q edge 2>/dev/null || true)
  if [ -z "$edge_id" ] ||
    ! docker exec "$edge_id" caddy validate \
      --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null ||
    ! docker exec "$edge_id" caddy reload \
      --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null ||
    ! docker exec "$edge_id" wget -q -O /dev/null \
      http://localhost:8080/.well-known/gsubs-edge-health; then
    echo "The stable public gateway could not load its reviewed configuration." >&2
    return 1
  fi
}

prepare_public_gateway() {
  if [ "${verified_maintenance_roll_forward:-0}" = 1 ]; then
    # Do not republish the failed candidate merely to prepare a gateway that is
    # already healthy and reviewed. Revalidate the local fail-closed state
    # immediately before cutover and keep app-edge stopped until the corrected
    # candidate is activated after retention and erasure replay.
    if ! public_gateway_is_reviewed_maintenance; then
      echo "The verified maintenance gateway changed before roll-forward cutover." >&2
      return 1
    fi
    echo "Keeping the previous failed candidate closed during roll-forward preparation." >&2
    return 0
  fi
  # Existing releases used the application proxy itself as the public tunnel
  # target, so every privacy cutover surfaced a raw 502. Place a stable,
  # data-blind gateway in front while the old app is still healthy. All later
  # deploys retain this container and expose only its maintenance response
  # while app-edge is quiesced.
  if [ -z "$previous_sha" ] || [ "$legacy_privacy_transition" -eq 1 ]; then
    return 0
  fi
  if ! compose up -d --no-deps --force-recreate app-edge ||
    ! wait_for_service_health app-edge 60 1; then
    echo "Application edge preparation failed before cutover; production was not quiesced." >&2
    compose logs --tail=120 app-edge >&2 || true
    return 1
  fi
  if ! compose up -d --no-deps edge ||
    ! wait_for_service_health edge 60 1 ||
    ! reload_public_gateway ||
    ! docker exec "$(compose ps -q edge)" wget -q -O /dev/null http://localhost:8080; then
    echo "Stable public gateway preparation failed before privacy cutover." >&2
    compose logs --tail=120 edge app-edge >&2 || true
    return 1
  fi
}

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

on_signal() {
  trap - INT TERM HUP
  cleanup_state_temp
  rollback
  exit 1
}
