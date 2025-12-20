#!/bin/bash

# Function to handle cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping servers..."
    if [ ! -z "$BACKEND_PID" ]; then
        kill $BACKEND_PID 2>/dev/null
    fi
    if [ ! -z "$FRONTEND_PID" ]; then
        kill $FRONTEND_PID 2>/dev/null
    fi
    if [ "$STARTED_DOCKER_DB" = "true" ]; then
        echo "🗄️  Stopping Docker database..."
        docker compose stop db 2>/dev/null
    fi
    exit
}

# Trap signals
trap cleanup SIGINT SIGTERM

echo "🚀 Starting Full Stack Environment..."

# Load environment variables from .env first (needed for DB connection)
if [ -f ".env" ]; then
    echo "📄 Loading environment from .env..."
    set -a
    source .env
    set +a
fi

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

# Check if database is reachable
STARTED_DOCKER_DB="false"
echo "🗄️  Checking database connection..."
if pg_isready -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-postgres}" >/dev/null 2>&1; then
    echo "✅ Database is already running!"
else
    echo "📦 Database not reachable, starting via Docker..."
    docker compose up -d db
    STARTED_DOCKER_DB="true"
    echo "⏳ Waiting for database to be ready..."
    sleep 3
    # Wait for postgres to be healthy
    for i in {1..30}; do
        if docker compose exec -T db pg_isready -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-gsp}" >/dev/null 2>&1; then
            echo "✅ Database is ready!"
            break
        fi
        if [ $i -eq 30 ]; then
            echo "❌ Database failed to start. Check 'docker compose logs db'"
            exit 1
        fi
        sleep 1
    done
fi

# Run database migrations
echo "🔄 Running database migrations..."
cd backend
alembic upgrade head
cd ..

# Start Backend
echo "⚙️  Starting Backend (Port 8080)..."
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
echo "   Press Ctrl+C to stop all."

# Wait for processes
wait
