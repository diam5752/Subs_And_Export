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

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	rm -rf frontend/coverage backend/htmlcov
