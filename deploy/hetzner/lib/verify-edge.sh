# shellcheck shell=sh
# shellcheck disable=SC2034,SC2154
# Edge and endpoint verification phase. This file is sourced by verify-production.sh.

verify_edge_and_endpoint_contracts() {
  if [ ! -f "$ERASURE_RECEIPT_FILE" ] || [ -L "$ERASURE_RECEIPT_FILE" ]; then
    echo "A successful erasure reconciliation receipt is required." >&2
    exit 1
  fi
  receipt_line_count=$(awk 'NF { count += 1 } END { print count + 0 }' \
    "$ERASURE_RECEIPT_FILE")
  if [ "$receipt_line_count" -ne 4 ] ||
    [ "$(receipt_value reconciled)" != true ] ||
    [ "$(receipt_value release_sha)" != "$release_sha" ] ||
    [ "$(receipt_value journal_path)" != /privacy-erasure-journal ]; then
    echo "Erasure reconciliation receipt is malformed or belongs to another release." >&2
    exit 1
  fi
  reconciled_at=$(receipt_value completed_at_utc)
  if ! reconciled_epoch=$(timestamp_epoch "$reconciled_at"); then
    echo "Erasure reconciliation receipt timestamp is invalid." >&2
    exit 1
  fi
  backend_started_at=$(docker inspect --format '{{.State.StartedAt}}' "$backend_id")
  if ! backend_started_epoch=$(date -u -d "$backend_started_at" +%s 2>/dev/null); then
    echo "Could not validate backend start time for erasure reconciliation." >&2
    exit 1
  fi
  now_epoch=$(date -u +%s)
  if [ "$reconciled_epoch" -lt "$backend_started_epoch" ] ||
    [ "$reconciled_epoch" -gt "$now_epoch" ]; then
    echo "Erasure reconciliation must complete after the current backend starts and before verification." >&2
    exit 1
  fi
  edge_id=$(compose ps -q edge)
  expected_gateway_caddyfile="$ROOT_DIR/deploy/hetzner/gateway/Caddyfile"
  expected_gateway_caddyfile_sha=$(sha256sum "$expected_gateway_caddyfile" | awk 'NR == 1 { print $1 }')
  runtime_gateway_caddyfile_sha=$(docker exec "$edge_id" sha256sum /etc/caddy/Caddyfile | awk 'NR == 1 { print $1 }')
  if [ "$runtime_gateway_caddyfile_sha" != "$expected_gateway_caddyfile_sha" ]; then
    echo "Running stable gateway configuration does not match the reviewed release." >&2
    exit 1
  fi
  if ! docker exec "$edge_id" caddy validate \
    --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null; then
    echo "Running stable gateway configuration is invalid." >&2
    exit 1
  fi
  expected_caddyfile="$ROOT_DIR/deploy/hetzner/Caddyfile"
  expected_caddyfile_sha=$(sha256sum "$expected_caddyfile" | awk 'NR == 1 { print $1 }')
  runtime_caddyfile_sha=$(docker exec "$app_edge_id" sha256sum /etc/caddy/Caddyfile | awk 'NR == 1 { print $1 }')
  if [ "$runtime_caddyfile_sha" != "$expected_caddyfile_sha" ]; then
    echo "Running application edge configuration does not match the reviewed release." >&2
    exit 1
  fi
  if ! docker exec "$app_edge_id" caddy validate \
    --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null; then
    echo "Running application edge configuration is invalid." >&2
    exit 1
  fi

  gateway_networks=$(docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$edge_id")
  app_edge_networks=$(docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$app_edge_id")
  for required_gateway_network in subframe-gateway-link mizai_mizai-private; do
    printf '%s\n' "$gateway_networks" | grep -Fqx "$required_gateway_network" || {
      echo "Stable gateway is missing its required network: $required_gateway_network" >&2
      exit 1
    }
  done
  for forbidden_gateway_network in subframe-private subframe-provider-egress; do
    if printf '%s\n' "$gateway_networks" | grep -Fqx "$forbidden_gateway_network"; then
      echo "Stable gateway must not reach private application or provider networks directly." >&2
      exit 1
    fi
  done
  if printf '%s\n' "$app_edge_networks" | grep -Fqx mizai_mizai-private; then
    echo "The application edge must not join the shared public tunnel network." >&2
    exit 1
  fi
  for required_app_edge_network in subframe-private subframe-provider-egress subframe-gateway-link; do
    printf '%s\n' "$app_edge_networks" | grep -Fqx "$required_app_edge_network" || {
      echo "Application edge is missing its required isolated network: $required_app_edge_network" >&2
      exit 1
    }
  done

  if ! docker exec "$edge_id" cat /etc/caddy/Caddyfile | docker exec -i "$backend_id" python -c 'import textwrap; exec(compile(textwrap.dedent("""\
  import sys

  source = sys.stdin.read()
  required = (
      "admin 127.0.0.1:2019",
      "path /.well-known/gsubs-edge-health",
      "dynamic a",
      "name app-edge",
      "Retry-After \"5\"",
      "Κάνουμε μια σύντομη αναβάθμιση.",
  )
  if any(fragment not in source for fragment in required):
      raise SystemExit("Stable gateway maintenance contract is incomplete.")
  if "reverse_proxy backend:" in source or "reverse_proxy frontend:" in source:
      raise SystemExit("Stable gateway must remain data-blind.")
  if source.count("name app-edge") != 2:
      raise SystemExit("Stable gateway must expose only the two reviewed app-edge ports.")
  """), "<gsubs-production-verifier>", "exec"))'; then
    echo "Running stable gateway contract is unsafe." >&2
    exit 1
  fi

  # Validate the exact runtime Caddyfile without exercising an allowed provider
  # route. Previous probes reached Google, Stripe, and ElevenLabs during every
  # deploy verification. The structural check below is performed against the
  # read-only file mounted in the running edge, while the subsequent HTTP probes
  # use method/path combinations proven to terminate at the local 404 handler.
  if ! docker exec "$app_edge_id" cat /etc/caddy/Caddyfile | docker exec -i "$backend_id" python -c 'import textwrap; exec(compile(textwrap.dedent("""\
  from __future__ import annotations

  from collections import Counter
  import re
  import sys

  source = sys.stdin.read()


  def block(scope: str, header: str) -> str:
      pattern = re.compile(r"^[ \t]*" + re.escape(header) + r"[ \t]*\{[ \t]*(?:#.*)?$", re.MULTILINE)
      matches = list(pattern.finditer(scope))
      if len(matches) != 1:
          raise SystemExit(f"Expected exactly one Caddy block: {header}")
      opening = scope.find("{", matches[0].start(), matches[0].end())
      depth = 0
      for index in range(opening, len(scope)):
          if scope[index] == "{":
              depth += 1
          elif scope[index] == "}":
              depth -= 1
              if depth == 0:
                  return scope[opening + 1 : index]
      raise SystemExit(f"Unterminated Caddy block: {header}")


  def directives(scope: str) -> tuple[str, ...]:
      return tuple(
          line
          for raw_line in scope.splitlines()
          if (line := raw_line.split("#", 1)[0].strip())
      )


  public = block(source, ":8080")
  mobile_matchers = re.findall(
      r"^[ \t]*@mobile_transcription[ \t]+path[ \t]+/videos/mobile-transcriptions[ \t]*(?:#.*)?$",
      public,
      re.MULTILINE,
  )
  if len(mobile_matchers) != 1:
      raise SystemExit("Mobile transcription must have one exact path matcher.")
  mobile_handler = block(public, "handle @mobile_transcription")
  if directives(block(mobile_handler, "request_body")) != ("max_size 16MB",):
      raise SystemExit("Mobile transcription request-body cap must be exactly 16MB.")
  if mobile_handler.count("reverse_proxy backend:8080") != 1:
      raise SystemExit("Mobile transcription must have one backend upstream.")
  if public.find("@mobile_transcription path") > public.find("@backend path"):
      raise SystemExit("Mobile transcription body cap must precede the generic backend route.")
  feedback_matchers = re.findall(
      r"^[ \t]*@feedback[ \t]+path[ \t]+/feedback[ \t]*(?:#.*)?$",
      public,
      re.MULTILINE,
  )
  if len(feedback_matchers) != 1:
      raise SystemExit("Public feedback route must have one exact path matcher.")
  feedback_handler = block(public, "handle @feedback")
  if directives(block(feedback_handler, "request_body")) != ("max_size 16KB",):
      raise SystemExit("Public feedback request-body cap must be exactly 16KB.")
  if feedback_handler.count("reverse_proxy backend:8080") != 1:
      raise SystemExit("Public feedback route must have one backend upstream.")
  observability_matchers = re.findall(
      r"^[ \t]*@observability_events[ \t]+path[ \t]+/observability/events[ \t]*(?:#.*)?$",
      public,
      re.MULTILINE,
  )
  if len(observability_matchers) != 1:
      raise SystemExit("Operational telemetry must have one exact intake matcher.")
  observability_handler = block(public, "handle @observability_events")
  if directives(block(observability_handler, "request_body")) != ("max_size 4KB",):
      raise SystemExit("Operational telemetry request-body cap must be exactly 4KB.")
  if observability_handler.count("reverse_proxy backend:8080") != 1:
      raise SystemExit("Operational telemetry must have one backend upstream.")
  if public.find("@observability_events path") > public.find("@backend path"):
      raise SystemExit("Operational telemetry body cap must precede the generic backend route.")
  backend_matchers = re.findall(
      r"^[ \t]*@backend[ \t]+path[ \t]+[^\n]+$",
      public,
      re.MULTILINE,
  )
  if len(backend_matchers) != 1 or "/feedback" in backend_matchers[0]:
      raise SystemExit("Feedback must not bypass its body cap through the generic backend matcher.")

  relay = block(source, ":8081")
  expected_matchers = {
      "@stripe_checkout_create": (
          "method POST",
          "path /stripe/v1/checkout/sessions",
      ),
      "@stripe_checkout_expire": (
          "method POST",
          "path_regexp stripe_checkout_expire ^/stripe/v1/checkout/sessions/cs_(?:test|live)_[A-Za-z0-9_]+/expire$",
      ),
      "@stripe_payment_intent_retrieve": (
          "method GET",
          "path_regexp stripe_payment_intent ^/stripe/v1/payment_intents/pi_[A-Za-z0-9_]+$",
      ),
      "@stripe_payment_intent_capture": (
          "method POST",
          "path_regexp stripe_payment_intent_capture ^/stripe/v1/payment_intents/pi_[A-Za-z0-9_]+/capture$",
      ),
      "@stripe_payment_intent_cancel": (
          "method POST",
          "path_regexp stripe_payment_intent_cancel ^/stripe/v1/payment_intents/pi_[A-Za-z0-9_]+/cancel$",
      ),
      "@stripe_refund_list": (
          "method GET",
          "path /stripe/v1/refunds",
      ),
      "@google_oauth_certs": (
          "method GET",
          "path /oauth2/v1/certs",
      ),
      "@elevenlabs_scribe": (
          "method POST",
          "path /elevenlabs/v1/speech-to-text",
      ),
      "@elevenlabs_transcript_delete": (
          "method DELETE",
          "path_regexp elevenlabs_transcript_delete ^/elevenlabs/v1/speech-to-text/transcripts/[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
      ),
  }
  handler_names = re.findall(r"^[ \t]*handle[ \t]+(@[A-Za-z0-9_]+)[ \t]*\{", relay, re.MULTILINE)
  if tuple(handler_names) != tuple(expected_matchers):
      raise SystemExit("Provider relay handler allow-list does not match the reviewed release.")

  for matcher, expected_directives in expected_matchers.items():
      if directives(block(relay, matcher)) != expected_directives:
          raise SystemExit(f"Provider relay matcher changed: {matcher}")
      handler = block(relay, f"handle {matcher}")
      if handler.count("reverse_proxy ") != 1:
          raise SystemExit(f"Provider relay must have one upstream: {matcher}")
      if matcher.startswith("@stripe_"):
          required = (
              "uri strip_prefix /stripe",
              "reverse_proxy https://api.stripe.com",
              "header_up Host api.stripe.com",
          )
      elif matcher == "@google_oauth_certs":
          required = (
              "reverse_proxy https://www.googleapis.com",
              "header_up Host www.googleapis.com",
          )
      else:
          required = (
              "uri strip_prefix /elevenlabs",
              "reverse_proxy https://api.elevenlabs.io",
              "header_up Host api.elevenlabs.io",
          )
      if any(fragment not in handler for fragment in required):
          raise SystemExit(f"Provider relay handler changed: {matcher}")

  expected_upstreams = Counter(
      {
          "https://api.stripe.com": 6,
          "https://www.googleapis.com": 1,
          "https://api.elevenlabs.io": 2,
      },
  )
  actual_upstreams = Counter(
      re.findall(r"^[ \t]*reverse_proxy[ \t]+(https://[^ \t{]+)", relay, re.MULTILINE),
  )
  if actual_upstreams != expected_upstreams:
      raise SystemExit("Provider relay upstream allow-list does not match the reviewed release.")
  default_deny_offset = relay.rfind("respond 404")
  last_handler_offset = max(relay.rfind(f"handle {matcher} {{") for matcher in expected_matchers)
  if directives(relay).count("respond 404") != 1 or default_deny_offset < last_handler_offset:
      raise SystemExit("Provider relay must end in one default-deny response.")
  if any(secret in relay for secret in ("ELEVENLABS_API_KEY", "STRIPE_RESTRICTED_KEY", "GOOGLE_CLIENT_SECRET")):
      raise SystemExit("Provider credentials must not be embedded in the edge relay.")
  """), "<gsubs-production-verifier>", "exec"))'; then
    echo "Running provider relay contract is unsafe." >&2
    exit 1
  fi

  relay_deny_http=$(docker exec "$backend_id" python -c 'import textwrap; exec(compile(textwrap.dedent("""\
  import urllib.error
  import urllib.request

  base = "http://app-edge:8081"
  probes = (
      (f"{base}/oauth2/v1/certs", "POST"),
      (f"{base}/oauth2/v1/certs/verification-deny", "GET"),
      (f"{base}/stripe/v1/checkout/sessions", "GET"),
      (f"{base}/stripe/v1/payment_intents/not-a-provider-id", "GET"),
      (f"{base}/elevenlabs/v1/speech-to-text", "GET"),
      (f"{base}/elevenlabs/v1/models", "POST"),
      (f"{base}/elevenlabs/v1/speech-to-text/transcripts/invalid/path", "DELETE"),
  )
  statuses = []
  for url, method in probes:
      request = urllib.request.Request(
          url,
          data=(b"" if method == "POST" else None),
          method=method,
      )
      try:
          response = urllib.request.urlopen(request, timeout=10)
      except urllib.error.HTTPError as exc:
          statuses.append(str(exc.code))
      except urllib.error.URLError:
          statuses.append("unavailable")
      else:
          statuses.append(str(response.status))
  print(",".join(statuses))
  """), "<gsubs-production-verifier>", "exec"))')
  [ "$relay_deny_http" = "404,404,404,404,404,404,404" ] || {
    echo "Provider relay local default-deny checks failed: $relay_deny_http" >&2
    exit 1
  }

  health_json=""
  catalog_json=""
  feedback_canary_json=""
  if command -v curl >/dev/null 2>&1; then
    health_json=$(curl -fsS "http://127.0.0.1:$preview_port/health")
    catalog_json=$(curl -fsS "http://127.0.0.1:$preview_port/billing/catalog")
    feedback_canary_json=$(curl -fsS \
      -H 'Content-Type: application/json' \
      --data '{"category":"chat","message":"deployment honeypot canary","source_path":"/","page_title":"GSUBS","form_started_at":1,"website":"deployment-canary"}' \
      "http://127.0.0.1:$preview_port/feedback")
    curl -fsS "http://127.0.0.1:$preview_port/" >/dev/null
  elif command -v wget >/dev/null 2>&1; then
    health_json=$(wget -qO- "http://127.0.0.1:$preview_port/health")
    catalog_json=$(wget -qO- "http://127.0.0.1:$preview_port/billing/catalog")
    feedback_canary_json=$(wget -qO- \
      --header='Content-Type: application/json' \
      --post-data='{"category":"chat","message":"deployment honeypot canary","source_path":"/","page_title":"GSUBS","form_started_at":1,"website":"deployment-canary"}' \
      "http://127.0.0.1:$preview_port/feedback")
    wget -qO- "http://127.0.0.1:$preview_port/" >/dev/null
  else
    echo "curl or wget is required for loopback verification." >&2
    exit 1
  fi
  printf '%s' "$health_json" | docker exec -i "$backend_id" python -c 'import textwrap; exec(compile(textwrap.dedent("""\
  import json
  import sys

  health = json.load(sys.stdin)
  if health.get("status") != "ok":
      raise SystemExit("Production health endpoint must report status=ok")
  if health.get("app_env") != "production":
      raise SystemExit("Production health endpoint must report app_env=production")
  """), "<gsubs-production-verifier>", "exec"))'
  printf '%s' "$catalog_json" | docker exec -i "$backend_id" python -c 'import textwrap; exec(compile(textwrap.dedent("""\
  import json
  import sys

  catalog = json.load(sys.stdin)
  if catalog.get("checkout_enabled") is not True:
      raise SystemExit("Production billing catalog must report checkout_enabled=true")
  if catalog.get("consumer_contract_status") != "approved":
      raise SystemExit("Production billing catalog must expose the approved consumer contract")
  if not isinstance(catalog.get("consumer_contract"), dict):
      raise SystemExit("Production billing catalog must publish the approved consumer contract")
  """), "<gsubs-production-verifier>", "exec"))'
  printf '%s' "$feedback_canary_json" | docker exec -i "$backend_id" python -c 'import textwrap; exec(compile(textwrap.dedent("""\
  import json
  import sys

  payload = json.load(sys.stdin)
  if payload != {"status": "received", "id": None}:
      raise SystemExit("Production feedback honeypot canary must succeed without persistence")
  """), "<gsubs-production-verifier>", "exec"))'

  if [ "$candidate_mode" -eq 0 ]; then
    if [ ! -f "$STATE_FILE" ] || [ -L "$STATE_FILE" ] ||
      [ "$(cat "$STATE_FILE")" != "$release_sha" ]; then
      echo "Recorded release does not match $release_sha." >&2
      exit 1
    fi
  fi

  if [ "$candidate_mode" -eq 1 ]; then
    printf 'Verified gsubs candidate release %s on loopback port %s.\n' \
      "$release_sha" \
      "$preview_port"
  else
    printf 'Verified gsubs release %s on loopback port %s.\n' \
      "$release_sha" \
      "$preview_port"
  fi
}
