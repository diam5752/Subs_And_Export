#!/bin/sh
set -eu
umask 077

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"
BACKUP_ROOT="${SUBFRAME_BACKUP_ROOT:-$ROOT_DIR/backups/production}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Production env is required: $ENV_FILE" >&2
  exit 1
fi

env_value() {
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

RETENTION_DAYS="${SUBFRAME_BACKUP_RETENTION_DAYS:-$(env_value SUBFRAME_BACKUP_RETENTION_DAYS)}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
RECIPIENT="${SUBFRAME_BACKUP_AGE_RECIPIENT:-$(env_value SUBFRAME_BACKUP_AGE_RECIPIENT)}"
POSTGRES_USER="${POSTGRES_USER:-$(env_value POSTGRES_USER)}"
POSTGRES_DB="${POSTGRES_DB:-$(env_value POSTGRES_DB)}"
if [ -z "$RECIPIENT" ] || [ -z "$POSTGRES_USER" ] || [ -z "$POSTGRES_DB" ]; then
  echo "Backup recipient and PostgreSQL identity are required." >&2
  exit 1
fi
command -v age >/dev/null 2>&1 || { echo "age is required." >&2; exit 1; }

export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="${SUBFRAME_RELEASE_SHA:-$(git -C "$ROOT_DIR" rev-parse HEAD)}"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
target="$BACKUP_ROOT/$timestamp"
install -d -m 700 "$target"

compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

cleanup() {
  if [ "${complete:-false}" != true ]; then
    rm -rf -- "$target"
  fi
}
trap cleanup EXIT INT TERM

encrypt_command() (
  output_file=$1
  shift
  fifo="$target/.age-input-$$"
  mkfifo -m 600 "$fifo"
  age --recipient "$RECIPIENT" --output "$output_file" < "$fifo" &
  age_pid=$!
  producer_status=0
  "$@" > "$fifo" || producer_status=$?
  rm -f "$fifo"
  age_status=0
  wait "$age_pid" || age_status=$?
  if [ "$producer_status" -ne 0 ] || [ "$age_status" -ne 0 ]; then
    rm -f "$output_file"
    echo "Encrypted backup stream failed." >&2
    exit 1
  fi
)

encrypt_command "$target/postgres.dump.age" \
  compose exec -T db pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom --no-owner
encrypt_command "$target/app-data.tgz.age" \
  docker run --rm -v subframe-app-data:/data:ro alpine:3.20 sh -c 'cd /data && tar -czf - .'

cat > "$target/manifest.txt" <<EOF
created_at_utc=$timestamp
release_sha=$SUBFRAME_RELEASE_SHA
encrypted=true
EOF
(cd "$target" && sha256sum postgres.dump.age app-data.tgz.age manifest.txt > SHA256SUMS)
find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" -exec rm -rf {} +
complete=true
printf '%s\n' "$target"
