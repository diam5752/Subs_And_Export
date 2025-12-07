#!/bin/bash

# Kill all child processes when this script exits
trap "kill 0" EXIT

# Check if venv exists and activate it
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Warning: 'venv' directory not found. Assuming uvicorn is in PATH or global python."
fi

# Start Backend
echo "Starting Backend on http://localhost:8000..."
# Run from root so that imports like 'backend.main' work if needed, 
# or change dir to backend depending on how app is structured.
# Looking at main.py: "from .app.api.endpoints..." implies it's a package or running from root.
# Usually `uvicorn backend.main:app` works from root.
uvicorn backend.main:app --reload --port 8000 &

# Start Frontend
echo "Starting Frontend on http://localhost:3000..."
cd frontend
npm run dev
