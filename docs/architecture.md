# SUBFRAME architecture

## Current runtime contract

The current release is mock-only. `GSP_MOCK_EXTERNAL_SERVICES=1` is the default
and Docker forces it explicitly. The backend rewrites every transcription
request to `mock-caption-v1`, disables LLM reservations, and reports provider
cost as zero. Both external-provider budget settings default to `0.0`, providing
a second fail-closed barrier if mock mode is changed accidentally.

The mock services still exercise the real product boundaries:

1. The source video is validated and FFmpeg extracts/probes its media locally.
2. `MockTranscriber` emits deterministic Greek cues and per-word timestamps.
3. The normal subtitle renderer, preview, editor, SRT export and video export run.
4. Fact-check and social-copy endpoints return clearly labelled deterministic
   previews without network calls or usage reservations.

## Components

| Surface | Responsibility | Persistent state |
| --- | --- | --- |
| Next.js PWA | Authentication UI, upload, timeline edit, styling, preview, installable shell | browser token and selected job only |
| FastAPI | Auth, jobs, capability discovery, orchestration, exports | PostgreSQL plus artifact volume |
| FFmpeg/libass | Probe, normalize, crop, subtitle burn-in and final encode | generated artifacts |
| Usage ledger | Idempotent points reservations and provider-cost audit | PostgreSQL |
| Java 25 surface | Contract-compatible migration path | test-only for now |

## Engine policy for later live mode

The API catalog is capability-first:

- `mock-caption-v1`: current and recommended; word-timed; zero external cost.
- Groq Whisper Large v3 / Turbo: caption-ready because they expose word timing;
  unavailable until live mode and a credential are explicitly enabled.
- Local faster-whisper `large-v3-turbo`: private and provider-free; retained for a
  later server with suitable CPU/GPU capacity.
- OpenAI GPT transcription models: catalogued for text or speaker workflows,
  but not marked caption-ready because they do not expose the word-timing
  contract used by karaoke animation.
- OpenAI `whisper-1`: accepted only by the legacy OpenAI caption adapter because
  it provides word timestamps; the adapter rejects incompatible models early.

## Deployment boundary

Local tests prove the code and local browser surface only. A production release
also requires a server-side database backup, persistent artifact volume, HTTPS
reverse proxy, production origin/host configuration, migrations, health checks,
and a real browser smoke test against the public URL.
