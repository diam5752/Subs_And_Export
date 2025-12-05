"""
Thin wrapper around the shared database helpers.

The backend now reuses the ``greek_sub_publisher`` persistence layer so schema
and behavior stay consistent between the FastAPI API and the Streamlit UI.
"""
from greek_sub_publisher.database import Database, DatabaseSettings

__all__ = ["Database", "DatabaseSettings"]
