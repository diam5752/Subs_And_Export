# Google Cloud Deployment Guide

This guide describes how to deploy the Ascentia Subs frontend and backend to Google Cloud Run using Cloud Build triggers.

## 1. Prerequisites

- A Google Cloud Project with billing enabled.
- **Cloud Run** and **Cloud Build** APIs enabled.
- Access to the source code repository (connected to Cloud Build).

## 2. Setup Triggers

You need two Cloud Build triggers. They can both listen to the same tag (e.g., `production`) or different ones.

### Backend Trigger
1.  Go to **Cloud Build > Triggers** in the Google Cloud Console.
2.  Click **Create Trigger**.
3.  **Name**: `deploy-backend-production`
4.  **Event**: Push new tag
5.  **Tag Pattern**: `production` (or `v.*` for version tags like v1.0)
6.  **Configuration**: Cloud Build configuration file (yaml or json).
7.  **Location**: `backend-cloudbuild.yaml` (Select "Repository" as source).
8.  Click **Create**.

### Frontend Trigger
1.  Click **Create Trigger**.
2.  **Name**: `deploy-frontend-production`
3.  **Event**: Push new tag
4.  **Tag Pattern**: `production`
5.  **Configuration**: Cloud Build configuration file (yaml or json).
6.  **Location**: `frontend/cloudbuild.yaml` (Select "Repository" as source).
7.  **Substitution Variables** (Critical Step):
    *   Add a new variable:
        *   **Variable**: `_NEXT_PUBLIC_API_URL`
        *   **Value**: `https://YOUR-BACKEND-SERVICE-URL.run.app`
    *   *Note: You get the Backend URL after deploying the backend once. If this is the first time, deploy backend first, get the URL, then set up this trigger.*
8.  Click **Create**.

## 3. Environment Variables

### Backend Service (Cloud Run)
Go to **Cloud Run > Services > ascentia-subs > Edit & Deploy New Revision > Variables & Secrets**.
Add the following Environment Variables:

*   `GSP_ALLOWED_ORIGINS`: `https://YOUR-FRONTEND-SERVICE-URL.run.app` (The URL of your deployed frontend).
*   `GSP_TRUSTED_HOSTS`: `YOUR-BACKEND-SERVICE-URL.run.app,*.a.run.app` (Host header allowlist; do **not** use `*` in production).
*   `GSP_PROXY_TRUSTED_HOSTS`: `127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` (Trusted proxy networks for `X-Forwarded-*` parsing).
*   `GSP_GCS_BUCKET`: `YOUR_BUCKET_NAME` (Enables direct-to-GCS uploads + GCS-backed `/static` redirects).
*   `GSP_GCS_UPLOADS_PREFIX`: `uploads` (Optional; keep default unless you have a naming convention).
*   `GSP_GCS_STATIC_PREFIX`: `static` (Optional; this is where processed artifacts are stored).
*   `GSP_GCS_KEEP_UPLOADS`: `1` (Recommended if you need Export/Re-renders; use `0` for minimal retention).
*   `GSP_GCS_UPLOAD_URL_TTL_SECONDS`: `3600` (Optional; signed upload URL lifetime).
*   `GSP_GCS_DOWNLOAD_URL_TTL_SECONDS`: `600` (Optional; signed download URL lifetime used by `/static` redirects).
*   `GSP_GCS_SIGNER_EMAIL`: `YOUR_RUNTIME_SA@YOUR_PROJECT.iam.gserviceaccount.com` (Optional; set if signing fails to resolve the service account email).

### Data Persistence Warning
> [!WARNING]
> **Files are ephemeral.**
> The current application saves uploads and generated files to the local container filesystem (`/data`).
> On Cloud Run, **these files vanish** when the container restarts or scales down.
> **Production Fix**: Configure `GSP_GCS_BUCKET` so uploads and artifacts persist in Google Cloud Storage (GCS).

### Large Uploads Warning
> [!WARNING]
> **Cloud Run request bodies are size-limited.**
> If you need ~1GB uploads in production, use a **direct-to-GCS upload flow** (signed URL / resumable upload), then submit the object name to the backend for processing.

### Required IAM (Cloud Run)
- Cloud Run runtime service account needs:
  - `roles/storage.objectAdmin` (or split into `storage.objectCreator` + `storage.objectViewer`) on the bucket.
  - `roles/iam.serviceAccountTokenCreator` on itself (required to sign URLs via IAM `signBlob`).

### Bucket CORS (Required for Browser Uploads/Downloads)
- Configure CORS on the bucket to allow your frontend origin for:
  - `PUT` (upload) with header `Content-Type`
  - `GET` (download) for `/static` redirects

## 4. How to Deploy

To deploy a new version:

1.  Commit your changes to `master`.
2.  Tag the commit:
    ```bash
    git tag -f production
    git push -f origin production
    ```
3.  This will fire both triggers.
4.  Monitor the build progress in **Cloud Build > History**.

## 5. Troubleshooting

-   **Frontend cannot connect**: Check the browser console. If you see CORS errors, update the `GSP_ALLOWED_ORIGINS` variable in the Backend Cloud Run service to match your Frontend URL exacty.
-   **Build fails**: Check Cloud Build logs. Common issues are permission errors (Cloud Build service account needs `Cloud Run Developer` and `Service Account User` roles).
