FROM python:3.11-slim AS builder

WORKDIR /build
ARG REQUIREMENTS_FILE=backend/requirements.mock.txt
COPY ${REQUIREMENTS_FILE} requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# ============================================
FROM python:3.11-slim AS runtime

# Install runtime system dependencies
# - ffmpeg: video/audio processing
# - fonts-*: subtitle text rendering (Greek support)
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-dejavu-core \
    fonts-noto-core \
    fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

WORKDIR /app

# Install Python dependencies from pre-built wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

# Copy source code
COPY backend/ .
COPY gsubs-logo.png /gsubs-logo.png

# Git can materialize non-executable files as mode 0600 when a release checkout
# is created under a restrictive umask. Normalize only immutable runtime source
# and the public watermark before dropping privileges; persistent data and
# secret mounts retain their separately enforced private modes.
RUN chmod -R a=rX,u+w /app \
    && chmod 0644 /gsubs-logo.png

# Create the only persistent runtime directories used by this image.
RUN mkdir -p /data/uploads /data/artifacts /privacy-erasure-journal

# Whisper model cache directory (mount as volume for persistence)
ENV HF_HOME=/models
RUN mkdir -p /models

# Provider-minimal images stay small and make no model download. A local-only
# deployment can opt in with --build-arg PRELOAD_WHISPER_MODEL=large-v3-turbo.
ARG PRELOAD_WHISPER_MODEL=""
RUN if [ -n "$PRELOAD_WHISPER_MODEL" ]; then \
      python -c "import os; from faster_whisper import WhisperModel; WhisperModel(os.environ['PRELOAD_WHISPER_MODEL'], device='cpu', compute_type='int8')"; \
    fi

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV GSP_MOCK_EXTERNAL_SERVICES=1
ENV GSP_ELEVENLABS_ENABLED=0
ENV GSP_EXTERNAL_PROVIDER_MONTHLY_BUDGET_USD=0
ENV GSP_EXTERNAL_PROVIDER_PER_REQUEST_BUDGET_USD=0

# The image copies the backend package contents into /app; expose the canonical
# `backend.*` package path without maintaining a second source tree.
RUN rm -rf /app/backend && ln -s /app /app/backend

# Drop root privileges for runtime.
# Run the API with a dedicated unprivileged user.
RUN useradd --create-home --uid 10001 --user-group --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /data /models /privacy-erasure-journal
USER appuser

# Default environment (overridden by the production Compose environment).
ENV APP_ENV=production

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

# Run migrations on startup, then launch the app
CMD ["sh", "-c", "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
