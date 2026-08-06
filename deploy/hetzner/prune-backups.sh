#!/bin/sh
set -eu
umask 077

usage() {
  echo "Usage: $0 BACKUP_ROOT [RETENTION_DAYS]" >&2
  exit 2
}

[ "$#" -ge 1 ] && [ "$#" -le 2 ] || usage

BACKUP_ROOT_INPUT=$1
RETENTION_DAYS=${2:-${SUBFRAME_BACKUP_RETENTION_DAYS:-14}}

case "$RETENTION_DAYS" in
  ''|*[!0-9]*)
    echo "Retention days must be a positive integer." >&2
    exit 1
    ;;
esac
if [ "$RETENTION_DAYS" -eq 0 ]; then
  echo "Retention days must be a positive integer." >&2
  exit 1
fi

case "$BACKUP_ROOT_INPUT" in
  /*) ;;
  *)
    echo "Backup root must be an absolute canonical path." >&2
    exit 1
    ;;
esac
if [ ! -d "$BACKUP_ROOT_INPUT" ] || [ -L "$BACKUP_ROOT_INPUT" ]; then
  echo "Backup root must be a real directory, not a symlink." >&2
  exit 1
fi
BACKUP_ROOT=$(CDPATH= cd -- "$BACKUP_ROOT_INPUT" && pwd -P)
if [ "$BACKUP_ROOT" != "$BACKUP_ROOT_INPUT" ] || [ "$BACKUP_ROOT" = "/" ]; then
  echo "Backup root must be canonical and cannot be filesystem root." >&2
  exit 1
fi
if [ -n "${HOME:-}" ] && [ -d "$HOME" ]; then
  canonical_operator_home=$(CDPATH= cd -- "$HOME" && pwd -P)
  if [ "$BACKUP_ROOT" = "$canonical_operator_home" ]; then
    echo "Backup root cannot be the operator home directory." >&2
    exit 1
  fi
fi

command -v date >/dev/null 2>&1 || { echo "GNU date is required." >&2; exit 1; }
cutoff=$(
  date -u -d "$RETENTION_DAYS days ago" +%Y%m%dT%H%M%SZ 2>/dev/null
) || {
  echo "GNU date is required to calculate the retention cutoff." >&2
  exit 1
}
if ! printf '%s\n' "$cutoff" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'; then
  echo "Could not calculate a valid retention cutoff." >&2
  exit 1
fi

prune_backup_directory() {
  candidate=$1
  if [ ! -d "$candidate" ] || [ -L "$candidate" ]; then
    return 0
  fi
  backup_name=${candidate##*/}
  case "$backup_name" in
    [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) ;;
    *) return 0 ;;
  esac

  actual_candidate_parent=$(CDPATH= cd -- "$candidate/.." && pwd -P)
  if [ "$actual_candidate_parent" != "$BACKUP_ROOT" ]; then
    echo "Skipping retention candidate outside the canonical backup root: $candidate" >&2
    return 0
  fi
  for required_file in postgres.dump.age app-data.tgz.age manifest.txt SHA256SUMS
  do
    if [ ! -f "$candidate/$required_file" ] || [ -L "$candidate/$required_file" ]; then
      echo "Skipping incomplete retention candidate: $candidate" >&2
      return 0
    fi
  done
  entry_count=$(find "$candidate" -mindepth 1 -maxdepth 1 -print | wc -l | tr -d '[:space:]')
  if [ "$entry_count" -ne 4 ] ||
    ! grep -Fqx "created_at_utc=$backup_name" "$candidate/manifest.txt"; then
    echo "Skipping non-canonical retention candidate: $candidate" >&2
    return 0
  fi

  rm -f -- "$candidate/postgres.dump.age" \
    "$candidate/app-data.tgz.age" \
    "$candidate/manifest.txt" \
    "$candidate/SHA256SUMS"
  rmdir -- "$candidate"
  printf 'Pruned expired encrypted backup: %s\n' "$candidate"
}

for candidate in "$BACKUP_ROOT"/*
do
  if [ ! -d "$candidate" ] || [ -L "$candidate" ]; then
    continue
  fi
  backup_name=${candidate##*/}
  if awk -v backup="$backup_name" -v oldest="$cutoff" \
    'BEGIN { exit !(backup < oldest) }'; then
    prune_backup_directory "$candidate"
  fi
done
