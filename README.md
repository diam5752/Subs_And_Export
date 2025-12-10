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

```bash
make docker-up
```
This will build and start both backend (port 8000) and frontend (port 3000).

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

## Features
- **Auto-Subtitles**: Generates Greek subtitles using Faster-Whisper.
- **Vertical Crop**: Intelligently crops videos for TikTok/Reels.
- **Social Upload**: Uploads directly to TikTok.
- **Viral Intelligence**: Generates viral hooks and captions/hashtags.
