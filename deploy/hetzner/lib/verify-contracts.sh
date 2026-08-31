# shellcheck shell=sh
# shellcheck disable=SC2034,SC2154
# Production verification helpers. This file is sourced by verify-production.sh.

portable_mode() {
  stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"
}

env_value() {
  sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1
}

compose() {
  docker compose --project-name subframe --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

assert_no_open_stripe_purchases_without_consumer_contract() {
  compose exec -T db sh -eu -c \
    'exec psql -X --no-password -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO $preflight$
DECLARE
    unsafe_count BIGINT;
BEGIN
    SELECT count(*)
    INTO unsafe_count
    FROM credit_purchases
    WHERE provider = 'stripe'
      AND fulfilled_at IS NULL
      AND status NOT IN ('expired', 'failed')
      AND (
          jsonb_typeof((snapshot::jsonb)->'consumer_contract')
              IS DISTINCT FROM 'object'
          OR COALESCE(
              (snapshot::jsonb)->>'consumer_contract_sha256',
              ''
          ) !~ '^[0-9a-f]{64}$'
      );

    IF unsafe_count <> 0 THEN
        RAISE EXCEPTION
            'Open Stripe purchase evidence preflight found % incompatible row(s).',
            unsafe_count;
    END IF;
END
$preflight$;
COMMIT;
SQL
}

assert_legacy_gcs_retirement_complete() {
  compose exec -T db sh -eu -c \
    'exec psql -X --no-password -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO $retirement$
DECLARE
    legacy_job_references BIGINT;
BEGIN
    IF to_regclass('public.gcs_uploads') IS NOT NULL THEN
        RAISE EXCEPTION 'Retired GCS upload-session table still exists.';
    END IF;

    SELECT count(*)
    INTO legacy_job_references
    FROM jobs
    WHERE result_data ? 'source_gcs_object';

    IF legacy_job_references <> 0 THEN
        RAISE EXCEPTION
            'Retired GCS job evidence remains in % row(s).',
            legacy_job_references;
    END IF;
END
$retirement$;
COMMIT;
SQL
}

assert_beta_login_promotion_contract() {
  compose exec -T db sh -eu -c \
    'exec psql -X --no-password -v ON_ERROR_STOP=1 --quiet --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"' <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
DO $promotion$
DECLARE
    campaign_max_claims INTEGER;
    campaign_credit_amount INTEGER;
    campaign_claimed_count INTEGER;
    unsafe_claims BIGINT;
BEGIN
    SELECT max_claims, credit_amount, claimed_count
    INTO STRICT campaign_max_claims, campaign_credit_amount, campaign_claimed_count
    FROM credit_promotion_campaigns
    WHERE id = 'beta_first_20_logins_v1';

    IF campaign_max_claims IS DISTINCT FROM 20
       OR campaign_credit_amount IS DISTINCT FROM 30
       OR campaign_claimed_count < 0
       OR campaign_claimed_count > 20 THEN
        RAISE EXCEPTION 'Beta login promotion is not the reviewed 20-by-30 contract.';
    END IF;

    SELECT count(*)
    INTO unsafe_claims
    FROM credit_promotion_claims
    WHERE campaign_id = 'beta_first_20_logins_v1'
      AND (
          credit_amount IS DISTINCT FROM 30
          OR slot_number < 1
          OR slot_number > campaign_claimed_count
          OR slot_number > 20
      );

    IF unsafe_claims <> 0 THEN
        RAISE EXCEPTION 'Beta login promotion contains % unsafe claim(s).', unsafe_claims;
    END IF;
EXCEPTION
    WHEN NO_DATA_FOUND THEN
        RAISE EXCEPTION 'Reviewed Beta login promotion campaign is missing.';
END
$promotion$;
COMMIT;
SQL
}

assert_existing_vm_local_volume() {
  volume_name=$1
  volume_driver=$(docker volume inspect --format '{{.Driver}}' "$volume_name") || {
    echo "Existing-VM storage volume is missing: $volume_name" >&2
    exit 1
  }
  if [ "$volume_driver" != local ]; then
    echo "Existing-VM storage volume must use Docker's local driver: $volume_name" >&2
    exit 1
  fi
  volume_options=$(docker volume inspect --format '{{json .Options}}' "$volume_name")
  case "$volume_options" in
    null|'{}') ;;
    *)
      echo "Existing-VM storage volume must not use external driver options: $volume_name" >&2
      exit 1
      ;;
  esac
  volume_mountpoint=$(docker volume inspect --format '{{.Mountpoint}}' "$volume_name")
  if [ ! -d "$volume_mountpoint" ] || [ -L "$volume_mountpoint" ]; then
    echo "Existing-VM storage volume mountpoint is invalid: $volume_name" >&2
    exit 1
  fi
  host_root_device=$(stat -c %d /)
  volume_device=$(stat -c %d "$volume_mountpoint")
  if [ "$volume_device" != "$host_root_device" ]; then
    echo "Existing-VM storage volume is not on the host root filesystem: $volume_name" >&2
    exit 1
  fi
}

