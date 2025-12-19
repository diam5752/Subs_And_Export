import pytest
from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.errors import (
    sanitize_message,
    register_exception_handlers
)

# Setup a dummy app for testing handlers
dummy_app = FastAPI()
register_exception_handlers(dummy_app)

class MockModel(BaseModel):
    name: str = Field(..., max_length=5)

@dummy_app.get("/error/http")
async def trigger_http_error():
    raise HTTPException(status_code=403, detail="Access to /app/secret denied")

@dummy_app.post("/error/validation")
async def trigger_validation_error(model: MockModel):
    return model

@dummy_app.get("/error/db")
async def trigger_db_error():
    raise SQLAlchemyError("Duplicate entry for /home/db/data")

@dummy_app.get("/error/unhandled")
async def trigger_unhandled_error():
    raise Exception("Something went wrong at /var/log/crash")

client = TestClient(dummy_app, raise_server_exceptions=False)

def test_sanitize_message_strips_internal_paths():
    """Test that internal paths are replaced with [INTERNAL_PATH]."""
    msg = "Error opening file /app/backend/data/uploads/123.mp4"
    sanitized = sanitize_message(msg)
    assert "[INTERNAL_PATH]" in sanitized
    assert "/app/backend/data" not in sanitized

    msg2 = "Permission denied: /home/user/project/file.txt"
    sanitized2 = sanitize_message(msg2)
    assert "[INTERNAL_PATH]" in sanitized2
    assert "/home/user" not in sanitized2

def test_http_exception_handler_sanitizes():
    """Test that explicit HTTP exceptions are sanitized."""
    response = client.get("/error/http")
    assert response.status_code == 403
    assert "[INTERNAL_PATH]" in response.json()["detail"]
    assert "/app/secret" not in response.json()["detail"]

def test_validation_exception_handler():
    """Test that validation errors are returned in a clean format."""
    response = client.post("/error/validation", json={"name": "too_long_name"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "Validation Error" in detail
    assert "body.name" in detail

def test_database_exception_handler():
    """Test that database errors return generic messages and error codes."""
    response = client.get("/error/db")
    assert response.status_code == 500
    data = response.json()
    assert data["code"] == "DB_ERROR"
    assert "Please try again later" in data["detail"]
    assert "/home/db/data" not in data["detail"]

def test_global_exception_handler():
    """Test that unhandled exceptions return generic messages and error codes."""
    response = client.get("/error/unhandled")
    assert response.status_code == 500
    data = response.json()
    assert data["code"] == "INTERNAL_ERROR"
    assert "An internal server error occurred" in data["detail"]
    assert "/var/log/crash" not in data["detail"]
