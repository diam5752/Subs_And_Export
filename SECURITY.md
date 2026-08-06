## Security checklist (Hetzner + Docker)

The persistent production media-storage path is local-only. Source videos and
generated artifacts must remain inside the dedicated backend Docker volume;
do not add external object storage or storage credentials. The separately
disclosed ElevenLabs processing boundary still receives extracted audio and is
governed by the controls below.

### Required App Config (Production)
- Set `APP_ENV=production`.
- Set `GSP_ALLOWED_ORIGINS` to your exact frontend origin(s) (no wildcards).
- Set `GSP_TRUSTED_HOSTS` to your backend hostnames (do **not** use `*` in production).
- Optionally set `GSP_PROXY_TRUSTED_HOSTS` to the proxy CIDRs/IPs that should be allowed to set `X-Forwarded-*`.

### Upload Limits
- Backend enforces a **500 MB maximum upload size** and **10-minute maximum duration** by default.
- Uploads go through the authenticated backend stream endpoint into the dedicated local volume.
- Keep the backend and database off the public network; only the edge proxy may reach them.

### Media retention and erasure
- Keep automatic retention enabled. Production defaults are 24 hours for terminal workspaces, 6 hours for stale active jobs, and 1 hour for orphan files.
- Project and account erasure must remove both database ownership records and the exact local workspace before reporting success.
- Encrypted server and independent backups have a 14-day default retention. An erased item may persist only in an already-created encrypted backup until that backup expires.
- After any restore, keep public traffic closed until automatic retention and the durable post-backup erasure reconciliation have completed successfully.
- Restore is supported only while the current host continuity state and live erasure-journal volume both survive. If either is lost, fail closed: do not restore/publish an older user database or media backup. The zero-extra-storage policy accepts data loss after total host loss; disaster recovery of user data would require a continuously updated encrypted journal copy in another failure domain.

### ElevenLabs processor boundary
- The edge permits only Scribe creation and deletion of a validated transcript ID; it does not provide a general ElevenLabs proxy.
- The backend must require the returned transcript ID, copy the result locally, request immediate provider deletion, and retry a failed deletion from the durable privacy journal.
- Offline restore/deploy reconciliation uses a temporary private relay with no published port and only the validated transcript DELETE route; stop it before reopening the public edge.
- Do not set or claim `enable_logging=false`, Zero Retention Mode, or EU data residency unless the actual ElevenLabs account has been contractually enabled and independently verified. Standard provider-side retention and transfers remain governed by the applicable DPA and account settings.
- Recheck the official [transcript deletion API](https://elevenlabs.io/docs/api-reference/speech-to-text/delete), [Zero Retention documentation](https://elevenlabs.io/docs/eleven-api/resources/zero-retention-mode), [data-residency documentation](https://elevenlabs.io/docs/overview/administration/data-residency), and [DPA](https://elevenlabs.io/dpa) before changing this boundary.

### Secrets
- Do not bake secrets into the image.
- Keep production secrets only in the host's untracked, mode-0600 `.env.production` file; grant read access only to the deployment operator and the exact containers that require each value.
- Treat any key that ever appeared in logs or a committed file as compromised and rotate it.

### Host hardening
- Restrict ingress to the public edge proxy and SSH administration path.
- Encrypt backup archives before they leave the host and keep the age identity in separate custody.
- Enable host and edge event logging with alerting for authentication failures and traffic spikes; do not log request bodies, media, transcript IDs, or bearer credentials. The internal ElevenLabs relay intentionally has no Caddy access-log directive.

### Local + CI Security Scans
- Backend: `python3 -m pytest` and `ruff check backend`
- Frontend: `npm test` and `npm run lint`
- Dependency audits:
  - Frontend: `cd frontend && npm audit --audit-level=high`
  - Python env: `pip-audit -l` (run inside the environment you deploy)

### Dynamic Scanning (OWASP)
- Use OWASP ZAP (baseline/passive scan) against a running staging deployment:
  - Scan the frontend URL and API URL.
  - Confirm security headers, CORS behavior, auth flows, and IDOR protections.

### Packet / Request Tracing
- Prefer application, edge and host telemetry over raw packet capture, which can expose user media or credentials.
