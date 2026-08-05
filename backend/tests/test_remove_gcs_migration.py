"""Contract tests for removing the retired cloud-upload schema."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock


def test_remove_gcs_uploads_migration_drops_schema_without_restoring_it(monkeypatch) -> None:
    migration = importlib.import_module(
        "backend.alembic.versions.0021_remove_gcs_uploads",
    )
    operation = MagicMock()
    monkeypatch.setattr(migration, "op", operation)

    migration.upgrade()

    operation.drop_table.assert_called_once_with("gcs_uploads", if_exists=True)

    migration.downgrade()

    operation.create_table.assert_not_called()
    operation.create_index.assert_not_called()
