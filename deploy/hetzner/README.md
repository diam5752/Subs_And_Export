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

The tracked production Compose file deliberately forces mock providers, zero
provider budgets, `GSP_PAID_CREDITS_ENABLED=0`, and
`GSP_STRIPE_AUTOMATIC_TAX_ENABLED=0`. It separately forces the consumer-policy,
durable-confirmation-channel and adjustment-workflow approvals to `0`, so an
environment-file change cannot approve an unfinished legal or operational
workflow. It also forces `GSP_GCS_BUCKET=""` and the billing-admin allowlist
to an empty value.

The Compose contract can stage one complete live Stripe bundle (restricted
key, webhook signing secret and all three Price IDs) from the untracked
production environment while sales remain disabled. Partial bundles fail the
production verifier. Stripe API traffic leaves the internal-only backend only
through an edge relay limited to Checkout Session creation/expiry,
PaymentIntent retrieval/capture/cancellation and Refund listing. Values placed only in
`.env.production` still cannot bypass the tracked Checkout, Automatic Tax or
approval overrides.

GCS activation has a separate privacy blocker: individual and batch terminal
project deletion must first delete every exact static artifact object before
the job's persisted `result_data` is removed. Account deletion already erases
its exact known GCS objects, but that does not close the per-project deletion
gap. Keep `GSP_GCS_BUCKET` empty until this behavior and its cross-user
isolation tests are implemented and reviewed.

The billing-aware release must apply and verify its database migrations while
paid Checkout remains unavailable. Enabling live sales later requires a
separate reviewed commit that changes both the tracked Checkout/approval
overrides and the matching fail-closed assertions in `verify-production.sh`.
Enabling the manual AADE/MARK record endpoint likewise requires a reviewed
change to both files after the accountant workflow is confirmed. Both actions
require explicit operator authorization; staging a complete Stripe bundle does
not authorize a charge or an admin allowlist.

## Release procedure

Run the complete repository gates and the production frontend build from a
clean checkout:

```bash
make check-all
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
exact file removal followed by `rmdir`. Any other directory is preserved.

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
3. The checksum-protected manifest has the exact release, timestamp, encryption
   and database/app-data size fields required by the restore-capacity gate.
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
# Fill the random database password, exact SHA, Google client ID and age public
# recipient. Never commit this file.
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

`verify-production.sh` checks container health and image SHAs, every fail-closed
payment/provider setting, the complete-or-absent Stripe staging bundle, the
method/path-scoped Stripe relay, the Google certificate relay, the Alembic head,
and that `/billing/catalog` returns `checkout_enabled=false`.
`deploy-production.sh` runs that complete verifier in candidate mode before it
atomically replaces `.runtime/last-successful-release`. A candidate-verification
failure leaves the previously recorded SHA unchanged and follows the documented
failure/rollback policy.

## Failure and rollback policy

The backend applies `alembic upgrade head` before starting. For that reason the
default recovery policy is roll-forward: an older image may not recognize a
database revision introduced by the failed release.

Automatic rollback is disabled unless the operator sets
`SUBFRAME_ALLOW_SCHEMA_COMPATIBLE_ROLLBACK=1`. Use that opt-in only after
proving that the previous image recognizes the database's current Alembic
revision and that both schemas are code-compatible. A backup is mandatory but
does not by itself prove rollback compatibility.

The deploy script does not prune the shared Docker build cache by default,
because the VM also hosts MizAI and other projects. Set
`SUBFRAME_PRUNE_BUILD_CACHE=1` only during an explicit disk-recovery operation.

The frontend uses a same-origin API URL, so changing the domain does not require
a separate frontend code change.

After the script-level verification, confirm the public `https://gsubs.gr` UI,
`/health`, disabled paid-credit state, upload-to-login gate and mock export in a
real browser.
