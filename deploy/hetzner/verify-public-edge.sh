#!/bin/sh
set -eu

PUBLIC_HEALTH_URL=https://gsubs.gr/health
CURL_BIN=${CURL_BIN:-curl}
mode=healthy

case "$#" in
  0) ;;
  1)
    if [ "$1" != --maintenance ]; then
      echo "Usage: $0 [--maintenance]" >&2
      exit 2
    fi
    mode=maintenance
    ;;
  *)
    echo "Usage: $0 [--maintenance]" >&2
    exit 2
    ;;
esac

fail() {
  echo "Public GSubs transport policy is invalid: $1" >&2
  exit 1
}

if ! command -v "$CURL_BIN" >/dev/null 2>&1; then
  fail "curl is required"
fi

edge_headers=$(mktemp /tmp/gsubs-public-edge.XXXXXX) || \
  fail "could not allocate a response-header file"
edge_body=$(mktemp /tmp/gsubs-public-edge-body.XXXXXX) || {
  rm -f -- "$edge_headers"
  fail "could not allocate a response-body file"
}
cleanup() {
  rm -f -- "$edge_headers" "$edge_body"
}
trap cleanup 0 1 2 3 15

if ! edge_result=$("$CURL_BIN" \
  --http2 \
  --silent \
  --show-error \
  --noproxy '*' \
  --connect-timeout 10 \
  --max-time 20 \
  --max-filesize 1048576 \
  --output "$edge_body" \
  --dump-header "$edge_headers" \
  --write-out '%{http_version}|%{http_code}' \
  "$PUBLIC_HEALTH_URL"); then
  fail "the public health probe failed"
fi

if grep -Eiq '^alt-svc:.*h3' "$edge_headers"; then
  fail "the public edge advertises the quarantined HTTP/3 path"
fi

if [ "$mode" = healthy ]; then
  if [ "$edge_result" != "2|200" ]; then
    fail "expected an HTTP/2 200 response, received $edge_result"
  fi
  if ! grep -Eiq \
    '^content-type:[[:space:]]*application/json([;[:space:]]|$)' \
    "$edge_headers"; then
    fail "the health response is not JSON"
  fi
  printf '%s\n' \
    'Verified public GSubs transport policy: HTTP/2 200 with no HTTP/3 advertisement.'
  exit 0
fi

if [ "$edge_result" != "2|503" ]; then
  fail "expected the reviewed HTTP/2 503 maintenance response, received $edge_result"
fi
if ! grep -Eiq \
  '^content-type:[[:space:]]*text/html([;[:space:]]|$)' \
  "$edge_headers"; then
  fail "the maintenance response is not HTML"
fi
if ! grep -Eiq '^retry-after:[[:space:]]*5[[:space:]]*$' "$edge_headers"; then
  fail "the maintenance response does not use the reviewed Retry-After value"
fi
if ! grep -Eiq \
  '^cache-control:[[:space:]]*no-store,[[:space:]]*max-age=0[[:space:]]*$' \
  "$edge_headers"; then
  fail "the maintenance response is not protected by the reviewed no-store policy"
fi
if ! grep -Fq 'Κάνουμε μια σύντομη αναβάθμιση.' "$edge_body"; then
  fail "the maintenance response is not the reviewed GSubs page"
fi

printf '%s\n' \
  'Verified fail-closed public GSubs maintenance: HTTP/2 503 with the reviewed no-store response.'
