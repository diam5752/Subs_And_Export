#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
image_tag="${CADDY_BUILD_IMAGE:-ascentia-security/caddy:2.11.7-20261027}"
platform="${CADDY_BUILD_PLATFORM:-linux/amd64}"
docker buildx build --load --platform "$platform" --tag "$image_tag" \
  --file "$SCRIPT_DIR/Dockerfile" "$SCRIPT_DIR" >&2
image_id=$(docker image inspect --format '{{.Id}}' "$image_tag")
printf '%s\n' "$image_id" | grep -Eq '^sha256:[0-9a-f]{64}$'
printf '%s\n' "$image_id"
