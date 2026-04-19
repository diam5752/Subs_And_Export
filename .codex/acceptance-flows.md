# Critical Acceptance Flows

Human review is required before this file becomes the canonical acceptance contract.

## Status

- needs_human_review

## Candidate flows

- Unauthenticated users are redirected from `/` to `/login`.
- Login and register layouts remain readable and overflow-free on desktop and mobile.
- Authenticated users can reach the workspace and see the upload area after selecting a model.
- Uploading a video can progress from upload to processing to completed preview and export actions.
- Processing-job polling surfaces active jobs from history and handles authenticated state correctly.
- Completed previews render transcript and styling surfaces without layout breakage.
- The account settings modal remains usable and readable across supported viewports.
- History views show prior jobs and status cards without layout regressions.

Do not let the agent silently remove or redefine these flows without human approval.
