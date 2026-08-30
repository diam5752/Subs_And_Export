# Critical Acceptance Flows

These flows reflect the product behavior explicitly approved during the guest-first workflow review.

## Status

- human_reviewed

## Candidate flows

- Unauthenticated users can open `/`, select a video, and configure subtitle options without losing their work.
- Login and register layouts remain readable and overflow-free on desktop and mobile.
- Starting paid or provider-backed processing prompts an unauthenticated user to log in, then resumes with the selected local video and settings intact.
- Before a chargeable action starts, the user sees the required credit amount and cannot proceed with an insufficient balance.
- Uploading a video can progress from upload to processing to completed preview, inline subtitle editing, and separate video/subtitle export actions.
- Processing-job polling surfaces active jobs from history and handles authenticated state correctly.
- Completed previews keep the video, transcript, styling controls, and inline editor usable without layout breakage across supported viewports.
- The account settings modal remains usable and readable across supported viewports.
- History views show prior jobs and status cards without layout regressions.
- Mock mode never calls a paid external provider and remains the default until live mode and non-zero safety budgets are explicitly enabled.
- On iOS, selecting a Photos video, receiving subtitles, correcting cues and exporting a decodable MP4 never sends or persists the source or exported video on the server; the API rejects any body containing a video stream, and only bounded temporary AAC audio reaches transcription.
- The iOS privacy copy distinguishes temporary audio transfer from replay-safe subtitle retention: cues remain live for at most 24 hours and may remain only in encrypted backups for up to 14 days.

Do not remove or redefine these flows without a new explicit product decision.
