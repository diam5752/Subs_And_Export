# gsubs

[![Quality gates](https://github.com/diam5752/Subs_And_Export/actions/workflows/quality-gates.yml/badge.svg?branch=main)](https://github.com/diam5752/Subs_And_Export/actions/workflows/quality-gates.yml)
[![CodeQL](https://github.com/diam5752/Subs_And_Export/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/diam5752/Subs_And_Export/actions/workflows/codeql.yml)
[![Container images](https://github.com/diam5752/Subs_And_Export/actions/workflows/container-images.yml/badge.svg?branch=main)](https://github.com/diam5752/Subs_And_Export/actions/workflows/container-images.yml)

gsubs is a local-first subtitle studio for turning a raw vertical clip into editable,
word-timed captions and an export-ready video. The default development profile is
deliberately zero-cost: it performs the complete workflow with deterministic mock
transcription and never calls an external provider. The
separate production profile uses ElevenLabs Scribe v2 for caption transcription and
Stripe-hosted Checkout for prepaid credits under fail-closed release guards.

## What is included

- Next.js 16, React 19 and Tailwind CSS 4 responsive PWA.
- FastAPI processing API with authenticated jobs, history and exports.
- FFmpeg/libass rendering for 9:16 video, SRT and animated subtitles.
- Deterministic Greek mock transcription with per-word timing for local development.
- ElevenLabs Scribe v2 production transcription guarded by purchased credits and
  provider budgets.
- Optional deterministic local social-copy output for the command-line workflow.
- Stripe-hosted prepaid-credit Checkout with server-owned prices and fulfillment.
- Hard provider budgets that default to `$0.00` outside the reviewed production
  profile.
- PostgreSQL persistence and Docker Compose packaging.
- Java 25 compatibility surface for the gradual Spring migration.

## Run with Docker

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

Open:

- Web app: <http://localhost:3000>
- API health: <http://localhost:8080/health>

The root `docker-compose.yml` forces mock mode and keeps provider budgets at zero,
even if a client requests `elevenlabs`, `groq`, or `openai`; the example local
environment also disables paid credits. It is the safe local/default profile.
Production is a separate, tracked contract in
`deploy/hetzner/docker-compose.production.yml`; its release procedure, backup and
restore-drill gates, and exact verifier are documented in
`deploy/hetzner/README.md`. Credentials belong only in the untracked production
environment and must never be committed.

## Local development

Requirements: Python 3.11+, Node.js 20+, FFmpeg with libass, PostgreSQL, and JDK
25 only when running the Java compatibility checks.

```bash
make install
make run
```

In another terminal:

```bash
cd frontend
npm run dev
```

The installable PWA manifest is available at `/manifest.webmanifest`; production
browsers register the local service worker automatically.

## Quality gates

```bash
make check-fast
make ci
```

`make ci` is the canonical local and GitHub entrypoint. It creates a unique
temporary PostgreSQL database for the run, executes the complete `check-all`
contract, and drops the database even when a gate fails. `make check-all`
remains an equivalent alias.

Individual checks:

```bash
make test-backend
make test-frontend
make check-complexity
make check-java
cd frontend && npm run build && npm run e2e
```

The complexity gate covers production Python, TypeScript and Java. New functions
must stay at cyclomatic complexity 10 or below and at 50 active lines or below.
Existing hotspots are tracked in a reviewed ratchet: they may improve, but any new
or worsened hotspot fails CI.

Pull requests also run CodeQL across all three languages, reject newly introduced
high/critical dependency vulnerabilities and committed secrets, and build plus
scan both production container images. Dependabot groups routine npm, Python,
Maven, Docker and GitHub Actions updates into weekly reviewable pull requests.

## Contributing and security

- Read `CONTRIBUTING.md` before opening a pull request.
- Follow `CODE_OF_CONDUCT.md` and use `SUPPORT.md` to choose the right reporting
  channel.
- Use the structured GitHub issue forms for reproducible bugs and feature requests.
- Never post customer media, transcripts, credentials, payment data or personal
  information in a public issue.
- Report vulnerabilities privately through GitHub Security Advisories as described
  in `SECURITY.md`.
- Production changes must follow `deploy/hetzner/README.md`; a green merge is not
  evidence that the reviewed SHA is live.

## Architecture

- `backend/`: FastAPI API and media pipeline.
- `frontend/`: Next.js PWA and editing workflow.
- `src/main/java/`: Java 25/Spring compatibility surface.
- `docs/architecture.md`: runtime boundaries and mock/live engine policy.
- `docs/credits-usage.md`: points and usage-ledger semantics.

The default local profile keeps every live provider disabled. The production
profile enables only ElevenLabs Scribe v2 for captions and requires an existing
purchased-credit balance, the complete Stripe configuration and non-zero guarded
provider budgets. OpenAI and Groq credentials remain empty there. The caption
pipeline only exposes engines that can produce the timestamps required by the
renderer.
