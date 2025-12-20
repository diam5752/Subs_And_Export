# Greek Sub Publisher

Local-first tooling for Greek subtitles and vertical video prep.

## Project Structure

This project follows a clean monorepo structure:

- **`backend/`**: FastAPI backend service.
    - `app/core`: Configuration, Auth, Database.
    - `app/services`: Business logic (Video Processing, Subtitles).
    - `app/api`: REST Endpoints.
- **`frontend/`**: Next.js frontend application.
- **`docker-compose.yml`**: orchestration for the full stack.

## Quick Start (Docker)

The easiest way to run the project is with Docker:

### 1. Configure Environment
```bash
cp .env.docker.example .env.docker
# Edit .env.docker with your API keys (OPENAI_API_KEY, GROQ_API_KEY, etc.)
```

### 1.5 Environments (Dev vs Production)

This repo uses a single environment variable across backend + frontend:

- `APP_ENV=dev` (default): orange dev vibe + visible environment badge + Dev Tools (sample video loader).
- `APP_ENV=production`: normal production vibe.

For Docker:
```bash
# Default (dev)
docker-compose up --build

# Production-like
APP_ENV=production docker-compose up --build
```

For Google Cloud Run: set `APP_ENV` as a service environment variable on both the backend and frontend services.

### 2. Build & Run
```bash
docker-compose up --build
```

This starts:
- **Backend**: http://localhost:8080 (API + static files)
- **Frontend**: http://localhost:3000 (Web UI)

### 3. Verify
```bash
curl http://localhost:8080/health  # Should return {"status": "ok"}
```

> **Note**: First transcription may take longer as Whisper models are downloaded.
> Models are cached in a Docker volume (`gsp_whisper_models`) for subsequent runs.

## Local Development

### Prerequisites
- Python 3.11+
- Node.js 20+
- FFmpeg installed (`brew install ffmpeg`)

### Setup

```bash
make install
```

### Running

To run the backend locally:
```bash
make run
```

To run the frontend:
```bash
cd frontend && npm run dev
```

### Testing

Run the full backend test suite:
```bash
make test
```

## Docs
- Credits and usage ledger: `docs/credits-usage.md`

## Features
- **Auto-Subtitles**: Generates Greek subtitles using Faster-Whisper.
- **Vertical Crop**: Intelligently crops videos for vertical formats.
- **Viral Intelligence**: Generates viral hooks and captions/hashtags.
