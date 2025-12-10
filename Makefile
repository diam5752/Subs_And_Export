.PHONY: install test lint run docker-up docker-down clean

install:
	@echo "Installing backend dependencies..."
	cd backend && pip install -r requirements.txt
	@echo "Installing frontend dependencies..."
	cd frontend && npm install

test:
	@echo "Running backend tests..."
	cd backend && pytest

lint:
	@echo "Running ruff..."
	ruff check backend

run:
	@echo "Running backend locally..."
	cd backend && uvicorn main:app --reload

docker-up:
	docker-compose up --build

docker-down:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
