# PostgreSQL 16 security runtime

Compose requires an explicit `POSTGRES_IMAGE`. Use a locally loaded immutable image ID from this recipe. The target for this repository preserves Alpine 3.24 / PostgreSQL UID 70; do not substitute the other target or change the data-volume ownership.

The shared Dockerfile pins PostgreSQL 16.15 bases, the gosu 1.20 upstream source archive and Go 1.27.3. It applies the base distribution's available package updates and replaces gosu with the tested upstream parser fix. The target keeps the official entrypoint's initial root setup and its existing transition to the postgres user. It changes no database schema or extension.

Build on the approved Linux build host, then scan and validate the actual image before promotion:

```sh
POSTGRES_IMAGE="$(deploy/postgres-security/build.sh)"
docker image inspect "$POSTGRES_IMAGE" >/dev/null
printf 'POSTGRES_IMAGE=%s\n' "$POSTGRES_IMAGE"
```

The helper loads only `postgres-alpine-security` for linux/amd64, sends build logs to stderr and prints its actual image ID. It publishes no image and uses no registry credentials. `POSTGRES_BUILD_IMAGE` and `POSTGRES_BUILD_PLATFORM` are local build options. The reviewed 27 October candidate is `sha256:8ffedfbad54433138b8fb59d5dab4118bafb2449d04805657c78d44278d59da4`; Docker build metadata can change later IDs. Record the actual verified ID in the existing private environment, with mode0600 and all other settings preserved.

[PostgreSQL 16.15 release notes](https://www.postgresql.org/docs/release/16.15/) describe this minor security update. Upstream does not require dump/restore for 16.X. This project's promotion nevertheless requires a fresh encrypted backup, independent full restore on the exact candidate, integrity and roundtrip checks, and captured old/new image IDs. Check extensions, logical slots and recorded/actual libc or ICU collation versions; stop for an unexpected mismatch. Do not run extension upgrades, application migrations or blanket REINDEX as part of this image update.

## Database-only promotion and rollback

Use the reviewed host procedure under the existing deployment lock. Freeze the current Compose files, private environment and old database image ID in durable private state. Prove the exact production volume and preserve its mounts, networks, user, configuration and application images. Quiesce ingress and all database writers, wait for active work and transactions to drain, then take the final encrypted backup and stop PostgreSQL cleanly. Replace only the database service with `--no-deps --no-build --pull never` and the verified image. Do not invoke the full application release script for this database-only operation.

Keep writers paused until server version, extensions, collation, database readiness and read-only application projections pass. A failure before writers resume requires stopping the candidate cleanly and restoring the frozen old image/environment on the same volume. Retain the old image locally. A failure after writes resume requires a new reviewed plan; never restore an older backup over current production data. The normal application rollback does not capture the database image, so its success marker is not database rollback evidence.

The isolated restore-drill receipt is separate from production and from any canonical schema-changing release receipt. Never manufacture an existing deployment guard's receipt from this drill. Follow the exact-release and backup requirements in the root repository guide before delivery.

## Compose regression check

Run `python -m pytest --noconftest -o addopts='' deploy/postgres-security/test_compose_contract.py`. This check renders Compose without starting containers or resolving private env files. Missing and empty pins must fail; the verified pin must preserve `subframe-postgres-data`. It lives outside the backend image's copied input tree. The normal full repository gates remain required separately.

## Existing database entrypoint role

The exact `deploy/postgres-security/Dockerfile` path has a structured DS-0002 exception in `deploy/caddy-security/trivy-role-exception.yaml`. The recipe retains the official entrypoint's existing root initialization and gosu transition to postgres UID 70 or UID 999. Its scope is this database-role recipe file; Trivy cannot distinguish the two named targets here. It grants no exception to application images or dependency CVEs. Keep the same production mounts, private networks and Compose healthchecks.

Use `trivy config --ignorefile deploy/caddy-security/trivy-role-exception.yaml .` for configuration evidence. Generic DS-0026 Dockerfile-healthcheck findings may remain because healthchecks are owned by Compose; record them honestly. An unrelated root application Dockerfile must still fail DS-0002 under this same exception configuration. Actual image vulnerability scanning remains separate, at all severities without CVE suppressions.
