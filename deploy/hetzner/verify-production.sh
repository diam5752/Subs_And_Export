#!/bin/sh
set -eu

usage() {
  echo "Usage: $0 [--candidate]" >&2
  exit 2
}

candidate_mode=0
if [ "${1:-}" = "--candidate" ]; then
  candidate_mode=1
  shift
fi
[ "$#" -eq 0 ] || usage

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
COMPOSE_FILE="$ROOT_DIR/deploy/hetzner/docker-compose.production.yml"
ENV_FILE="${SUBFRAME_ENV_FILE:-$ROOT_DIR/.env.production}"
STATE_FILE="$ROOT_DIR/.runtime/last-successful-release"
ERASURE_RECEIPT_FILE="$ROOT_DIR/.runtime/last-erasure-reconciliation"
CONTINUITY_STATE_FILE="$ROOT_DIR/.runtime/privacy-continuity-id"
ERASURE_ANCHOR_DIR="$ROOT_DIR/.runtime/privacy-erasure-anchor"
export SUBFRAME_ERASURE_ANCHOR_DIR="$ERASURE_ANCHOR_DIR"
. "$ROOT_DIR/deploy/hetzner/lib/verify-contracts.sh"
. "$ROOT_DIR/deploy/hetzner/lib/verify-edge.sh"

if [ ! -f "$ENV_FILE" ]; then
  echo "Production env is required: $ENV_FILE" >&2
  exit 1
fi
if grep -Eq \
  '^[[:space:]]*(export[[:space:]]+)?(GSP_GCS_[A-Z0-9_]*|GOOGLE_APPLICATION_CREDENTIALS)[[:space:]]*=' \
  "$ENV_FILE"; then
  echo "Retired GCS settings remain in the production env." >&2
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
if ! "$ROOT_DIR/deploy/hetzner/verify-gcs-retirement.sh"; then
  echo "Legacy GCS retirement evidence is missing or invalid." >&2
  exit 1
fi
if [ ! -f "$CONTINUITY_STATE_FILE" ] || [ -L "$CONTINUITY_STATE_FILE" ]; then
  echo "Live privacy continuity state is required: $CONTINUITY_STATE_FILE" >&2
  exit 1
fi
privacy_continuity_id=$(cat "$CONTINUITY_STATE_FILE")
if ! printf '%s\n' "$privacy_continuity_id" | grep -Eq '^[0-9a-f]{64}$'; then
  echo "Live privacy continuity state is malformed." >&2
  exit 1
fi
export SUBFRAME_PRIVACY_CONTINUITY_ID="$privacy_continuity_id"

release_sha="${SUBFRAME_RELEASE_SHA:-$(env_value SUBFRAME_RELEASE_SHA)}"
preview_port="${SUBFRAME_PREVIEW_PORT:-$(env_value SUBFRAME_PREVIEW_PORT)}"
preview_port="${preview_port:-18090}"
case "$preview_port" in
  *[!0-9]*|'')
    echo "SUBFRAME_PREVIEW_PORT must be numeric." >&2
    exit 1
    ;;
esac
if [ -z "$release_sha" ]; then
  echo "SUBFRAME_RELEASE_SHA is required." >&2
  exit 1
fi
google_client_id=$(env_value GOOGLE_CLIENT_ID)
if [ -z "$google_client_id" ]; then
  echo "Google client ID is required." >&2
  exit 1
fi
if [ -z "$(env_value ELEVENLABS_API_KEY)" ]; then
  echo "ElevenLabs production API key is required." >&2
  exit 1
fi
observability_admin_user_ids=$(env_value GSP_OBSERVABILITY_ADMIN_USER_IDS)
if ! printf '%s\n' "$observability_admin_user_ids" | grep -Eq \
  '^[0-9a-f]{16}(,[0-9a-f]{16})*$'; then
  echo "A valid immutable observability admin user ID allowlist is required." >&2
  exit 1
fi
export SUBFRAME_ENV_FILE="$ENV_FILE"
export SUBFRAME_RELEASE_SHA="$release_sha"

# REGRESSION: loopback health stayed green while the shared public HTTP/3 path
# made a 49 MiB authenticated download take more than three minutes.
if ! "$ROOT_DIR/deploy/hetzner/verify-public-edge.sh"; then
  echo "Public download transport verification failed." >&2
  exit 1
fi

verify_container_runtime_contracts
verify_storage_and_provider_contracts
verify_edge_and_endpoint_contracts
