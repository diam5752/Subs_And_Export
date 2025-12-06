"""
Thin wrapper around the shared database helpers to keep backend persistence
consistent with the core package.
"""
from greek_sub_publisher.database import Database, DatabaseSettings

__all__ = ["Database", "DatabaseSettings"]
