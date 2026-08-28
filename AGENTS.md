# gsubs repository guide

## Purpose and sources

Maintain the local-first subtitle studio: Next.js editing UI, FastAPI media/billing runtime, FFmpeg/libass export pipeline, PostgreSQL persistence, and the Java 25 compatibility/migration surface.

Prefer executable code and tests, then `README.md`, `docs/architecture.md`, `docs/credits-usage.md`, `.codex/quality-gates.json`, and `deploy/hetzner/README.md`. Use official documentation that matches the pinned dependency before changing framework behavior. For Next.js work, read `frontend/node_modules/next/dist/docs/`.

This root file is the only repository instruction file. Do not add singular, nested, Claude, Gemini, Copilot, Jules, Cursor, or Windsurf mirrors.

## Repository map

- `frontend/`: Next.js PWA, editor, history, auth, checkout, and browser tests.
- `backend/`: FastAPI API, database/migrations, jobs, billing, retention, and media pipeline.
- `src/main/java/`: Spring compatibility surface; keep its public contracts aligned with the active runtime.
- `.codex/`: executable quality contract and acceptance flows.
- `deploy/hetzner/`: production compose, backup, restore, deploy, and verification scripts.

## Non-negotiable contracts

- The default/local profile is deterministic and zero-cost. Never allow a client flag or ambient credential to activate a paid provider.
- Production transcription is ElevenLabs Scribe v2 only when the reviewed production profile, purchased credits, and provider budgets all allow it. Provider failure must fail closed.
- Credit mutation, fulfillment, cancellation, refund, and startup recovery must be idempotent. Never charge for an invalid or failed result.
- Customer media and derived files stay in the dedicated local volume. Preserve retention, erasure-journal continuity, private downloads, and cache/privacy headers.
- Do not log media, transcripts, credentials, cookies, payment data, or personal information.
- Preserve API/database backward compatibility unless the change includes a reviewed migration and release plan.
- UI work needs real responsive proof for the applicable signed-in and signed-out customer paths; export work needs a real decodable media artifact.

## Change and verification workflow

- Add the smallest regression test at the affected Python, TypeScript, Java, database, or browser boundary.
- Iterate with `make check-fast` or the narrow `make test-backend`, `make test-frontend`, or frontend test/spec command that covers the change.
- Keep new functions within the repository complexity and size limits; improve rather than expand an existing baseline.
- After the pull request exists and targeted checks pass, run `make ci` once. Treat the required GitHub security and image workflows as part of the merge gate.

## Delivery

- Branch from current `origin/main`, open one focused pull request, and merge only reviewed green code.
- A release must use the immutable merged SHA and the full procedure in `deploy/hetzner/README.md`: exact-SHA encrypted backup, restore-drill receipt where required, deployment, candidate verification, and public readback.
- Never bypass a backup, erasure-continuity, migration, or rollback guard. If verification fails, leave the edge in the state prescribed by the runbook and prepare a verified roll-forward.
