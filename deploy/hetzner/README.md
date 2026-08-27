# Hetzner production lane

`https://gsubs.gr` runs as an independent Docker Compose project on the MizAI
Hetzner VM. It shares only the existing edge network so the public reverse proxy
can reach the `subframe-edge` alias. PostgreSQL, media data, logs, images and
the private network remain separate from MizAI and the other projects on the
host.

The `SUBFRAME_*`, `subframe-*`, and `/home/mizai/subframe` identifiers below are
stable internal deployment contracts. The public product name is gsubs; these
legacy infrastructure identifiers stay unchanged to preserve compatibility.

## Safe release contract

### Five-user media capacity

The existing four-core VM admits at most five active upload/reprocess jobs
across all accounts. Admission is a short cross-process transaction: the
capacity check, provisional credit charge and durable job creation complete
before request streaming starts, so five slow uploads can progress together
without holding a global request lock. In-flight uploads publish a private
size reservation and every storage preflight includes those reservations plus
the fixed 2 GiB free-space floor. If the requested files do not fit safely,
the next request receives `507` before its body is consumed; capacity never
means overcommitting the root disk.

Video exports acquire their bounded render lane before publishing a projected
output-size reservation. The short admission lock makes those reservations and
their disk preflight atomic across both render lanes. A queued export therefore
rechecks current free space only when it can actually render, while a second
active renderer sees the first renderer's reservation. Abandoned reservation
metadata is ignored and cleared once its render-slot lock is no longer held.

CPU-heavy stages are deliberately queued inside that five-job envelope:

