FROM python:3.11-slim AS builder

# Install build dependencies for native packages (faster-whisper, etc.)
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY backend/requirements.txt .
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
RUN mkdir -p /data/uploads /data/artifacts /app/logs

# Whisper model cache directory (mount as volume for persistence)
ENV HF_HOME=/models
RUN mkdir -p /models

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Create symlink so 'backend.app' imports work (codebase uses mixed import styles)
RUN ln -s /app /app/backend

# Production settings
ENV APP_ENV=production

# Health check
# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

EXPOSE 8080

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
