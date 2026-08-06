#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
STATE_DIR="$ROOT_DIR/.runtime"
RECEIPT_FILE="$STATE_DIR/gcs-retirement-receipt"
EVIDENCE_FILE="$STATE_DIR/gcs-retirement-evidence"
RETIREMENT_BASE_SHA=d0d47ac774995d7eb06f1942c7e5eeacff69b1e1

fail() {
  echo "GCS retirement receipt is invalid: $1" >&2
  exit 1
}

file_mode() {
  path=$1
  if stat -c %a "$path" >/dev/null 2>&1; then
    stat -c %a "$path"
  else
    stat -f %Lp "$path"
  fi
}

require_private_regular_file() {
  path=$1
  label=$2
  if [ ! -f "$path" ] || [ -L "$path" ]; then
    fail "$label must be a regular non-symlink file"
  fi
  mode=$(file_mode "$path")
  if [ "$mode" != 600 ]; then
    fail "$label must have mode 600"
  fi
}

receipt_value() {
  sed -n "s/^$1=//p" "$RECEIPT_FILE" | tail -n 1
}

require_private_regular_file "$RECEIPT_FILE" receipt
require_private_regular_file "$EVIDENCE_FILE" evidence

receipt_lines=$(awk 'NF { count += 1 } END { print count + 0 }' "$RECEIPT_FILE")
if [ "$receipt_lines" -ne 9 ]; then
  fail "receipt must contain exactly nine non-empty fields"
fi

[ "$(receipt_value retired)" = true ] || fail "retired must be true"
[ "$(receipt_value scope)" = hetzner-production-whole-storage ] || \
  fail "scope must cover the complete retired production storage"
[ "$(receipt_value retirement_base_sha)" = "$RETIREMENT_BASE_SHA" ] || \
  fail "retirement base SHA does not match the removed runtime"
[ "$(receipt_value objects_after)" = 0 ] || fail "objects_after must be zero"
[ "$(receipt_value credentials_revoked)" = true ] || \
  fail "retired credentials must be revoked"

retirement_basis=$(receipt_value retirement_basis)
bucket_identity_sha256=$(receipt_value bucket_identity_sha256)
case "$retirement_basis" in
  provider_inventory_zero)
    printf '%s\n' "$bucket_identity_sha256" | grep -Eq '^[0-9a-f]{64}$' || \
      fail "provider inventory must bind the exact bucket identity"
    ;;
  never_configured_on_hetzner)
    [ "$bucket_identity_sha256" = none ] || \
      fail "a never-configured deployment must not name a retired bucket"
    ;;
  *)
    fail "unsupported retirement basis"
    ;;
esac

verified_at_utc=$(receipt_value verified_at_utc)
printf '%s\n' "$verified_at_utc" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$' || \
  fail "verified_at_utc must use strict UTC form"

expected_evidence_sha256=$(receipt_value evidence_sha256)
printf '%s\n' "$expected_evidence_sha256" | grep -Eq '^[0-9a-f]{64}$' || \
  fail "evidence_sha256 must be a SHA-256 digest"
actual_evidence_sha256=$(sha256sum "$EVIDENCE_FILE" | awk '{print $1}')
[ "$actual_evidence_sha256" = "$expected_evidence_sha256" ] || \
  fail "evidence digest does not match"

exit 0
