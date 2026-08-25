#!/bin/sh
set -eu

PUBLIC_HEALTH_URL=https://gsubs.gr/health
CURL_BIN=${CURL_BIN:-curl}

fail() {
  echo "Public GSubs transport policy is invalid: $1" >&2
  exit 1
}

if ! command -v "$CURL_BIN" >/dev/null 2>&1; then
  fail "curl is required"
fi

edge_headers=$(mktemp /tmp/gsubs-public-edge.XXXXXX) || \
  fail "could not allocate a response-header file"
cleanup() {
  rm -f -- "$edge_headers"
}
trap cleanup 0 1 2 3 15

if ! edge_result=$("$CURL_BIN" \
  --http2 \
  --silent \
  --show-error \
  --fail \
  --noproxy '*' \
  --connect-timeout 10 \
  --max-time 20 \
  --output /dev/null \
  --dump-header "$edge_headers" \
  --write-out '%{http_version}|%{http_code}' \
  "$PUBLIC_HEALTH_URL"); then
  fail "the public health probe failed"
fi

if [ "$edge_result" != "2|200" ]; then
  fail "expected an HTTP/2 200 response, received $edge_result"
fi
if ! grep -Eiq \
  '^content-type:[[:space:]]*application/json([;[:space:]]|$)' \
  "$edge_headers"; then
  fail "the health response is not JSON"
fi
if grep -Eiq '^alt-svc:.*h3' "$edge_headers"; then
  fail "the public edge advertises the quarantined HTTP/3 path"
fi

printf '%s\n' \
  'Verified public GSubs transport policy: HTTP/2 200 with no HTTP/3 advertisement.'
