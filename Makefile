.PHONY: install test lint run docker-up docker-down clean coverage coverage-frontend coverage-backend coverage-open

install:
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

test:
	@echo "Running backend tests..."
	cd backend && APP_ENV=dev pytest
	@echo "Running frontend tests..."
	cd frontend && npm test -- --watchAll=false

test-frontend:
	cd frontend && npm test -- --watchAll=false

test-backend:
	cd backend && APP_ENV=dev pytest

lint:
	@echo "Running ruff..."
	ruff check backend
	@echo "Running eslint..."
	cd frontend && npm run lint

coverage: coverage-backend coverage-frontend
	@echo "Coverage reports generated!"

coverage-frontend:
	@echo "Running frontend tests with coverage..."
	cd frontend && npm test -- --coverage --watchAll=false

coverage-backend:
	@echo "Running backend tests with coverage..."
	cd backend && APP_ENV=dev python3 -m pytest --cov=app --cov-report=html --cov-report=term

coverage-open:
	@echo "Opening coverage reports..."
	@if [ -f frontend/coverage/lcov-report/index.html ]; then open frontend/coverage/lcov-report/index.html; fi
	@if [ -f backend/htmlcov/index.html ]; then open backend/htmlcov/index.html; fi

run:
	@echo "Running backend locally..."
	cd backend && APP_ENV=dev uvicorn main:app --reload

docker-up:
	docker-compose up --build

docker-down:
	docker-compose down

# Database management
db-up:
	docker compose up -d db

db-down:
	docker compose stop db

db-create-test:
	@echo "Creating test database..."
	docker exec -it subs_and_export_project-db-1 psql -U gsp -d postgres -c "CREATE DATABASE gsp_test;" || true

migrate:
	cd backend && alembic upgrade head

migrate-test:
	cd backend && GSP_DATABASE_URL=postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test alembic upgrade head

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	rm -rf frontend/coverage backend/htmlcov
