#!/bin/sh
set -eu
umask 077

usage() {
  echo "Usage: $0 [--drill] BACKUP_DIRECTORY INDEPENDENT_BACKUP_DIRECTORY" >&2
  exit 2
}

run_drill=0
if [ "${1:-}" = "--drill" ]; then
  run_drill=1
  shift
fi
[ "$#" -eq 2 ] || usage

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"
STATE_DIR="$ROOT_DIR/.runtime"
RECEIPT_FILE="$STATE_DIR/last-backup-restore-drill"
BACKUP_DIR_INPUT=$1
INDEPENDENT_DIR_INPUT=$2
RESTORE_SIZE_MULTIPLIER=2
RESTORE_FIXED_RESERVE_BYTES=10737418240

if [ "$run_drill" -eq 1 ]; then
  # Any attempted new drill invalidates an older receipt before validation.
  rm -f -- "$RECEIPT_FILE"
fi

if [ ! -f "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
  echo "Production env must be a regular file: $ENV_FILE" >&2
  exit 1
fi

canonical_directory() {
  directory_input=$1
  directory_label=$2
  case "$directory_input" in
    /*) ;;
    *)
      echo "$directory_label must be an absolute canonical path." >&2
      return 1
      ;;
  esac
  if [ ! -d "$directory_input" ] || [ -L "$directory_input" ]; then
    echo "$directory_label must be a real directory, not a symlink." >&2
    return 1
  fi
  canonical=$(CDPATH= cd -- "$directory_input" && pwd -P)
  if [ "$canonical" != "$directory_input" ]; then
    echo "$directory_label must contain no symlink or dot components." >&2
    return 1
  fi
  printf '%s\n' "$canonical"
}

BACKUP_DIR=$(canonical_directory "$BACKUP_DIR_INPUT" "Backup directory")
INDEPENDENT_DIR=$(canonical_directory \
  "$INDEPENDENT_DIR_INPUT" \
  "Independent backup directory")
if [ "$BACKUP_DIR" = "$INDEPENDENT_DIR" ]; then
  echo "Independent backup directory must differ from the server backup." >&2
  exit 1
fi

IDENTITY_FILE="${SUBFRAME_BACKUP_AGE_IDENTITY_FILE:-}"
if [ -z "$IDENTITY_FILE" ] || [ ! -f "$IDENTITY_FILE" ] || [ -L "$IDENTITY_FILE" ]; then
  echo "SUBFRAME_BACKUP_AGE_IDENTITY_FILE must name a regular age identity file." >&2
  exit 1
fi

env_value() {
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    checksum_output=$(sha256sum "$1") || return 1
  elif command -v shasum >/dev/null 2>&1; then
    checksum_output=$(shasum -a 256 "$1") || return 1
  else
    echo "sha256sum or shasum is required." >&2
    return 1
  fi
  digest=$(printf '%s\n' "$checksum_output" | awk 'NR == 1 { print $1 }')
  if ! printf '%s\n' "$digest" | grep -Eq '^[0-9A-Fa-f]{64}$'; then
    echo "Could not calculate a valid SHA-256 for $1." >&2
    return 1
  fi
  printf '%s' "$digest" | tr 'A-F' 'a-f'
}

directory_device() {
  device=$(stat -c '%d' -- "$1" 2>/dev/null) || {
    echo "GNU/Linux stat -c support is required for independent-copy validation." >&2
    return 1
  }
  case "$device" in
    ''|*[!0-9]*)
      echo "Could not determine a numeric filesystem device for $1." >&2
      return 1
      ;;
  esac
  printf '%s\n' "$device"
}

read_independent_mount_options() {
  if ! command -v findmnt >/dev/null 2>&1; then
    echo "Linux findmnt is required for independent-copy mount validation." >&2
    return 1
  fi
  mount_options=$(
    findmnt --noheadings --raw --target "$1" --output OPTIONS 2>/dev/null
  ) || {
    echo "Could not resolve the independent backup mount with findmnt." >&2
    return 1
  }
  mount_option_line_count=$(printf '%s\n' "$mount_options" |
    wc -l |
    tr -d '[:space:]')
  if [ -z "$mount_options" ] || [ "$mount_option_line_count" -ne 1 ]; then
    echo "Independent backup mount options do not prove read-only access." >&2
    return 1
  fi
  case ",$mount_options," in
    *,rw,*)
      echo "Independent backup directory is on a writable mount; remount it read-only." >&2
      return 1
      ;;
  esac
  case ",$mount_options," in
    *,ro,*) ;;
    *)
      echo "Independent backup mount options do not prove read-only access." >&2
      return 1
      ;;
  esac
  printf '%s\n' "$mount_options"
}

validate_backup_directory() {
  directory=$1
  directory_label=$2
  entry_count=$(find "$directory" -mindepth 1 -maxdepth 1 -print |
    wc -l |
    tr -d '[:space:]')
  if [ "$entry_count" -ne 4 ]; then
    echo "$directory_label must contain exactly the four backup files." >&2
    return 1
  fi

  for required_file in \
    postgres.dump.age \
    app-data.tgz.age \
    manifest.txt \
    SHA256SUMS
  do
    if [ ! -f "$directory/$required_file" ] || [ -L "$directory/$required_file" ]; then
      echo "$directory_label is missing a regular backup file: $required_file" >&2
      return 1
    fi
  done

  checksum_line_count=$(awk 'NF { count += 1 } END { print count + 0 }' \
    "$directory/SHA256SUMS")
  if [ "$checksum_line_count" -ne 3 ]; then
    echo "$directory_label SHA256SUMS must contain exactly three entries." >&2
    return 1
  fi
  if ! awk '
    NF != 2 { exit 1 }
    $2 != "postgres.dump.age" &&
      $2 != "app-data.tgz.age" &&
      $2 != "manifest.txt" { exit 1 }
  ' "$directory/SHA256SUMS"; then
    echo "$directory_label SHA256SUMS contains an unexpected path or malformed entry." >&2
    return 1
  fi

  for checked_file in postgres.dump.age app-data.tgz.age manifest.txt
  do
    expected_sha=$(awk -v filename="$checked_file" '
      $2 == filename { count += 1; value = $1 }
      END {
        if (count != 1) {
          exit 1
        }
        print value
      }
    ' "$directory/SHA256SUMS")
    if ! printf '%s\n' "$expected_sha" | grep -Eq '^[0-9A-Fa-f]{64}$'; then
      echo "$directory_label has an invalid checksum for $checked_file." >&2
      return 1
    fi
    expected_sha=$(printf '%s' "$expected_sha" | tr 'A-F' 'a-f')
    actual_sha=$(sha256_file "$directory/$checked_file")
    if [ "$actual_sha" != "$expected_sha" ]; then
      echo "$directory_label ciphertext checksum mismatch: $checked_file" >&2
      return 1
    fi
  done
}

manifest_value() {
  manifest_file=$1
  manifest_key=$2
  awk -v key="$manifest_key" '
    index($0, key "=") == 1 {
      count += 1
      value = substr($0, length(key) + 2)
    }
    END {
      if (count != 1) {
        exit 1
      }
      print value
    }
  ' "$manifest_file"
}

validate_backup_directory "$BACKUP_DIR" "Server backup"
validate_backup_directory "$INDEPENDENT_DIR" "Independent backup copy"

server_device=$(directory_device "$BACKUP_DIR")
independent_device=$(directory_device "$INDEPENDENT_DIR")
if [ "$server_device" = "$independent_device" ]; then
  echo "Independent backup copy must be mounted on a different filesystem device." >&2
  exit 1
fi
independent_mount_options=$(read_independent_mount_options "$INDEPENDENT_DIR")

for copied_file in \
  postgres.dump.age \
  app-data.tgz.age \
  manifest.txt \
  SHA256SUMS
do
  server_sha=$(sha256_file "$BACKUP_DIR/$copied_file")
  independent_sha=$(sha256_file "$INDEPENDENT_DIR/$copied_file")
  if [ "$server_sha" != "$independent_sha" ]; then
    echo "Independent backup copy differs from server file: $copied_file" >&2
    exit 1
  fi
done

manifest_line_count=$(awk 'NF { count += 1 } END { print count + 0 }' \
  "$BACKUP_DIR/manifest.txt")
if [ "$manifest_line_count" -ne 5 ]; then
  echo "Backup manifest must contain exactly five fields." >&2
  exit 1
fi
if ! awk -F= '
  $1 != "created_at_utc" &&
    $1 != "release_sha" &&
    $1 != "encrypted" &&
    $1 != "database_size_bytes" &&
    $1 != "app_data_size_bytes" { exit 1 }
' "$BACKUP_DIR/manifest.txt"; then
  echo "Backup manifest contains an unexpected field." >&2
  exit 1
fi

backup_id=$(manifest_value "$BACKUP_DIR/manifest.txt" created_at_utc)
backup_release_sha=$(manifest_value "$BACKUP_DIR/manifest.txt" release_sha)
encrypted=$(manifest_value "$BACKUP_DIR/manifest.txt" encrypted)
database_size_bytes=$(manifest_value \
  "$BACKUP_DIR/manifest.txt" \
  database_size_bytes)
app_data_size_bytes=$(manifest_value \
  "$BACKUP_DIR/manifest.txt" \
  app_data_size_bytes)
if ! printf '%s\n' "$backup_id" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'; then
  echo "Backup manifest has an invalid created_at_utc value." >&2
  exit 1
fi
if [ "${BACKUP_DIR##*/}" != "$backup_id" ] ||
  [ "${INDEPENDENT_DIR##*/}" != "$backup_id" ]; then
  echo "Both backup directory names must match manifest created_at_utc." >&2
  exit 1
fi
if ! printf '%s\n' "$backup_release_sha" | grep -Eq '^[0-9A-Fa-f]{40}$'; then
  echo "Backup manifest has an invalid release_sha value." >&2
  exit 1
fi
if [ "$encrypted" != true ]; then
  echo "Backup manifest must declare encrypted=true." >&2
  exit 1
fi
for measured_size in "$database_size_bytes" "$app_data_size_bytes"
do
  case "$measured_size" in
    ''|*[!0-9]*)
      echo "Backup manifest has an invalid size estimate." >&2
      exit 1
      ;;
  esac
