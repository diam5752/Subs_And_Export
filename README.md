# SUBFRAME

Mock-first subtitle studio for turning a raw vertical clip into editable,
word-timed captions and an export-ready video. The current mode is deliberately
zero-cost: it performs the complete workflow with deterministic mock transcript
and intelligence services and never calls OpenAI, Groq, or another AI provider.

## What is included

- Next.js 16, React 19 and Tailwind CSS 4 responsive PWA.
- FastAPI processing API with authenticated jobs, history and exports.
- FFmpeg/libass rendering for 9:16 video, SRT and animated subtitles.
- Deterministic Greek mock transcription with per-word timing.
- Honest mock fact-check cards and local social-copy preview.
- Provider capability catalog for a later opt-in live mode.
- Hard provider budgets defaulting to `$0.00` per request and per month.
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

The tracked Compose configuration forces mock mode and zero provider budgets,
even if a client submits `groq` or `openai` as its preferred engine. API keys do
not belong in this repository and are not needed for the current product.

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
make check-all
```

Individual checks:

```bash
make test-backend
make test-frontend
make check-java
cd frontend && npm run build && npm run e2e
```

## Architecture

- `backend/`: FastAPI API and media pipeline.
- `frontend/`: Next.js PWA and editing workflow.
- `src/main/java/`: Java 25/Spring compatibility surface.
- `docs/architecture.md`: runtime boundaries and mock/live engine policy.
- `docs/credits-usage.md`: points and usage-ledger semantics.

Live providers remain disabled until credentials and non-zero app budgets are
explicitly configured. The caption pipeline only exposes engines that can
produce the timestamps required by the renderer; newer text-only transcription
models are catalogued separately instead of being presented as caption-ready.
