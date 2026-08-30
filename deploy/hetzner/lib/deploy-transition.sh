# shellcheck shell=sh
# shellcheck disable=SC2034,SC2154
# Deployment transition helpers. This file is sourced by deploy-production.sh.

compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

portable_mode() {
  stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"
}

portable_owner() {
  owner_uid=$(stat -c %u "$1" 2>/dev/null || stat -f %u "$1") || return 1
  owner_gid=$(stat -c %g "$1" 2>/dev/null || stat -f %g "$1") || return 1
  printf '%s:%s\n' "$owner_uid" "$owner_gid"
}

portable_device() {
  stat -c %d "$1" 2>/dev/null || stat -f %d "$1"
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

prepare_private_state_directory() {
  if [ -e "$STATE_DIR" ] || [ -L "$STATE_DIR" ]; then
    if [ ! -d "$STATE_DIR" ] || [ -L "$STATE_DIR" ]; then
      echo "Runtime state path must be a real directory: $STATE_DIR" >&2
      return 1
    fi
  elif ! mkdir "$STATE_DIR"; then
    echo "Could not create the private runtime state directory." >&2
    return 1
  fi
  chmod 700 "$STATE_DIR"
  state_parent=$(CDPATH= cd -- "$STATE_DIR/.." && pwd -P) || return 1
  if [ "$state_parent/$(basename -- "$STATE_DIR")" != "$STATE_DIR" ]; then
    echo "Runtime state directory must not traverse a symlink." >&2
    return 1
  fi
  if [ "$(portable_mode "$STATE_DIR")" != 700 ]; then
    echo "Runtime state directory permissions are unsafe." >&2
    return 1
  fi
  state_device=$(portable_device "$STATE_DIR") || {
    echo "Could not identify the runtime-state filesystem." >&2
    return 1
  }
  root_device=$(portable_device /) || {
    echo "Could not identify the existing host root filesystem." >&2
    return 1
  }
  if [ "$state_device" != "$root_device" ]; then
    echo "Runtime transition evidence must stay on the existing host root disk." >&2
    return 1
  fi
}

transition_value() {
  sed -n "s/^$1=//p" "$TRANSITION_STATE_FILE" | tail -n 1
}

container_runtime_fingerprint() {
  inspected_state=$(docker inspect --format \
    '{{.Id}}|{{.State.Running}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|{{.RestartCount}}' \
    "$1") || return 1
  printf '%s\n' "$inspected_state" | sha256sum | awk 'NR == 1 { print $1 }'
}

stop_legacy_services_fail_closed() {
  compose stop edge app-edge backend feedback-worker >/dev/null 2>&1 || true
  docker stop subframe-edge-1 subframe-app-edge-1 subframe-backend-1 subframe-feedback-worker-1 >/dev/null 2>&1 || true
  running_legacy_services=$(compose ps --status running -q edge app-edge backend feedback-worker 2>/dev/null) || {
    echo "Could not verify that the legacy edge and backend are closed." >&2
    return 1
  }
  if [ -n "$running_legacy_services" ]; then
    echo "Legacy edge or backend is still running after the fail-closed stop." >&2
    return 1
  fi
}

assert_legacy_transition_services_quiesced() {
  current_edge_id=$(docker inspect --format '{{.Id}}' subframe-edge-1 2>/dev/null || true)
  current_backend_id=$(docker inspect --format '{{.Id}}' subframe-backend-1 2>/dev/null || true)
  current_edge_running=""
  current_backend_running=""
  if [ -n "$current_edge_id" ]; then
    current_edge_running=$(docker inspect --format '{{.State.Running}}' \
      "$current_edge_id" 2>/dev/null || true)
  fi
  if [ -n "$current_backend_id" ]; then
    current_backend_running=$(docker inspect --format '{{.State.Running}}' \
      "$current_backend_id" 2>/dev/null || true)
  fi
  current_edge_fingerprint=""
  current_backend_fingerprint=""
  if [ -n "$current_edge_id" ]; then
    current_edge_fingerprint=$(container_runtime_fingerprint "$current_edge_id" 2>/dev/null || true)
  fi
  if [ -n "$current_backend_id" ]; then
    current_backend_fingerprint=$(container_runtime_fingerprint "$current_backend_id" 2>/dev/null || true)
  fi
  if [ "$current_edge_id" != "$transition_edge_id" ] ||
    [ "$current_edge_running" != false ] ||
    [ "$current_edge_fingerprint" != "$transition_edge_fingerprint" ] ||
    [ "$current_backend_id" != "$transition_backend_id" ] ||
    [ "$current_backend_running" != false ] ||
    [ "$current_backend_fingerprint" != "$transition_backend_fingerprint" ]; then
    if ! stop_legacy_services_fail_closed; then
      echo "Manual intervention is required to close the legacy writers." >&2
    fi
    echo "Legacy edge or backend restarted after the transition marker; deployment remains closed." >&2
    echo "Investigate, restage the transition, and create a fresh backup and restore drill." >&2
    return 1
  fi
}

validate_legacy_transition_marker() {
  if [ ! -f "$TRANSITION_STATE_FILE" ] || [ -L "$TRANSITION_STATE_FILE" ]; then
    echo "Legacy journal transition marker must be a regular file." >&2
    return 1
  fi
  transition_mode=$(portable_mode "$TRANSITION_STATE_FILE") || transition_mode=""
  transition_owner=$(portable_owner "$TRANSITION_STATE_FILE") || transition_owner=""
  state_owner=$(portable_owner "$STATE_DIR") || state_owner="invalid"
  if [ "$transition_mode" != 600 ] ||
    [ -z "$transition_owner" ] || [ "$transition_owner" != "$state_owner" ]; then
    echo "Legacy journal transition marker is not private to the runtime-state owner." >&2
    return 1
  fi
  transition_line_count=$(awk 'NF { count += 1 } END { print count + 0 }' \
    "$TRANSITION_STATE_FILE")
  if [ "$transition_line_count" -ne 8 ]; then
    echo "Legacy journal transition marker is malformed or belongs to another release." >&2
    return 1
  fi
  for transition_key in schema_version previous_release_sha target_release_sha \
    edge_container_id edge_state_sha256 backend_container_id \
    backend_state_sha256 services_stopped_at_utc
  do
    if [ "$(grep -Ec "^$transition_key=" "$TRANSITION_STATE_FILE")" -ne 1 ]; then
      echo "Legacy journal transition marker is malformed or belongs to another release." >&2
      return 1
    fi
  done

  transition_edge_id=$(transition_value edge_container_id)
  transition_edge_fingerprint=$(transition_value edge_state_sha256)
  transition_backend_id=$(transition_value backend_container_id)
  transition_backend_fingerprint=$(transition_value backend_state_sha256)
  transition_stopped_at=$(transition_value services_stopped_at_utc)
  if [ "$(transition_value schema_version)" != 2 ] ||
    [ "$(transition_value previous_release_sha)" != "$previous_sha" ] ||
    [ "$(transition_value target_release_sha)" != "$release_sha" ] ||
    ! printf '%s\n' "$transition_edge_id" | grep -Eq '^[0-9a-f]{64}$' ||
    ! printf '%s\n' "$transition_edge_fingerprint" | grep -Eq '^[0-9a-f]{64}$' ||
    ! printf '%s\n' "$transition_backend_id" | grep -Eq '^[0-9a-f]{64}$' ||
    ! printf '%s\n' "$transition_backend_fingerprint" | grep -Eq '^[0-9a-f]{64}$' ||
    ! transition_stopped_epoch=$(receipt_timestamp_epoch "$transition_stopped_at"); then
    echo "Legacy journal transition marker is malformed or belongs to another release." >&2
    return 1
  fi
  assert_legacy_transition_services_quiesced
}

stage_or_validate_legacy_transition() {
  prepare_private_state_directory || return 1
  if [ -e "$TRANSITION_STATE_FILE" ] || [ -L "$TRANSITION_STATE_FILE" ]; then
    validate_legacy_transition_marker
    return
  fi

  transition_edge_id=$(docker inspect --format '{{.Id}}' subframe-edge-1 2>/dev/null || true)
  transition_backend_id=$(docker inspect --format '{{.Id}}' subframe-backend-1 2>/dev/null || true)
  if ! printf '%s\n' "$transition_edge_id" | grep -Eq '^[0-9a-f]{64}$' ||
    ! printf '%s\n' "$transition_backend_id" | grep -Eq '^[0-9a-f]{64}$'; then
    echo "Cannot identify the legacy public edge and backend before the journal transition." >&2
    return 1
  fi
  if compose stop edge app-edge backend; then
    :
  else
    if ! stop_legacy_services_fail_closed; then
      echo "Manual intervention is required to close the legacy writers." >&2
    fi
    echo "Could not quiesce the legacy public edge and backend before the journal transition." >&2
    return 1
  fi
  stopped_edge_id=$(docker inspect --format '{{.Id}}' subframe-edge-1 2>/dev/null || true)
  stopped_backend_id=$(docker inspect --format '{{.Id}}' subframe-backend-1 2>/dev/null || true)
  stopped_edge_running=$(docker inspect --format '{{.State.Running}}' \
    "$transition_edge_id" 2>/dev/null || true)
  stopped_backend_running=$(docker inspect --format '{{.State.Running}}' \
    "$transition_backend_id" 2>/dev/null || true)
  if [ "$stopped_edge_id" != "$transition_edge_id" ] ||
    [ "$stopped_edge_running" != false ] ||
    [ "$stopped_backend_id" != "$transition_backend_id" ] ||
    [ "$stopped_backend_running" != false ]; then
    stop_legacy_services_fail_closed
    echo "Could not prove that the legacy public edge and backend are quiesced." >&2
    return 1
  fi
  transition_edge_fingerprint=$(container_runtime_fingerprint "$transition_edge_id") || {
    echo "Could not fingerprint the quiesced legacy edge." >&2
    return 1
  }
  transition_backend_fingerprint=$(container_runtime_fingerprint "$transition_backend_id") || {
    echo "Could not fingerprint the quiesced legacy backend." >&2
    return 1
  }
  transition_stopped_at=$(date -u +%Y%m%dT%H%M%SZ)
  if ! printf '%s\n' "$transition_edge_fingerprint" | grep -Eq '^[0-9a-f]{64}$' ||
    ! printf '%s\n' "$transition_backend_fingerprint" | grep -Eq '^[0-9a-f]{64}$' ||
    ! printf '%s\n' "$transition_stopped_at" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'; then
    echo "Could not create canonical legacy transition evidence." >&2
    return 1
  fi
  transition_state_temp=$(mktemp "$STATE_DIR/.legacy-journal-bootstrap-transition.XXXXXX") || return 1
  if ! printf '%s\n' \
    "schema_version=2" \
    "previous_release_sha=$previous_sha" \
    "target_release_sha=$release_sha" \
    "edge_container_id=$transition_edge_id" \
    "edge_state_sha256=$transition_edge_fingerprint" \
    "backend_container_id=$transition_backend_id" \
    "backend_state_sha256=$transition_backend_fingerprint" \
    "services_stopped_at_utc=$transition_stopped_at" > "$transition_state_temp" ||
    ! chmod 600 "$transition_state_temp" ||
    ! mv -f -- "$transition_state_temp" "$TRANSITION_STATE_FILE"; then
    rm -f -- "$transition_state_temp"
    echo "Could not persist the legacy journal transition marker." >&2
    return 1
  fi
  transition_state_temp=""
  if ! sync "$TRANSITION_STATE_FILE" "$STATE_DIR"; then
    rm -f -- "$TRANSITION_STATE_FILE"
    sync "$STATE_DIR" >/dev/null 2>&1 || true
    echo "Could not make the legacy journal transition marker durable." >&2
    return 1
  fi
  echo "Legacy edge and backend are quiesced and the transition marker is durable." >&2
  echo "Create a fresh backup now, copy it off-server, and run verify-backup.sh --drill." >&2
  echo "Then rerun this exact release; do not restart the edge between invocations." >&2
  return 10
}
