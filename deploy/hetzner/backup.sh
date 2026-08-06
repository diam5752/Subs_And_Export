#!/bin/sh
set -eu
umask 077

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Production env is required: $ENV_FILE" >&2
  exit 1
fi

unsafe_backup_root() {
  echo "Unsafe SUBFRAME_BACKUP_ROOT: $1" >&2
  exit 1
}

backup_root_is_default=0
if [ "${SUBFRAME_BACKUP_ROOT+x}" = x ]; then
  BACKUP_ROOT_INPUT=$SUBFRAME_BACKUP_ROOT
else
  BACKUP_ROOT_INPUT="$ROOT_DIR/backups/production"
  backup_root_is_default=1
fi
case "$BACKUP_ROOT_INPUT" in
  /*) ;;
  *) unsafe_backup_root "an absolute canonical path is required" ;;
esac
if [ "$BACKUP_ROOT_INPUT" = "/" ] || [ "$BACKUP_ROOT_INPUT" = "$ROOT_DIR" ]; then
  unsafe_backup_root "filesystem and repository roots are forbidden"
fi
if [ -n "${HOME:-}" ] && [ -d "$HOME" ]; then
  canonical_operator_home=$(CDPATH= cd -- "$HOME" && pwd -P)
  if [ "$BACKUP_ROOT_INPUT" = "$canonical_operator_home" ]; then
    unsafe_backup_root "the operator home directory is forbidden"
  fi
fi
if [ -L "$BACKUP_ROOT_INPUT" ]; then
  unsafe_backup_root "symlinks are forbidden"
fi

backup_parent_input=$(dirname -- "$BACKUP_ROOT_INPUT")
backup_root_name=$(basename -- "$BACKUP_ROOT_INPUT")
if [ "$backup_root_name" = "." ] || [ "$backup_root_name" = ".." ]; then
  unsafe_backup_root "a dedicated child directory is required"
fi
if [ ! -e "$backup_parent_input" ] && [ "$backup_root_is_default" -eq 1 ]; then
  install -d -m 700 "$backup_parent_input"
fi
if [ ! -d "$backup_parent_input" ] || [ -L "$backup_parent_input" ]; then
  unsafe_backup_root "the parent must be an existing real directory"
fi
canonical_backup_parent=$(CDPATH= cd -- "$backup_parent_input" && pwd -P)
if [ "$canonical_backup_parent" = "/" ]; then
  unsafe_backup_root "a top-level filesystem child is not a dedicated backup root"
fi
BACKUP_ROOT="$canonical_backup_parent/$backup_root_name"
if [ "$BACKUP_ROOT_INPUT" != "$BACKUP_ROOT" ]; then
  unsafe_backup_root "the path must already be canonical and contain no symlink or dot components"
fi
if [ -e "$BACKUP_ROOT" ] && [ ! -d "$BACKUP_ROOT" ]; then
  unsafe_backup_root "the target exists and is not a directory"
fi

env_value() {
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

RETENTION_DAYS="${SUBFRAME_BACKUP_RETENTION_DAYS:-$(env_value SUBFRAME_BACKUP_RETENTION_DAYS)}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
case "$RETENTION_DAYS" in
  ''|*[!0-9]*)
    echo "SUBFRAME_BACKUP_RETENTION_DAYS must be a positive integer." >&2
    exit 1
    ;;
esac
if [ "$RETENTION_DAYS" -eq 0 ]; then
  echo "SUBFRAME_BACKUP_RETENTION_DAYS must be a positive integer." >&2
  exit 1
fi
RECIPIENT="${SUBFRAME_BACKUP_AGE_RECIPIENT:-$(env_value SUBFRAME_BACKUP_AGE_RECIPIENT)}"
POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
if [ -z "$RECIPIENT" ] || [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DB" ]; then
  echo "Backup recipient and PostgreSQL identity are required." >&2
  exit 1
fi
command -v age >/dev/null 2>&1 || { echo "age is required." >&2; exit 1; }
command -v sha256sum >/dev/null 2>&1 || {
  echo "sha256sum is required." >&2
  exit 1
}

install -d -m 700 "$BACKUP_ROOT"
if [ -L "$BACKUP_ROOT" ]; then
  unsafe_backup_root "the created backup root resolved to a symlink"
fi
canonical_backup_root=$(CDPATH= cd -- "$BACKUP_ROOT" && pwd -P)
if [ "$canonical_backup_root" != "$BACKUP_ROOT" ]; then
  unsafe_backup_root "the created backup root is not canonical"
fi

export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="${SUBFRAME_RELEASE_SHA:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_ROOT/$timestamp"
if [ -e "$target" ] || [ -L "$target" ]; then
  echo "Backup target already exists: $target" >&2
  exit 1
fi

target_created=0
active_age_pid=""
active_fifo=""
active_producer_pid=""

terminate_active_stream() {
  for active_pid in "${active_producer_pid:-}" "${active_age_pid:-}"
  do
    if [ -n "$active_pid" ]; then
      kill "$active_pid" 2>/dev/null || true
    fi
  done
  for active_pid in "${active_producer_pid:-}" "${active_age_pid:-}"
  do
    if [ -n "$active_pid" ]; then
      wait "$active_pid" 2>/dev/null || true
    fi
  done
  if [ -n "${active_fifo:-}" ]; then
    rm -f -- "$active_fifo"
  fi
  active_age_pid=""
  active_fifo=""
  active_producer_pid=""
}

cleanup() {
  terminate_active_stream
  if [ "${complete:-false}" != true ] && [ "$target_created" -eq 1 ]; then
    rm -f -- \
      "${active_fifo:-$target/.age-input-$$}" \
      "$target/postgres.dump.age" \
      "$target/app-data.tgz.age" \
      "$target/manifest.txt" \
      "$target/SHA256SUMS"
    if [ -d "$target" ] && ! rmdir -- "$target"; then
      echo "Incomplete backup cleanup left a non-empty exact target: $target" >&2
    fi
  fi
  return 0
}

cleanup_on_signal() {
  trap - EXIT HUP INT TERM
  cleanup
  exit 1
}

trap cleanup EXIT
trap cleanup_on_signal HUP INT TERM

target_created=1
install -d -m 700 "$target"

compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

encrypt_command() {
  output_file=$1
  shift
  active_fifo="$target/.age-input-$$"
  mkfifo -m 600 "$active_fifo"
  age --recipient "$RECIPIENT" --output "$output_file" < "$active_fifo" &
  active_age_pid=$!
  "$@" > "$active_fifo" &
  active_producer_pid=$!

  producer_status=0
  wait "$active_producer_pid" || producer_status=$?
  if [ "$producer_status" -ne 0 ]; then
    kill "$active_age_pid" 2>/dev/null || true
  fi
  age_status=0
  wait "$active_age_pid" || age_status=$?
  rm -f -- "$active_fifo"
  active_age_pid=""
  active_fifo=""
  active_producer_pid=""
  if [ "$producer_status" -ne 0 ] || [ "$age_status" -ne 0 ]; then
    rm -f -- "$output_file"
    echo "Encrypted backup stream failed." >&2
    return 1
  fi
}

database_size_bytes=$(compose exec -T db psql \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --tuples-only \
  --no-align \
  --command "SELECT pg_database_size(current_database());" |
  tr -d '[:space:]')
app_data_size_bytes=$(docker run --rm \
  -v subframe-app-data:/data:ro \
  alpine:3.20 \
  sh -eu -c 'set -- $(du -sk /data); echo $(($1 * 1024))' |
  tr -d '[:space:]')
for measured_size in "$database_size_bytes" "$app_data_size_bytes"
do
  case "$measured_size" in
    ''|*[!0-9]*)
      echo "Backup size measurement returned an invalid byte count." >&2
      exit 1
      ;;
  esac
done

encrypt_command "$target/postgres.dump.age" \
  compose exec -T db pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom --no-owner
encrypt_command "$target/app-data.tgz.age" \
  docker run --rm -v subframe-app-data:/data:ro alpine:3.20 sh -c 'cd /data && tar -czf - .'

cat > "$target/manifest.txt" <<EOF
created_at_utc=$timestamp
release_sha=$SUBFRAME_RELEASE_SHA
encrypted=true
retention_days=$RETENTION_DAYS
database_size_bytes=$database_size_bytes
app_data_size_bytes=$app_data_size_bytes
EOF
(cd "$target" && sha256sum postgres.dump.age app-data.tgz.age manifest.txt > SHA256SUMS)
sums_output=$(sha256sum "$target/SHA256SUMS")
sums_sha=$(printf '%s\n' "$sums_output" | awk 'NR == 1 { print $1 }')
if ! printf '%s\n' "$sums_sha" | grep -Eq '^[0-9A-Fa-f]{64}$'; then
  echo "Could not calculate the backup SHA256SUMS digest." >&2
  exit 1
fi
"$ROOT_DIR/deploy/hetzner/prune-backups.sh" "$BACKUP_ROOT" "$RETENTION_DAYS"
complete=true
printf 'sha256sums_sha256=%s\n' "$sums_sha" >&2
printf '%s\n' "$target"
