## Security Checklist (Cloud Run + Docker)

This repository contains security hardening in code, but **production security also depends on your Cloud Run + GCP configuration**.

### Required App Config (Production)
- Set `APP_ENV=production`.
- Set `GSP_ALLOWED_ORIGINS` to your exact frontend origin(s) (no wildcards).
- Set `GSP_TRUSTED_HOSTS` to your backend hostnames (do **not** use `*` in production).
- Optionally set `GSP_PROXY_TRUSTED_HOSTS` to the proxy CIDRs/IPs that should be allowed to set `X-Forwarded-*`.

### Upload Limits
- Backend enforces **max upload size 1GiB** and **max duration 3 minutes**.
- Cloud Run has request body limits; for large uploads use **direct-to-GCS uploads** (signed URL / resumable upload), then pass the object name to the backend.
- When `GSP_GCS_BUCKET` is set, processed `/static/*` responses can be served via **signed GCS URLs** (redirect), so artifacts persist across Cloud Run restarts.

### GCS Hardening (Recommended)
- Use a dedicated bucket with **Uniform bucket-level access** enabled.
- Apply a **Lifecycle Policy** to auto-delete old objects (uploads/artifacts) according to your retention policy.
- IAM (minimum):
  - Cloud Run runtime SA: `roles/storage.objectViewer` + `roles/storage.objectCreator` (or `roles/storage.objectAdmin`) on the bucket.
  - Cloud Run runtime SA: `roles/iam.serviceAccountTokenCreator` on itself (required for Signed URL `signBlob` on Cloud Run).
- Bucket CORS (required for browser direct uploads / `/static` redirects):
  - Allow your frontend origin for `PUT` (upload) and `GET` (download).
  - Allow request header `Content-Type`.

### Secrets
- Do not bake secrets into the image.
- Prefer **Secret Manager** and mount secrets as env vars in Cloud Run.
- Treat any key that ever appeared in logs or a committed file as compromised and rotate it.

### Cloud Run Hardening
- Use a dedicated **service account** with minimum permissions.
- Restrict ingress if possible (e.g. only via HTTPS LB + Cloud Armor).
- Add **Cloud Armor WAF + rate limiting** in front of the services.
- Enable **Cloud Audit Logs** and set alerting for suspicious patterns (auth failures, spikes, 4xx/5xx bursts).

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
- Prefer platform telemetry over raw packet capture:
  - Cloud Logging request logs
  - Cloud Trace (latency + request tracing)
  - Cloud Armor logs (blocked requests)
  - VPC Flow Logs (egress visibility, if using VPC connectors)
