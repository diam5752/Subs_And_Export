# Optional Google Cloud Run lane

The active SUBFRAME production procedure is documented in
`deploy/hetzner/README.md`. The Cloud Build files remain available as an
optional deployment lane:

- `backend-cloudbuild.yaml` builds and updates the FastAPI service.
- `frontend/cloudbuild.yaml` builds and updates the Next.js service.

Do not deploy from an unreviewed working tree or use force-pushed release tags.
Run `make check-all` on a machine with JDK 25, then deploy an immutable commit
from `main` through protected Cloud Build triggers.

## Required safety configuration

Keep the current product in deterministic mock mode unless live providers have
been approved explicitly:

```text
GSP_MOCK_EXTERNAL_SERVICES=1
GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0
GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0
GSP_USE_LLM_BY_DEFAULT=0
```

No OpenAI, Groq, ElevenLabs, Google OAuth or database credential belongs in the
repository or in build substitutions. Store deployment credentials in the
platform secret manager and grant each service account only the permissions it
needs.

## Backend trigger

Use `backend-cloudbuild.yaml` as the trigger configuration. Configure the Cloud
Run service with:

- the production PostgreSQL URL;
- the exact frontend origin in `GSP_ALLOWED_ORIGINS`;
- the exact service hosts in `GSP_TRUSTED_HOSTS`;
- trusted proxy networks in `GSP_PROXY_TRUSTED_HOSTS`;
- a persistent GCS bucket if uploads and exports must survive container
  restarts.

The runtime service account needs object access only to the selected bucket. If
signed URLs are enabled, it also needs permission to sign as itself.

## Frontend trigger

Use `frontend/cloudbuild.yaml` and set `_NEXT_PUBLIC_API_URL` to the HTTPS URL of
the backend service. The browser origin must match the backend CORS allowlist
exactly.

## Release verification

After Cloud Build completes, verify the deployed commit SHA, `/health`, the
public upload-to-login gate, one mock processing job, and both video and subtitle
exports. Local green tests are necessary, but they are not proof that the public
deployment is healthy.