done

POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
TARGET_RELEASE_SHA=$(git -C "$ROOT_DIR" rev-parse HEAD)
CONFIGURED_RELEASE_SHA=$(env_value SUBFRAME_RELEASE_SHA)
if [ -z "$POSTGRES_USER" ]; then
  echo "POSTGRES_USER is required." >&2
  exit 1
fi
if [ "$CONFIGURED_RELEASE_SHA" != "$TARGET_RELEASE_SHA" ]; then
  echo "SUBFRAME_RELEASE_SHA must match the checked-out release before validation." >&2
  exit 1
fi
if [ "$backup_release_sha" != "$TARGET_RELEASE_SHA" ]; then
  echo "Backup release_sha must match the checked-out release before validation." >&2
  exit 1
fi

for required_command in age df docker findmnt stat tar
do
  command -v "$required_command" >/dev/null 2>&1 || {
    echo "$required_command is required." >&2
    exit 1
  }
done

export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="$TARGET_RELEASE_SHA"
compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" \
    -f "$COMPOSE_FILE" "$@"
}

compose config --quiet
docker_root=$(docker info --format '{{.DockerRootDir}}')
case "$docker_root" in
  /*) ;;
  *)
    echo "DockerRootDir must be an absolute path." >&2
    exit 1
    ;;
esac
if [ ! -d "$docker_root" ] || [ -L "$docker_root" ]; then
  echo "DockerRootDir must be a real directory for capacity validation." >&2
  exit 1
fi

available_bytes() {
  available_kib=$(df -Pk "$docker_root" |
    awk 'END { print $4 }')
  case "$available_kib" in
    ''|*[!0-9]*)
      echo "Could not determine Docker filesystem free space." >&2
      return 1
      ;;
  esac
  printf '%s\n' "$((available_kib * 1024))"
}

require_restore_capacity() {
  estimated_bytes=$1
  restore_label=$2
  required_bytes=$((estimated_bytes * RESTORE_SIZE_MULTIPLIER + RESTORE_FIXED_RESERVE_BYTES))
  if [ "$required_bytes" -lt "$estimated_bytes" ]; then
    echo "Restore capacity arithmetic overflowed for $restore_label." >&2
    return 1
  fi
  free_bytes=$(available_bytes)
  if [ "$free_bytes" -lt "$required_bytes" ]; then
    echo "Insufficient Docker filesystem space for $restore_label restore drill." >&2
    echo "Required free bytes: $required_bytes; available: $free_bytes." >&2
    return 1
  fi
}

WORK_DIR=$(mktemp -d "${TMPDIR:-/tmp}/subframe-backup-verify.XXXXXX")
backup_token=$(printf '%s' "$backup_id" | tr 'A-Z' 'a-z')
DRILL_DATABASE="subframe_restore_drill_$backup_token"
DRILL_VOLUME="subframe-restore-drill-$backup_token-app-data"
active_consumer_pid=""
active_decrypt_pid=""
active_fifo=""
database_created=0
volume_created=0
work_dir_created=1

terminate_active_stream() {
  for active_pid in "${active_consumer_pid:-}" "${active_decrypt_pid:-}"
  do
    if [ -n "$active_pid" ]; then
      kill "$active_pid" 2>/dev/null || true
    fi
  done
  for active_pid in "${active_consumer_pid:-}" "${active_decrypt_pid:-}"
  do
    if [ -n "$active_pid" ]; then
      wait "$active_pid" 2>/dev/null || true
    fi
  done
  if [ -n "${active_fifo:-}" ]; then
    rm -f -- "$active_fifo"
  fi
  active_consumer_pid=""
  active_decrypt_pid=""
  active_fifo=""
}

remove_drill_database() {
  if [ "$database_created" -eq 0 ]; then
    return 0
  fi
  if ! compose exec -T db dropdb --username "$POSTGRES_USER" \
    --if-exists --force "$DRILL_DATABASE"; then
    echo "Failed to remove exact restore-drill database: $DRILL_DATABASE" >&2
    return 1
  fi
  database_created=0
}

remove_drill_volume() {
  if [ "$volume_created" -eq 0 ]; then
    return 0
  fi
  if ! docker volume rm "$DRILL_VOLUME" >/dev/null; then
    echo "Failed to remove exact restore-drill volume: $DRILL_VOLUME" >&2
    return 1
  fi
  volume_created=0
}

cleanup_resources() {
  cleanup_failed=0
  terminate_active_stream
  remove_drill_database || cleanup_failed=1
  remove_drill_volume || cleanup_failed=1
  if [ "$work_dir_created" -eq 1 ]; then
    if rmdir -- "$WORK_DIR"; then
      work_dir_created=0
    else
      echo "Failed to remove restore-drill working directory: $WORK_DIR" >&2
      cleanup_failed=1
    fi
  fi
  [ "$cleanup_failed" -eq 0 ]
}

cleanup_on_exit() {
  exit_status=$?
  trap - EXIT HUP INT TERM
  cleanup_resources || true
  exit "$exit_status"
}

cleanup_on_signal() {
  trap - EXIT HUP INT TERM
  cleanup_resources || true
  exit 1
}

trap cleanup_on_exit EXIT
trap cleanup_on_signal HUP INT TERM

decrypt_to_command() {
  encrypted_file=$1
  shift
  active_fifo="$WORK_DIR/decrypt.fifo"
  mkfifo -m 600 "$active_fifo"
  age --decrypt --identity "$IDENTITY_FILE" "$encrypted_file" \
    > "$active_fifo" &
  active_decrypt_pid=$!
  "$@" < "$active_fifo" &
  active_consumer_pid=$!

  consumer_status=0
  wait "$active_consumer_pid" || consumer_status=$?
  if [ "$consumer_status" -ne 0 ]; then
    kill "$active_decrypt_pid" 2>/dev/null || true
  fi
  decrypt_status=0
  wait "$active_decrypt_pid" || decrypt_status=$?
  rm -f -- "$active_fifo"
  active_consumer_pid=""
  active_decrypt_pid=""
  active_fifo=""
  if [ "$consumer_status" -ne 0 ] || [ "$decrypt_status" -ne 0 ]; then
    echo "Authenticated backup stream validation failed." >&2
    return 1
  fi
}

decrypt_to_command \
  "$BACKUP_DIR/postgres.dump.age" \
  compose exec -T db pg_restore --list
decrypt_to_command \
  "$BACKUP_DIR/app-data.tgz.age" \
  tar -tzf -

if [ "$run_drill" -eq 0 ]; then
  if ! cleanup_resources; then
    exit 1
  fi
  trap - EXIT HUP INT TERM
  echo "Encrypted server backup and independent copy verification succeeded; restore drill was not requested."
  exit 0
fi

database_exists=$(compose exec -T db psql --username "$POSTGRES_USER" \
  --dbname postgres --tuples-only --no-align \
  --command "SELECT 1 FROM pg_database WHERE datname = '$DRILL_DATABASE';")
if [ -n "$(printf '%s' "$database_exists" | tr -d '[:space:]')" ]; then
  echo "Refusing to use existing restore-drill database: $DRILL_DATABASE" >&2
  exit 1
fi
if docker volume inspect "$DRILL_VOLUME" >/dev/null 2>&1; then
  echo "Refusing to use existing restore-drill volume: $DRILL_VOLUME" >&2
  exit 1
fi

require_restore_capacity "$database_size_bytes" "database"
compose exec -T db createdb --username "$POSTGRES_USER" \
  --template=template0 "$DRILL_DATABASE"
database_created=1
decrypt_to_command \
  "$BACKUP_DIR/postgres.dump.age" \
  compose exec -T db pg_restore --username "$POSTGRES_USER" \
  --dbname "$DRILL_DATABASE" --exit-on-error --no-owner --no-privileges
compose exec -T db psql --username "$POSTGRES_USER" \
  --dbname "$DRILL_DATABASE" --tuples-only --no-align \
  --command "SELECT 1;" | grep -qx '1'
remove_drill_database

# Database cleanup must complete before app-data capacity or volume creation.
require_restore_capacity "$app_data_size_bytes" "app-data"
docker volume create "$DRILL_VOLUME" >/dev/null
volume_created=1
decrypt_to_command \
  "$BACKUP_DIR/app-data.tgz.age" \
  docker run --rm -i \
  -v "$DRILL_VOLUME:/restore" \
  alpine:3.20 \
  sh -eu -c 'cd /restore && tar -xzf -'
docker run --rm \
  -v "$DRILL_VOLUME:/restore:ro" \
  alpine:3.20 \
  sh -eu -c 'test -d /restore'
remove_drill_volume

if ! cleanup_resources; then
  exit 1
fi
trap - EXIT HUP INT TERM

install -d -m 700 "$STATE_DIR"
receipt_temp=$(mktemp "$STATE_DIR/.last-backup-restore-drill.XXXXXX")
cleanup_receipt_temp() {
  if [ -n "${receipt_temp:-}" ]; then
    rm -f -- "$receipt_temp"
  fi
}
receipt_promoting=0
cleanup_receipt_on_signal() {
  trap - EXIT HUP INT TERM
  cleanup_receipt_temp
  if [ "$receipt_promoting" -eq 1 ]; then
    rm -f -- "$RECEIPT_FILE"
  fi
  exit 1
}
trap cleanup_receipt_temp EXIT
trap cleanup_receipt_on_signal HUP INT TERM
verified_at=$(date -u +%Y%m%dT%H%M%SZ)
local_sums_sha=$(sha256_file "$BACKUP_DIR/SHA256SUMS")
printf '%s\n' \
  "verified_at_utc=$verified_at" \
  "backup_created_at_utc=$backup_id" \
  "backup_release_sha=$backup_release_sha" \
  "target_release_sha=$TARGET_RELEASE_SHA" \
  "sha256sums_sha256=$local_sums_sha" \
  "independent_backup_copy_verified=true" \
  "server_backup_copy_device=$server_device" \
  "independent_backup_copy_device=$independent_device" \
  "independent_backup_copy_distinct_filesystem=true" \
  "independent_backup_copy_mount_detected=true" \
  "independent_backup_copy_mount_read_only=true" \
  "ciphertext_checksums=true" \
  "age_decrypt=true" \
  "pg_restore_archive=true" \
  "tar_archive=true" \
  "restore_drill=true" \
  "database_restore=true" \
  "database_removed_before_app_restore=true" \
  "volume_restore=true" \
  "sequential_restore=true" \
  "restore_size_multiplier=$RESTORE_SIZE_MULTIPLIER" \
  "restore_fixed_reserve_bytes=$RESTORE_FIXED_RESERVE_BYTES" \
  "schema_rollback_evidence=postgres_dump" \
  "app_data_authoritative=false" \
  "cleanup=true" > "$receipt_temp"
chmod 600 "$receipt_temp"
receipt_promoting=1
mv -f -- "$receipt_temp" "$RECEIPT_FILE"
receipt_temp=""
trap - EXIT HUP INT TERM

echo "Backup restore drill succeeded and receipt was recorded: $RECEIPT_FILE"
