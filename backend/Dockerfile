FROM python:3.11-slim

# Install system dependencies
# ffmpeg is required for video processing
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY backend/ .

# Create data directories
RUN mkdir -p /data/uploads /data/artifacts /app/logs

# Set environment variables
ENV PYTHONPATH=/app
ENV PROJECT_ROOT=/app/app
# Override config for data dir usually, but our code uses relative paths to PROJECT_ROOT.parent.parent
# In container:
# PROJECT_ROOT = /app/app/core (after config.py change)
# .parent = /app/app
# .parent.parent = /app
# So /data will be sibling? Wait.
# Code: DATA_DIR = config.PROJECT_ROOT.parent / "data" -> /app/data
# But we usually mount volumes at /data.
# In videos.py: data_dir = config.PROJECT_ROOT.parent / "data"
# If PROJECT_ROOT is /app/app (from my manual set in config.py pointing to .parent.parent from core/config.py)
# Wait, I set `PROJECT_ROOT = Path(__file__).resolve().parent.parent` in `core/config.py`.
# `core/config.py` is in `/app/app/core`.
# .parent = `/app/app`.
# .parent.parent = `/app`.
# So PROJECT_ROOT = `/app`.
# videos.py says `data_dir = config.PROJECT_ROOT.parent / "data"` -> `/app/../data` -> `/data`.
# This is perfect for Docker which mounts at /data.

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
