"""Shared SQLAlchemy column types for ORM model modules."""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import JSON

JSON_VALUE = JSON().with_variant(JSONB, "postgresql")
