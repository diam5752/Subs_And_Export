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
| iOS app | Photos selection, local preview/editing, local AAC extraction and local MP4 subtitle burn-in | Keychain session plus one owner-bound, device-local draft |
| FastAPI | Auth, jobs, capability discovery, orchestration, exports | PostgreSQL plus artifact volume |
| FFmpeg/libass | Probe, normalize, crop, subtitle burn-in and final encode | generated artifacts |
| Usage ledger | Idempotent points reservations and provider-cost audit | PostgreSQL |
| Java 25 surface | Contract-compatible migration path | test-only for now |

## iOS local-media boundary

The native iOS flow deliberately does not reuse the web video-upload endpoint.
`PhotosPicker` provides a device-local movie, AVFoundation extracts a bounded AAC
audio track, and `POST /videos/mobile-transcriptions` returns word-timed cue JSON.
The client then previews, edits and burns those cues into a new MP4 with
AVFoundation/Core Image on the phone.

The current source, optional preview proxy, cues, style and transcription
idempotency key are kept as one versioned draft under Application Support. The
manifest is committed atomically, contains only validated relative paths, is
excluded from backup and is restored only after `/auth/me` confirms the exact
owner. Audio extraction and rendered exports remain scratch files. Reset,
replacement, sign-out, invalid authentication and confirmed or ambiguous account
deletion purge the private draft; transient network/server failures leave it
locked for a later authenticated retry.

The route accepts at most 16 MiB of AAC audio, probes every stream from memory with
`ffprobe pipe:0`, rejects any container carrying a video stream, and never creates
an upload or artifact file. A bounded cross-process pool controls untrusted audio
probing, and new requests run an owner-wallet preflight before their body is read.
The production engine is selected by the server and is Scribe v2; a client field
cannot activate or replace the paid provider. The normal purchased-credit,
provider-budget, dispatch-claim, refund and replay-safe result guards remain in
force. Development mock mode returns deterministic cues at zero provider cost.

This is "no video upload", not "no network media". Scribe v2 still requires the
extracted audio to cross the network temporarily. The provider transcript is
erasure-journaled and deleted before GSUBS accepts the result. The small replay-safe
cue result is removed with the existing 24-hour job retention pass.
It may remain only in already-created encrypted backups until the documented
14-day backup-retention window expires.

## Privacy-bounded operational observability

Production enables a first-party diagnostic surface for bug repair. The browser
sends only a fixed event vocabulary, coarse route and viewport buckets, export
format buckets, status categories, and runtime heartbeats. The server persists
content-free events in `/data/observability/events.jsonl` for at most 168 hours
and holds active presence only in memory for 90 seconds. Signed-in accounts are
deduplicated by a runtime-salted key; guest browser IDs exist only for the current
page runtime. Neither identifier is written to disk.

The intake schema rejects arbitrary fields. It cannot accept media, captions,
filenames, email, user IDs, IP addresses, cookies, raw error messages, stacks,
keystrokes, or replay data. A dedicated immutable user-ID allow-list protects
the no-store `/observability/admin/snapshot` response. The public intake has a
4 KiB body limit and an in-memory abuse limiter so its network key does not
become analytics data. Diagnostic writes are best-effort and can never make a
product action fail.

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