- one single-thread audio-extraction lane;
- eight weighted ElevenLabs Scribe slots (a ten-minute Scribe v2 request uses
  two, matching the provider's
  [documented concurrency accounting](https://elevenlabs.io/docs/help-center/product/core-capabilities/speech-to-text/how-many-speech-to-text-requests-can-i-make-and-can-i-increase-it));
- two normal render/export lanes, each capped at two FFmpeg worker threads; and
- one 4K render reserves both lanes and uses at most two encoder threads.

The backend container is capped at 3 CPUs, 3 GiB RAM and 256 PIDs. FFmpeg
children run at reduced priority, so interactive API work preempts encoders
inside that cgroup while one host core remains outside the backend budget for
the database and co-located MizAI services. Five accepted jobs can therefore
upload and wait/process concurrently, but this contract intentionally does not
promise five simultaneous encoders. The production verifier enforces all
admission, lane, thread and container limits against the running container.

The tracked production Compose file enables only ElevenLabs Scribe v2 for
caption transcription. The API key stays in the untracked, mode-0600
`.env.production` file and the internal-only backend can reach exactly
`POST /v1/speech-to-text` through a method/path-scoped edge relay. Production
hard-caps provider reservations at $100/month, $10/day and $0.05/request with
the 1.25 safety multiplier. The global limits are emergency circuit breakers,
not ordinary customer quotas: every external request must first reserve
already-purchased credits and pass the independent 3x contribution-margin
guard. At the current official Scribe v2 price of $0.22/hour, the tracked
limits support more than 200 guarded ten-minute jobs per day and 2,000 per
month while keeping one compromised request below five cents. Missing
credentials, a closed budget, an unsupported tier/provider pair or a provider
error fails closed before work is accepted or refunds the idempotent
reservation.

The backend copies each Scribe result locally, requires its provider
`transcription_id`, then calls ElevenLabs' narrowly relayed transcript-deletion
endpoint. A missing ID or failed deletion fails closed and is retained for
idempotent retry; the edge exposes only `POST /v1/speech-to-text` and
`DELETE /v1/speech-to-text/transcripts/<validated-id>`, never a general
ElevenLabs proxy. This minimizes provider copies but does not turn on Zero
Retention Mode or EU residency. ElevenLabs documents those as Enterprise
features and states that ordinary deleted records can remain in its backups for
up to 30 days. See the official
[transcript deletion API](https://elevenlabs.io/docs/api-reference/speech-to-text/delete),
[Zero Retention documentation](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode),
[data-residency documentation](https://elevenlabs.io/docs/overview/administration/data-residency),
and [Data Processing Addendum](https://elevenlabs.io/dpa).

Paid Checkout is enabled by the tracked release contract:
`GSP_PAID_CREDITS_ENABLED=1`, with the consumer-policy,
durable-confirmation-channel and manual-adjustment gates also fixed to `1`.
Stripe Automatic Tax remains fixed to `0` for the reviewed tax-inclusive
Greek B2C catalog. The Compose file forces the billing-admin allowlist to an
empty value. New accounts receive no automatic credits, and external provider
spend requires an existing paid-credit balance.

The Compose contract requires one complete live Stripe bundle (restricted key,
webhook signing secret and all three Price IDs) from the untracked production
environment. Partial bundles fail startup and the production verifier. Stripe
API traffic leaves the internal-only backend only through an edge relay limited
to Checkout Session creation/expiry, PaymentIntent
retrieval/capture/cancellation and Refund listing. Values placed only in
`.env.production` cannot bypass the tracked Automatic Tax, legal publication,
or approval contract.

Source videos and generated media live only in the dedicated local
`subframe-app-data` Docker volume. Browser uploads go through the authenticated
backend stream endpoint; there is no cloud-object-storage path or credential.
`subframe-app-data` and `subframe-erasure-journal` are ordinary Docker `local`
volumes on the existing VM root filesystem. The journal's rollback-detection
anchor is a host bind at
`/home/mizai/subframe/.runtime/privacy-erasure-anchor`, on that same existing
root filesystem. This release does not create or request a Hetzner Block
Volume, Storage Box, Object Storage bucket, NFS mount or any other separately
billed storage product, and neither release script calls the Hetzner API.
`verify-production.sh` enforces the local driver, empty driver options and root
filesystem device for both named volumes, then enforces the anchor's exact
writable bind, real-directory type, mode `0700`, owner `10001:10001` and root
filesystem device.
Before the first release on an upgraded host, remove every `GSP_GCS_*` and
`GOOGLE_APPLICATION_CREDENTIALS` assignment from `.env.production`, delete any
obsolete credential file, and revoke the retired cloud service-account access
at its issuer. Deployment and production verification fail if a retired key is
still injected into the application container.

### One-time retired GCS evidence

The schema-removal release will not discard the old object-name columns on an
operator assertion alone. Before migration, `deploy-production.sh` verifies
that the legacy upload table has zero rows and that no job contains a
`source_gcs_object` reference. It also requires the private, mode-`0600` files
`.runtime/gcs-retirement-evidence` and
`.runtime/gcs-retirement-receipt`; the receipt is bound to the evidence file by
SHA-256 and to the exact pre-removal release
`d0d47ac774995d7eb06f1942c7e5eeacff69b1e1`.

For this Hetzner lane, `never_configured_on_hetzner` is valid only when the
evidence records all of the following without recording secret values:

- every tracked Hetzner backend image from its first release through the
  pre-removal release was built from `backend/requirements.mock.txt`, which did
  not contain `google-cloud-storage`, so the optional client could neither
  issue a signed upload URL nor write an object;
- all retired GCS and Google credential keys are absent from the live untracked
  environment and the running container; and
- the read-only live database checks report zero upload rows and zero job
  object references.

That proof uses only Git, environment-key presence checks and read-only SQL; it
does not contact Google and creates no provider request or charge. In this
basis, `credentials_revoked=true` means that no GCS credential exists in the
Hetzner deployment and no obsolete credential file remains. If any historical
deployment could actually reach a bucket, do not use this basis: preserve the
database mappings and use `provider_inventory_zero` only after an authenticated
inventory proves the exact bucket and every retired prefix empty and the
credential has been revoked.

The receipt contains exactly these nine fields:

```text
retired=true
scope=hetzner-production-whole-storage
retirement_basis=never_configured_on_hetzner
retirement_base_sha=d0d47ac774995d7eb06f1942c7e5eeacff69b1e1
objects_after=0
credentials_revoked=true
bucket_identity_sha256=none
evidence_sha256=<sha256-of-gcs-retirement-evidence>
verified_at_utc=<YYYYMMDDTHHMMSSZ>
```

`verify-gcs-retirement.sh` rejects missing, symlinked, non-private, malformed or
evidence-mismatched files. Keep both files as retirement audit evidence; they
contain no media, account data, credential value or bucket name.

Individual, batch and account deletion remove the exact local workspace, while
the retention worker removes terminal workspaces after 24 hours, stale active
jobs after 6 hours and orphaned files after 1 hour. Production must keep
`GSP_RETENTION_CLEANUP_ENABLED=1`; a restore must stay unavailable to users
until retention and post-backup erasure reconciliation have both completed.

Deletion tombstones are pseudonymous and live in the separate named volume
`subframe-erasure-journal`, mounted only by the backend at
`/privacy-erasure-journal`. Its 30-day retention covers the 14-day backup
window plus safety margin. Neither `postgres.dump.age` nor `app-data.tgz.age`
contains this journal, and a database/app-data restore must never replace it.
The app-data archive does include the hidden `.workspace-ownership` registry:
`backup.sh` archives `.` from the volume root, so dot-directories are retained.
These fsynced markers associate media created before its database row with the
owning account and must be restored with the corresponding app-data archive.
The deploy script binds that live volume to the host through a generated
continuity identifier stored in `.runtime/privacy-continuity-id`; the backend
also writes a monotonic integrity checkpoint to
`.runtime/privacy-erasure-anchor/checkpoint.json`, mounted at
`/privacy-erasure-anchor/checkpoint.json`. The checkpoint is isolated from the
journal named volume so restoring or rolling that volume back cannot silently
erase newer tombstones. The deploy and production-verification paths fail
closed when the continuity state, journal, checkpoint or external anchor is
missing, mismatched, truncated or rolled back. This is a fail-closed privacy
control, not an independent disaster backup of the journal: both stores remain
on the already-paid VM root disk.
After total host or journal-volume loss, the supported no-extra-storage policy
is to lose the recovery copy: do not restore or publish an older user database
or media archive. Start an empty service instead. Supporting user-data disaster
recovery in that scenario would require a continuously updated encrypted copy
of the journal in an independent failure domain.
While the public edge is stopped, provider-deletion tombstones are replayed
through the temporary `privacy-relay` service. That service has no host port,
joins only the private application network and a dedicated outbound-only
network, and proxies only a validated ElevenLabs transcript DELETE. It is
stopped before any public cutover; production verification fails if it remains
running.

The billing-aware release applies and verifies every database migration before
the candidate can become active. The manual AADE/MARK record endpoint remains
disabled because the immutable billing-admin allowlist is empty; enabling that
separate administrative capability still requires a reviewed change and
explicit operator authorization. Deployment and Checkout activation do not
authorize a real test charge or any AADE action.

## Release procedure

Run the complete repository gates and the production frontend build from a
clean checkout:

```bash
make ci
(cd frontend && npm run build)
git status --short
```

The deploy script refuses tracked or non-ignored untracked worktree changes so
the Docker image contents cannot differ from their release SHA.

Before every release:

1. Back up MizAI and copy the encrypted backup off-server.
2. If gsubs contains user data, create and verify the encrypted gsubs backup
   using the procedure below.
3. Set `SUBFRAME_RELEASE_SHA` to the exact clean, reviewed commit being
   deployed.

The one-time release that introduces journal continuity beside existing
production data is deliberately a two-stage operation. The first invocation of
`deploy-production.sh` stops the existing public edge and legacy backend
immediately, fingerprints both stopped Docker states, and atomically writes the private mode-`0600`
`.runtime/legacy-journal-bootstrap-transition` marker on the existing server
root disk. It then exits without building, migrating, or opening any service.
Do not restart or replace the edge or backend after this marker exists. Keeping
the legacy backend stopped is essential because its retention worker predates
the durable erasure journal and could otherwise delete state after the backup.

Only after that first invocation may the operator create the fresh encrypted
backup, copy it off-server, and run `verify-backup.sh --drill` for the exact
target SHA. The second invocation validates the marker, proves that the same
edge and backend have remained stopped, and requires the backup creation timestamp to be
strictly later than the marker timestamp. A missing or modified marker, a
restarted/replaced edge or backend, or a pre-marker backup fails closed and requires the
transition to be investigated and restaged with a new backup. This prevents an
account/project deletion from falling between the accepted backup and creation
of the first durable journal. Only that independently gated first-use path may
create the mode-`0700`, UID/GID-`10001` anchor directory and call the journal's
explicit initializer. Later releases require the existing continuity state,
journal marker and external anchor; they run a complete fail-closed journal
read before starting the application or reopening the public edge, and none of
those files is silently recreated.

### Backup verification and restore drill

`backup.sh` prints the backup directory on standard output and the SHA-256 of
its `SHA256SUMS` file on standard error. The backup is not release-ready merely
because both encrypted files exist.

The default backup root is the dedicated
`/home/mizai/subframe/backups/production` directory. An explicit
`SUBFRAME_BACKUP_ROOT` override must be a non-empty, canonical absolute child
of an existing real parent directory. Filesystem root, repository root,
operator home, relative paths, symlinks and paths with dot components are
rejected before any backup command runs. Retention never recursively removes
the configured root: it prunes only direct timestamped children containing
exactly the four expected regular backup files and a matching manifest, using
exact file removal followed by `rmdir`. Any other directory is preserved. The
default retention is 14 days and the checksum-protected manifest records the
configured value. `verify-backup.sh` rejects a backup older than that value.

```bash
backup_dir=$(
  SUBFRAME_ENV_FILE=/home/mizai/subframe/.env.production \
    ./deploy/hetzner/backup.sh
)
server_sums_sha=$(sha256sum "$backup_dir/SHA256SUMS" | awk '{print $1}')
printf 'server SHA256SUMS SHA-256: %s\n' "$server_sums_sha"
```

Copy that complete timestamped directory to independent recovery storage, then
mount that storage read-only on the verifier host. Preserve the exact
timestamped directory name and all four files. The server directory and mounted
copy must be canonical absolute paths on different Linux filesystem devices;
two paths into the same filesystem do not count as an independent copy.

The server backup command prunes its own root. The independent storage operator
must run the same reviewed exact-target pruner on its writable backup root at
least daily, then mount the selected copy read-only for verification. Both
locations must use the same configured retention:

```bash
SUBFRAME_BACKUP_RETENTION_DAYS=14 \
  ./deploy/hetzner/prune-backups.sh \
  /srv/independent-subframe-backups/production
```

Do not exempt individual backups from this lifecycle. Media or account data
erased from the live service may remain only inside an already-created
encrypted backup and only until that backup's configured expiry.

Validate the mounted copy independently before starting the drill:

```bash
independent_backup_dir=/mnt/subframe-recovery/20260726T120000Z
findmnt --target "$independent_backup_dir" \
  --noheadings --output TARGET,SOURCE,FSTYPE,OPTIONS
cd "$independent_backup_dir"
sha256sum --check SHA256SUMS
```

The reported options must contain the standalone `ro` mount option. The
verifier repeats this check with Linux util-linux `findmnt`; a writable, absent
or ambiguous mount fails closed. A read-only file or directory permission is
not equivalent to a read-only mount and does not satisfy this gate.

The verifier then reads both directories itself: a scalar checksum copied into
an environment variable is not accepted as evidence of an independent backup.
It also inspects every timestamp-named sibling in the mounted independent
backup root and fails if any is older than the configured retention window;
run the exact-target pruner on the writable storage before remounting it
read-only for verification.
Make the age identity available from separate secure custody only for this
operation; do not put the identity or its contents in `.env.production`, shell
history, source control, or either backup directory.

```bash
SUBFRAME_ENV_FILE=/home/mizai/subframe/.env.production \
SUBFRAME_BACKUP_AGE_IDENTITY_FILE=/secure/mounted/age-identity.txt \
  ./deploy/hetzner/verify-backup.sh --drill \
    "$backup_dir" \
    "$independent_backup_dir"
```

The verifier fails closed unless all of these checks succeed:

1. Each directory contains exactly the same four regular, non-symlink files,
   and each encrypted archive and manifest matches its fixed entry in
   `SHA256SUMS`.
2. The paths differ, Linux `stat` reports different filesystem devices,
   `findmnt` resolves the independent directory to a mount whose options
   contain `ro` and not `rw`, and every one of the four files matches across
   copies.
3. The checksum-protected manifest has the exact release, timestamp, encryption,
   retention and database/app-data size fields required by the restore gates;
   an expired backup is rejected.
4. `age` authenticates and decrypts both ciphertexts; `pg_restore --list`
   accepts the PostgreSQL custom archive and `tar -tzf` accepts the app-data
   archive.
5. Before creating a restore resource, available space on Docker's filesystem
   is at least twice that resource's manifest size plus a fixed 10 GiB reserve.
6. The database restores into only
   `subframe_restore_drill_<backup-id>` and app data restores into only
   `subframe-restore-drill-<backup-id>-app-data`.
7. The restored database answers a query, is dropped successfully, and only
   then may the app-data volume be created and restored.
8. Both disposable resources and the verifier working directory are removed
   successfully.

The drill refuses to touch either exact name if it already exists, and it never
uses a database, volume or filesystem-wide prune. Decryption streams directly
to each validator or restore consumer, so there is no decrypted archive on
disk. Database restore, validation and removal complete before app-data
capacity is checked or its volume exists; the two restore footprints therefore
cannot accumulate. It writes
`.runtime/last-backup-restore-drill` only after successful restore and cleanup,
binding the receipt to the checked-out `SUBFRAME_RELEASE_SHA`. Starting a new
drill invalidates any older receipt first, so a failed attempt cannot leave a
stale green gate behind. The receipt records both numeric filesystem device
identifiers plus
`independent_backup_copy_distinct_filesystem=true`,
`independent_backup_copy_mount_detected=true`, and
`independent_backup_copy_mount_read_only=true`.

The PostgreSQL dump is the authoritative schema rollback evidence. `pg_dump`
provides its own consistent database snapshot. The `subframe-app-data` archive
is only a best-effort recovery convenience for the product's ephemeral,
24-hour workspace media; it is non-authoritative and is not transactionally
quiesced with the database dump. Never use that media archive as billing,
invoice or payment evidence.

### Production restore privacy gate

A real restore is an offline operation. It is supported only on the same live
host while both `.runtime/privacy-continuity-id` and the matching
`subframe-erasure-journal/.continuity-id` still exist and
`.runtime/privacy-erasure-anchor/checkpoint.json` matches the live journal.
Stop the public edge before replacing the PostgreSQL or `subframe-app-data`
state and leave both the journal volume and anchor directory untouched. If any
continuity or integrity side is missing, do not restore user data and do not
reopen the edge. After the restored backend is healthy, run both the configured
local retention pass and the idempotent erasure replay:

```bash
docker compose --project-name subframe \
  --env-file /home/mizai/subframe/.env.production \
  -f deploy/hetzner/docker-compose.production.yml \
  --profile privacy-maintenance up -d privacy-relay
docker compose --project-name subframe \
  --env-file /home/mizai/subframe/.env.production \
  -f deploy/hetzner/docker-compose.production.yml \
  --profile privacy-maintenance exec -T \
  -e GSP_ELEVENLABS_API_BASE=http://privacy-relay:8082/elevenlabs \
  backend python -m backend.cli run-retention
docker compose --project-name subframe \
  --env-file /home/mizai/subframe/.env.production \
  -f deploy/hetzner/docker-compose.production.yml \
  --profile privacy-maintenance exec -T \
  -e GSP_ELEVENLABS_API_BASE=http://privacy-relay:8082/elevenlabs \
  backend python -m backend.cli reconcile-erasures
docker compose --project-name subframe \
  --env-file /home/mizai/subframe/.env.production \
  -f deploy/hetzner/docker-compose.production.yml \
  --profile privacy-maintenance stop privacy-relay
```

The normal `deploy-production.sh` path does this automatically: it stops the
edge, invalidates `.runtime/last-erasure-reconciliation`, starts only the core
services, replays and prunes the journal, writes a new receipt atomically, and
only then recreates the edge. Provider replay uses the private temporary relay
while the public edge remains stopped, and the relay is torn down before the
receipt and cutover. `verify-production.sh` rejects a running privacy relay or a missing,
malformed, release-mismatched or stale receipt, including one written before
the current backend container started. Never reopen public traffic manually if
the replay exits nonzero or the journal is malformed. When the live continuity
checks above pass, this replay prevents a backup from resurrecting projects or
accounts erased after that backup was created.

A schema-changing release is any release that changes
`backend/alembic/versions`, plus a first release for which no valid prior
release SHA is recorded. `deploy-production.sh` refuses such a release unless
the backup and successful `last-backup-restore-drill` receipt both identify the
same exact target release SHA. The receipt timestamps must use strict
`YYYYMMDDTHHMMSSZ` UTC form, neither timestamp may be in the future, backup
creation must precede verification, and both timestamps must be no more than
24 hours old when deployment starts. A stale, malformed, misordered or
release-mismatched receipt requires a fresh backup and successful restore drill.
Do not bypass this gate: keep the failed release stopped, preserve the backup,
and investigate or prepare a new roll-forward release.

```bash
cp deploy/hetzner/subframe.env.example .env.production
# Fill the random database password, exact SHA, Google client ID, ElevenLabs
# production key and age public recipient. Never commit this file. Create the
# API pseudonym key and SMTP worker bundles separately; both must be absolute,
# canonical, non-symlink paths with mode 0600.
install -d -m 700 .runtime
cp deploy/hetzner/feedback-api.env.example .runtime/feedback-api.env
cp deploy/hetzner/feedback-worker.env.example .runtime/feedback-worker.env
chmod 600 .runtime/feedback-api.env .runtime/feedback-worker.env
# Put only a random stable HMAC key in feedback-api.env. Fill the exact app DB
# URL, recipient, sender and STARTTLS SMTP credentials in feedback-worker.env.
# Point SUBFRAME_FEEDBACK_API_ENV_FILE and SUBFRAME_FEEDBACK_WORKER_ENV_FILE in
# .env.production at these absolute paths.
SUBFRAME_ENV_FILE=/home/mizai/subframe/.env.production \
  ./deploy/hetzner/deploy-production.sh
SUBFRAME_ENV_FILE=/home/mizai/subframe/.env.production \
  ./deploy/hetzner/verify-production.sh
```

The edge service binds to `127.0.0.1:18090` by default. Public HTTPS reaches it
through the existing reverse proxy and the `subframe-edge` Docker-network
alias; the backend, frontend and database do not publish host ports. An
operator can also inspect the loopback surface through an SSH local-forward:

```bash
ssh -N -L 127.0.0.1:18090:127.0.0.1:18090 root@SERVER
```

`verify-production.sh` checks container health and image SHAs, every reviewed
payment/provider setting, the non-empty Scribe credential without printing it,
the complete live Stripe bundle, and the method/path-scoped Google, Stripe and
ElevenLabs relays. It also requires separate private 0600 API and worker
bundles, verifies that the pseudonym key reaches only the public API, and that
SMTP/provider credentials remain out of the API, database and worker where
they are not needed. The verifier pins the database-backed rate limiter,
180-day feedback retention, the public 16KB request-body cap, and confirms the
durable queue without sending a message. Relay verification compares and
validates the exact runtime Caddyfile, checks its structural allow-list and
exercises only local default-deny routes; it never sends a verification request to a third-party
provider. The verifier also checks the local-volume and
anchor-bind storage contract, a complete authenticated read of the erasure
journal, the Alembic head, and that
`/billing/catalog` returns `checkout_enabled=true` with the approved contract.
`deploy-production.sh` runs that complete verifier in candidate mode before it
atomically replaces `.runtime/last-successful-release`. A candidate-verification
failure leaves the previously recorded SHA unchanged and follows the documented
failure/rollback policy.

The verifier also probes `https://gsubs.gr/health` with HTTP/2 and rejects any
`Alt-Svc` advertisement for HTTP/3. `deploy-production.sh` runs the same probe
before it changes an existing production release, and the nightly workflow
repeats it daily. This is a deliberate quarantine of the shared public edge's
QUIC path after the 2026-08-25 incident: keep the outer HTTPS listener on
`protocols h1 h2` until a full authenticated browser download proves HTTP/3 is
both correct and at least 2 MiB/s. A loopback probe or a small initial range is
not sufficient evidence to lift the quarantine.

## Failure and rollback policy

The backend applies `alembic upgrade head` before starting. For that reason the
default recovery policy is roll-forward: an older image may not recognize a
database revision introduced by the failed release.

Automatic rollback is disabled unless the operator sets
`SUBFRAME_ALLOW_SCHEMA_COMPATIBLE_ROLLBACK=1`. Use that opt-in only after
proving that the previous image recognizes the database's current Alembic
revision, the live erasure-journal entry formats, and that both schemas are
code-compatible. A successful Alembic downgrade alone is insufficient when a
newer backend may already have written a journal event the previous image
cannot decode. A backup is mandatory but does not by itself prove rollback
compatibility. Even with that opt-in, a failed candidate restores only the
previous core containers: it invalidates the erasure receipt and leaves the
public edge stopped. Do not expose the rollback directly. Complete retention
and durable erasure reconciliation, then ship a verified roll-forward release
through the normal privacy gate.

The deploy script does not prune the shared Docker build cache by default,
because the VM also hosts MizAI and other projects. Set
`SUBFRAME_PRUNE_BUILD_CACHE=1` only during an explicit disk-recovery operation.

The frontend uses a same-origin API URL, so changing the domain does not require
a separate frontend code change.

After the script-level verification, confirm the public `https://gsubs.gr` UI,
`/health`, paid-credit catalog, terms/privacy pages and upload-to-login gate in a
real browser. Test a Checkout redirect only with explicit operator authorization:
the redirect itself does not complete a charge, but its `POST /billing/checkout`
creates a real purchase record and a live Stripe Checkout Session, so it is not a
routine read-only smoke check.
