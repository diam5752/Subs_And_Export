#!/bin/bash

# Function to handle cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping servers..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID
    fi
    exit
}

# Trap signals
trap cleanup SIGINT SIGTERM

echo "🚀 Starting Full Stack Environment..."

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "🐍 Activating virtual environment..."
    source venv/bin/activate
else
    echo "⚠️  No venv found in root. Assuming python/pip are in path or handled otherwise."
fi

echo "🧹 Killing old servers on ports 8080 and 3000..."
lsof -ti:8080 | xargs kill -9 2>/dev/null || true
lsof -ti:3000 | xargs kill -9 2>/dev/null || true


# Start Backend
echo "⚙️  Starting Backend (Port 8080)..."
# Load environment variables from .env
if [ -f ".env" ]; then
    echo "📄 Loading environment from .env..."
    set -a
    source .env
    set +a
fi
# Run as module from root so relative imports in main.py work
# Explicitly set APP_ENV=dev to enable dev routes
export APP_ENV=dev
uvicorn backend.main:app --reload --port 8080 &
BACKEND_PID=$!

# Start Frontend
echo "🎨 Starting Frontend (Port 3000)..."
cd frontend
npm run dev &
FRONTEND_PID=$!
cd ..

echo "✅ Servers are running!"
echo "   Backend: http://localhost:8080"
echo "   Frontend: http://localhost:3000"
echo "   Press Ctrl+C to stop both."

# Wait for processes
wait