assert_existing_vm_anchor_bind() {
  if [ ! -d "$ERASURE_ANCHOR_DIR" ] || [ -L "$ERASURE_ANCHOR_DIR" ]; then
    echo "Erasure-journal anchor source must be a real host directory." >&2
    exit 1
  fi
  canonical_anchor_dir=$(readlink -f -- "$ERASURE_ANCHOR_DIR") || {
    echo "Erasure-journal anchor source cannot be resolved." >&2
    exit 1
  }
  if [ "$canonical_anchor_dir" != "$ERASURE_ANCHOR_DIR" ]; then
    echo "Erasure-journal anchor source must not traverse a symlink." >&2
    exit 1
  fi
  if [ "$(stat -c %a "$ERASURE_ANCHOR_DIR")" != 700 ]; then
    echo "Erasure-journal anchor directory permissions are unsafe." >&2
    exit 1
  fi
  if [ "$(stat -c %u:%g "$ERASURE_ANCHOR_DIR")" != 10001:10001 ]; then
    echo "Erasure-journal anchor directory ownership is unsafe." >&2
    exit 1
  fi
  host_root_device=$(stat -c %d /)
  anchor_device=$(stat -c %d "$ERASURE_ANCHOR_DIR")
  if [ "$anchor_device" != "$host_root_device" ]; then
    echo "Erasure-journal anchor is not on the host root filesystem." >&2
    exit 1
  fi
  anchor_mount=$(docker inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/privacy-erasure-anchor"}}{{.Type}}|{{.Source}}|{{.RW}}{{end}}{{end}}' \
    "$backend_id")
  if [ "$anchor_mount" != "bind|$ERASURE_ANCHOR_DIR|true" ]; then
    echo "Backend erasure-journal anchor must use its dedicated writable host bind." >&2
    exit 1
  fi
}

receipt_value() {
  sed -n "s/^$1=//p" "$ERASURE_RECEIPT_FILE" | tail -n 1
}

timestamp_epoch() (
  raw_timestamp=$1
  if ! printf '%s\n' "$raw_timestamp" | grep -Eq '^[0-9]{8}T[0-9]{6}Z$'; then
    return 1
  fi
  iso_timestamp=$(printf '%s\n' "$raw_timestamp" | sed \
    's/^\(....\)\(..\)\(..\)T\(..\)\(..\)\(..\)Z$/\1-\2-\3T\4:\5:\6Z/')
  date -u -d "$iso_timestamp" +%s 2>/dev/null
)

verify_container_runtime_contracts() {
  compose config --quiet
  for service in db backend frontend feedback-worker app-edge edge; do
    container_id=$(compose ps -q "$service")
    if [ -z "$container_id" ]; then
      echo "Missing container for service: $service" >&2
      exit 1
    fi
    health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$container_id")
    if [ "$health" != healthy ]; then
      echo "Service $service is not healthy: $health" >&2
      exit 1
    fi
  done

  db_id=$(compose ps -q db)
  backend_id=$(compose ps -q backend)
  frontend_id=$(compose ps -q frontend)
  feedback_worker_id=$(compose ps -q feedback-worker)
  app_edge_id=$(compose ps -q app-edge)
  backend_image=$(docker inspect --format '{{.Config.Image}}' "$backend_id")
  frontend_image=$(docker inspect --format '{{.Config.Image}}' "$frontend_id")
  feedback_worker_image=$(docker inspect --format '{{.Config.Image}}' "$feedback_worker_id")
  [ "$backend_image" = "subframe-backend:$release_sha" ] || {
    echo "Backend image does not match release $release_sha." >&2
    exit 1
  }
  [ "$frontend_image" = "subframe-frontend:$release_sha" ] || {
    echo "Frontend image does not match release $release_sha." >&2
    exit 1
  }
  [ "$feedback_worker_image" = "subframe-backend:$release_sha" ] || {
    echo "Feedback worker image does not match release $release_sha." >&2
    exit 1
  }
  if ! docker exec "$feedback_worker_id" python -m backend.cli check-feedback-worker >/dev/null; then
    echo "Feedback worker configuration or durable queue is unavailable." >&2
    exit 1
  fi
  backend_networks=$(docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$backend_id")
  feedback_worker_networks=$(docker inspect --format '{{range $name, $network := .NetworkSettings.Networks}}{{println $name}}{{end}}' "$feedback_worker_id")
  if printf '%s\n' "$backend_networks" | grep -Fqx subframe-provider-egress; then
    echo "The public API must not have general provider egress." >&2
    exit 1
  fi
  for required_network in subframe-private subframe-provider-egress; do
    printf '%s\n' "$feedback_worker_networks" | grep -Fqx "$required_network" || {
      echo "Feedback worker is missing its required isolated network: $required_network" >&2
      exit 1
    }
  done

  feedback_worker_environment=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$feedback_worker_id")
  for required_secret in \
    GSP_DATABASE_URL \
    GSP_FEEDBACK_NOTIFICATION_TO \
    GSP_FEEDBACK_MAIL_FROM \
    GSP_FEEDBACK_SMTP_HOST \
    GSP_FEEDBACK_SMTP_USERNAME \
    GSP_FEEDBACK_SMTP_PASSWORD
  do
    printf '%s\n' "$feedback_worker_environment" | grep -Eq "^$required_secret=.+" || {
      echo "Feedback worker is missing required mail configuration: $required_secret" >&2
      exit 1
    }
  done
  printf '%s\n' "$feedback_worker_environment" | grep -Fqx 'GSP_FEEDBACK_RETENTION_DAYS=180' || {
    echo "Feedback worker retention must be pinned to 180 days." >&2
    exit 1
  }
  for forbidden_secret in \
    ELEVENLABS_API_KEY \
    GSP_STRIPE_RESTRICTED_KEY \
    GSP_STRIPE_WEBHOOK_SECRET \
    GOOGLE_CLIENT_SECRET \
    GOOGLE_CLIENT_ID \
    OPENAI_API_KEY \
    GROQ_API_KEY \
    POSTGRES_PASSWORD \
    GSP_FEEDBACK_HASH_SECRET \
    GSP_DOWNLOAD_GRANT_SECRET
  do
    if printf '%s\n' "$feedback_worker_environment" | grep -Eq "^$forbidden_secret="; then
      echo "Feedback worker must not receive unrelated provider credentials: $forbidden_secret" >&2
      exit 1
    fi
  done

  db_environment=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$db_id")
  if printf '%s\n' "$db_environment" | grep -Eq '^(GSP_FEEDBACK_HASH_SECRET|GSP_DOWNLOAD_GRANT_SECRET)='; then
    echo "The database container must not receive API-only signing secrets." >&2
    exit 1
  fi

  backend_nano_cpus=$(docker inspect --format '{{.HostConfig.NanoCpus}}' "$backend_id")
  [ "$backend_nano_cpus" = "3000000000" ] || {
    echo "Backend CPU budget must reserve one host core for interactive services." >&2
    exit 1
  }
  backend_memory_limit=$(docker inspect --format '{{.HostConfig.Memory}}' "$backend_id")
  [ "$backend_memory_limit" = "3221225472" ] || {
    echo "Backend memory budget must be exactly 3 GiB." >&2
    exit 1
  }
  backend_pids_limit=$(docker inspect --format '{{.HostConfig.PidsLimit}}' "$backend_id")
  [ "$backend_pids_limit" = "256" ] || {
    echo "Backend process budget must be exactly 256 PIDs." >&2
    exit 1
  }

  backend_environment=$(docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "$backend_id")
  if printf '%s\n' "$backend_environment" | grep -Eq \
    '^(GSP_GCS_[A-Z0-9_]*|GOOGLE_APPLICATION_CREDENTIALS)='; then
    echo "Backend container still exposes retired GCS settings." >&2
    exit 1
  fi
  for expected in \
    GSP_APP_ENV=production \
    APP_ENV=production \
    GSP_MOCK_EXTERNAL_SERVICES=0 \
    GSP_ELEVENLABS_ENABLED=1 \
    GSP_ELEVENLABS_API_BASE=http://app-edge:8081/elevenlabs \
    GSP_PAID_CREDITS_ENABLED=1 \
    GSP_CONSUMER_POLICY_APPROVED=1 \
    GSP_DURABLE_CONFIRMATION_CHANNEL_READY=1 \
    GSP_ADJUSTMENT_WORKFLOW_READY=1 \
    GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0 \
    GSP_STRIPE_API_BASE=http://app-edge:8081/stripe \
    GSP_BILLING_ADMIN_USER_IDS= \
    GSP_OBSERVABILITY_ENABLED=1 \
    GSP_OBSERVABILITY_RETENTION_HOURS=168 \
    GSP_OBSERVABILITY_PRESENCE_TTL_SECONDS=90 \
    "GSP_OBSERVABILITY_ADMIN_USER_IDS=$observability_admin_user_ids" \
    GSP_FEEDBACK_ENABLED=1 \
    GSP_DISABLE_RATELIMIT=0 \
    GSP_USE_MEMORY_RATELIMIT=0 \
    STRIPE_SECRET_KEY= \
    STRIPE_WEBHOOK_SECRET= \
    OPENAI_API_KEY= \
    GROQ_API_KEY= \
    GOOGLE_CLIENT_SECRET= \
    GOOGLE_REDIRECT_URI= \
    GSP_GOOGLE_OAUTH_CERTS_URL=http://app-edge:8081/oauth2/v1/certs \
    GSP_GOOGLE_AUTH_NONCE_TTL_SECONDS=600 \
    GSP_DOWNLOAD_GRANT_TTL_SECONDS=300 \
    GSP_BETA_LOGIN_PROMOTION_ENABLED=1 \
    GSP_MAX_VIDEO_DURATION_SECONDS=180 \
    GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=100 \
    GSP_EXTERNAL_PROVIDER_DAILY_BUDGET_USD=10 \
    GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0.05 \
    GSP_EXTERNAL_PROVIDER_PRICE_SAFETY_MULTIPLIER=1.25 \
    GSP_MAX_ACTIVE_MEDIA_JOBS=5 \
    GSP_MEDIA_RENDER_SLOTS=2 \
    GSP_MEDIA_RENDER_THREADS_PER_SLOT=2 \
    GSP_MEDIA_EXTRACTION_SLOTS=1 \
    GSP_MEDIA_EXTRACTION_THREADS_PER_SLOT=1 \
    GSP_PROVIDER_TRANSCRIPTION_SLOTS=8 \
    GSP_UPLOAD_INACTIVITY_TIMEOUT_SECONDS=30 \
    GSP_WORKSPACE_RETENTION_HOURS=24 \
    GSP_STALE_JOB_RETENTION_HOURS=6 \
    GSP_ORPHAN_RETENTION_HOURS=1 \
    GSP_CLEANUP_INTERVAL_MINUTES=15 \
    GSP_STORAGE_MIN_FREE_MB=2048 \
    GSP_RETENTION_CLEANUP_ENABLED=1 \
    GSP_ERASURE_JOURNAL_DIR=/privacy-erasure-journal \
    GSP_ERASURE_JOURNAL_RETENTION_DAYS=30 \
    GSP_ERASURE_JOURNAL_ANCHOR_PATH=/privacy-erasure-anchor/checkpoint.json \
    "GSP_ERASURE_JOURNAL_CONTINUITY_ID=$privacy_continuity_id"
  do
    printf '%s\n' "$backend_environment" | grep -Fqx "$expected" || {
      echo "Missing safe runtime setting: $expected" >&2
      exit 1
    }
  done
  printf '%s\n' "$backend_environment" | grep -Eq '^GSP_FEEDBACK_HASH_SECRET=.{32,}$' || {
    echo "Backend feedback pseudonym secret is missing or too short." >&2
    exit 1
  }
  printf '%s\n' "$backend_environment" | grep -Eq '^GSP_DOWNLOAD_GRANT_SECRET=.{32,}$' || {
    echo "Backend download-grant signing secret is missing or too short." >&2
    exit 1
  }
  if printf '%s\n' "$backend_environment" | grep -Eq '^GSP_FEEDBACK_(NOTIFICATION_TO|MAIL_FROM|SMTP_[A-Z0-9_]+)='; then
    echo "SMTP credentials must remain isolated from the public API container." >&2
    exit 1
  fi

}

verify_storage_and_provider_contracts() {
  assert_existing_vm_local_volume subframe-app-data
  assert_existing_vm_local_volume subframe-erasure-journal

  assert_existing_vm_anchor_bind

  journal_mount=$(docker inspect --format \
    '{{range .Mounts}}{{if eq .Destination "/privacy-erasure-journal"}}{{.Name}}|{{.RW}}{{end}}{{end}}' \
    "$backend_id")
  if [ "$journal_mount" != "subframe-erasure-journal|true" ]; then
    echo "Backend erasure journal must use its dedicated writable volume." >&2
    exit 1
  fi
  if ! docker exec "$backend_id" python -c '
  import os
  from pathlib import Path

  from backend.app.core.erasure_journal import configured_erasure_journal

  expected = os.environ["GSP_ERASURE_JOURNAL_CONTINUITY_ID"]
  marker = Path("/privacy-erasure-journal/.continuity-id")
  if marker.is_symlink() or not marker.is_file():
      raise SystemExit("Live erasure journal continuity marker is missing.")
  if marker.read_text(encoding="ascii").strip() != expected:
      raise SystemExit("Live erasure journal continuity marker does not match.")
  configured_erasure_journal().read_all()
  '; then
    echo "Erasure-journal integrity validation failed in the running backend." >&2
    exit 1
  fi
  privacy_relay_id=$(compose ps -q privacy-relay)
  if [ -n "$privacy_relay_id" ]; then
    echo "Temporary privacy relay must be stopped after erasure reconciliation." >&2
    exit 1
  fi
  backup_retention_days="${SUBFRAME_BACKUP_RETENTION_DAYS:-$(env_value SUBFRAME_BACKUP_RETENTION_DAYS)}"
  backup_retention_days="${backup_retention_days:-14}"
  case "$backup_retention_days" in
    ''|*[!0-9]*)
      echo "SUBFRAME_BACKUP_RETENTION_DAYS must be a positive integer." >&2
      exit 1
      ;;
  esac
  if [ "$backup_retention_days" -eq 0 ] || [ 30 -lt "$backup_retention_days" ]; then
    echo "Erasure journal retention must cover the complete backup retention window." >&2
    exit 1
  fi
  printf '%s\n' "$backend_environment" | grep -Fqx "GOOGLE_CLIENT_ID=$google_client_id" || {
    echo "Backend Google client ID does not match the release environment." >&2
    exit 1
  }
  if ! docker exec "$backend_id" python -c '
  from urllib.parse import urlsplit

  from backend.app.core.config import settings
  from backend.app.services.provider_clients import resolve_elevenlabs_api_key

  if not settings.allowed_origins:
      raise SystemExit("Production CORS requires an explicit origin allow-list.")
  for origin in settings.allowed_origins:
      parsed = urlsplit(origin)
      try:
          _ = parsed.port
      except ValueError as exc:
          raise SystemExit("Production CORS origins must be exact HTTPS origins.") from exc
      if (
          "*" in origin
          or parsed.scheme != "https"
          or parsed.hostname is None
          or parsed.username is not None
          or parsed.password is not None
          or parsed.path
          or parsed.query
          or parsed.fragment
          or origin != f"https://{parsed.netloc}"
      ):
          raise SystemExit("Production CORS origins must be exact HTTPS origins.")
  if not settings.paid_credit_checkout_enabled:
      raise SystemExit("Paid Checkout and every independent launch gate must be enabled.")
  if settings.stripe_automatic_tax_enabled:
      raise SystemExit("Stripe Automatic Tax must remain disabled for the reviewed tax-inclusive catalog.")
  if settings.mock_external_services:
      raise SystemExit("Production Scribe must not run in mock mode.")
  if not settings.elevenlabs_enabled:
      raise SystemExit("Production Scribe must be enabled.")
  if settings.elevenlabs_api_base != "http://app-edge:8081/elevenlabs":
      raise SystemExit("Production Scribe must use the scoped internal relay.")
  expected_budgets = (100.0, 10.0, 0.05, 1.25)
  actual_budgets = (
      settings.external_provider_monthly_budget_usd,
      settings.external_provider_daily_budget_usd,
      settings.external_provider_per_request_budget_usd,
      settings.external_provider_price_safety_multiplier,
  )
  if actual_budgets != expected_budgets:
      raise SystemExit("Production Scribe budget caps do not match the reviewed release.")
  if not resolve_elevenlabs_api_key():
      raise SystemExit("Production Scribe API key is unavailable.")
  settings.assert_paid_credits_configuration()
  settings.assert_download_grant_configuration()
  '; then
    echo "Production provider or Stripe staging configuration is incomplete or unsafe." >&2
    exit 1
  fi
  if ! docker exec "$backend_id" python -c '
  from backend.app.services.billing import BillingError, StripeSdkGateway

  try:
      StripeSdkGateway().assert_payment_intent_write_access()
  except BillingError as exc:
      raise SystemExit(str(exc)) from None
  '; then
    echo "Production Stripe Payment Intents Write access is unavailable." >&2
    exit 1
  fi
  if ! docker exec "$backend_id" alembic current --check-heads >/dev/null; then
    echo "Production database is not at the Alembic head revision." >&2
    exit 1
  fi
  if ! assert_beta_login_promotion_contract; then
    echo "Beta login promotion contract failed after database migration." >&2
    exit 1
  fi
  if ! assert_legacy_gcs_retirement_complete; then
    echo "Legacy GCS retirement invariant failed after database migration." >&2
    exit 1
  fi
  if ! assert_no_open_stripe_purchases_without_consumer_contract; then
    echo "Open Stripe purchase invariant failed after database migration." >&2
    exit 1
  fi

}
