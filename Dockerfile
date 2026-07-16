FROM python:3.11-slim AS builder

# Install build dependencies for native packages (faster-whisper, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
ARG REQUIREMENTS_FILE=backend/requirements.mock.txt
COPY ${REQUIREMENTS_FILE} requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ============================================
FROM python:3.11-slim AS runtime

# Install runtime system dependencies
# - ffmpeg: video/audio processing
# - fonts-*: subtitle text rendering (Greek support)
# - libgl1: OpenCV dependency
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    fonts-dejavu-core \
    fonts-noto \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

WORKDIR /app

# Install Python dependencies from pre-built wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy source code
COPY backend/ .

# Create directories for data and logs
RUN mkdir -p /logs /app/logs /app/data/uploads /app/data/artifacts

# Whisper model cache directory (mount as volume for persistence)
ENV HF_HOME=/models
RUN mkdir -p /models

# Mock-first images stay small and make no model download. A later local-only
# deployment can opt in with --build-arg PRELOAD_WHISPER_MODEL=large-v3-turbo.
ARG PRELOAD_WHISPER_MODEL=""
RUN if [ -n "$PRELOAD_WHISPER_MODEL" ]; then \
      python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['PRELOAD_WHISPER_MODEL'], device='cpu', compute_type='int8')"; \
    fi

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV GSP_MOCK_EXTERNAL_SERVICES=1
ENV GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0
ENV GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0

# Create symlink so 'backend.app' imports work (codebase uses mixed import styles)
RUN rm -rf /app/backend && ln -s /app /app/backend

# Drop root privileges for runtime.
# Cloud Run runs containers as root by default; use a dedicated unprivileged user instead.
RUN useradd --create-home --uid 10001 --user-group --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /logs /models /app/logs /app/data
USER appuser

# Default environment (override via Cloud Run env vars)
ENV APP_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

# Run migrations on startup, then launch the app
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
