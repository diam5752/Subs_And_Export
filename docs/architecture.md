# gsubs architecture

## Runtime profiles

The default development profile is mock-only. `GSP_MOCK_EXTERNAL_SERVICES=1` is
the application default and the root `docker-compose.yml` forces it explicitly.
The backend rewrites every transcription request to `mock-caption-v1` and
reports provider cost as zero. External-provider budgets default to `0.0`,
providing a second fail-closed barrier if mock mode is changed accidentally.

The tracked production profile is a separate contract in
`deploy/hetzner/docker-compose.production.yml`. It forces mock mode off, enables
only ElevenLabs Scribe v2 for caption transcription, and enables the reviewed
prepaid-credit Checkout contract. Startup and production verification require the
complete ElevenLabs and Stripe configuration from the untracked environment.
Every Scribe request must reserve purchased credits and pass the per-request,
daily, monthly and contribution-margin guards before provider dispatch. OpenAI
and Groq credentials remain empty and no relay route is provided for them.

The default mock services still exercise the real product boundaries:

1. The source video is validated and FFmpeg extracts/probes its media locally.
2. `MockTranscriber` emits deterministic Greek cues and per-word timestamps.
3. The normal subtitle renderer, preview, editor, SRT export and video export run.

## Components

| Surface | Responsibility | Persistent state |
| --- | --- | --- |
| Next.js PWA | Authentication UI, upload, timeline edit, styling, preview, installable shell | browser token and selected job only |
| FastAPI | Auth, jobs, capability discovery, orchestration, exports | PostgreSQL plus artifact volume |
| FFmpeg/libass | Probe, normalize, crop, subtitle burn-in and final encode | generated artifacts |
| Usage ledger | Idempotent points reservations and provider-cost audit | PostgreSQL |
| Java 25 surface | Contract-compatible migration path | test-only for now |

## Engine policy

The API catalog is capability-first:

- `mock-caption-v1`: default for local development; word-timed; zero external
  cost.
- ElevenLabs `scribe_v2`: production caption engine with native word timestamps
  and diarization capability. It is available only when mock mode is disabled,
  `GSP_ELEVENLABS_ENABLED=1`, a credential is supplied outside the repository,
  the guarded budgets are open and the request is backed by purchased credits.
- Groq Whisper Large v3 / Turbo: caption-ready because they expose word timing;
  catalogued but not enabled by the production contract.
- Local faster-whisper `large-v3-turbo`: private and provider-free; retained for a
  later server with suitable CPU/GPU capacity.
- OpenAI GPT transcription models: catalogued for text or speaker workflows,
  but not marked caption-ready because they do not expose the word-timing
  contract used by karaoke animation.
- OpenAI `whisper-1`: accepted only by the dedicated OpenAI caption adapter because
  it provides word timestamps; the adapter rejects incompatible models early.

## Deployment boundary

Local tests prove the code and local browser surface only. A production release
must follow `deploy/hetzner/README.md`, including the exact-SHA encrypted backup
and successful `verify-backup.sh --drill` receipt. `deploy-production.sh` applies
migrations and runs `verify-production.sh --candidate` before atomically replacing
`.runtime/last-successful-release`; a later standalone verifier requires that
recorded SHA to match. The verifier checks container health and image SHAs, the
reviewed payment/provider configuration, relay allow-lists, storage and erasure
continuity, the Alembic head, and the enabled approved billing catalog without
calling a third-party provider. HTTPS/public routing and a real browser smoke test
against the public URL remain separate release evidence.
