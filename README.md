# Greek Sub Publisher

Local-first tooling to normalize vertical videos, transcribe Greek audio with faster-whisper, burn styled subtitles (ASS), and generate social copy.

## Requirements
- Python 3.11+
- ffmpeg available on PATH
- Optional for LLM copy: `OPENAI_API_KEY` and `pip install openai` (see `OPENAI_SETUP.md` for secure setup tips)
- Optional for auth/publishing:
  - Google OAuth: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
  - TikTok publishing: `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET`, `TIKTOK_REDIRECT_URI`
    (register an app in TikTok Dev Console; enable the `video.upload` scope)

Install deps:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Usage
```bash
python -m greek_sub_publisher.cli INPUT.mp4 --output OUTPUT.mp4 --artifacts ./artifacts \
  --model medium --language el --beam-size 5 --best-of 1
```
Add `--llm-social-copy` (and optionally `--llm-model`, `--llm-temperature`) to draft social copy via an OpenAI-compatible LLM.

Artifacts directory will contain WAV/SRT/ASS/transcript and social_copy files.

Need help configuring OpenAI? Check `OPENAI_SETUP.md` for environment variable and secrets instructions.

## Auth, sessions, and TikTok uploads
- Users can sign in with Google or a local email/password account (hashed + salted). The app now uses a SQLite database (`logs/app.db` by default) instead of loose JSON files. Override the path with `GSP_DATABASE_PATH` to place the DB on a persistent volume (e.g., an EBS mount in AWS).
- All processing/publishing runs are tied to the signed-in user and logged to the `history` table. Session tokens are hashed at rest; they auto-issue on both Google and local logins so returning users are signed in automatically in the web UI.
- TikTok uploads stay inside the app: connect your TikTok account (OAuth) and upload the processed MP4 directly after a run. Tokens are stored in session only; reconnect when expired.

## Production readiness
- **Scalability**: SQLite is opened in WAL mode with a busy-timeout for better concurrency; for heavier multi-instance deployments point `GSP_DATABASE_PATH` at a shared filesystem path or swap to a managed SQL backend by reusing the `Database` helper.
- **Security & privacy**: Passwords and session tokens are hashed; Google OAuth IDs are stored for account linking only. Audit logs stay local-first. Review your privacy policy and OAuth consent screen before publishing.
- **Cloud deployment**: On AWS/other clouds, run the FastAPI backend (`uvicorn backend.main:app`) behind TLS alongside the Next.js frontend. Persist `logs/app.db` on durable storage and set env vars or `config/secrets.toml` values for Google/TikTok OAuth secrets. Add network egress controls if processing sensitive media.

## Tests
- Fast suite (CI default): `pytest -m "not slow"`
- Full suite (includes regression on `tests/data/demo.mp4` and Whisper run): `pytest`
- LLM path is tested with stubs; no network required.

## CI
GitHub Actions workflow `.github/workflows/tests.yml` installs deps and runs `pytest -m "not slow"` to avoid downloading large Whisper models. Run the full suite locally before releases.***
