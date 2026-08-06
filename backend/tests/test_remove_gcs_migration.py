"""Contract tests for removing the retired cloud-upload schema."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest


def _migration_with_counts(
    monkeypatch,
    *,
    upload_rows: int,
    job_references: int,
    legacy_table_exists: bool = True,
):
    migration = importlib.import_module(
        "backend.alembic.versions.0021_remove_gcs_uploads",
    )
    operation = MagicMock()
    connection = MagicMock()
    table_result = MagicMock()
    table_result.scalar_one.return_value = legacy_table_exists
    job_result = MagicMock()
    job_result.scalar_one.return_value = job_references
    query_results = [table_result]
    if legacy_table_exists:
        upload_result = MagicMock()
        upload_result.scalar_one.return_value = upload_rows
        query_results.append(upload_result)
    query_results.append(job_result)
    connection.execute.side_effect = query_results
    operation.get_bind.return_value = connection
    monkeypatch.setattr(migration, "op", operation)

    return migration, operation, connection


def test_remove_gcs_uploads_migration_drops_only_empty_legacy_schema(monkeypatch) -> None:
    migration, operation, connection = _migration_with_counts(
        monkeypatch,
        upload_rows=0,
        job_references=0,
    )

    migration.upgrade()

    assert connection.execute.call_count == 3
    operation.drop_table.assert_called_once_with("gcs_uploads", if_exists=True)

    migration.downgrade()

    operation.create_table.assert_not_called()
    operation.create_index.assert_not_called()


def test_remove_gcs_uploads_migration_is_reentrant_after_safe_downgrade(
    monkeypatch,
) -> None:
    migration, operation, connection = _migration_with_counts(
        monkeypatch,
        upload_rows=0,
        job_references=0,
        legacy_table_exists=False,
    )

    # Downgrade deliberately does not recreate retired cloud-upload state, so
    # a later re-upgrade must still validate job evidence and remain safe.
    migration.upgrade()

    assert connection.execute.call_count == 2
    operation.drop_table.assert_called_once_with("gcs_uploads", if_exists=True)


@pytest.mark.parametrize(
    ("upload_rows", "job_references"),
    ((1, 0), (0, 1), (2, 3)),
)
def test_remove_gcs_uploads_migration_preserves_legacy_deletion_evidence(
    monkeypatch,
    upload_rows: int,
    job_references: int,
) -> None:
    # REGRESSION: the first retirement migration discarded object mappings
    # before legacy provider media had been proven absent or deleted.
    migration, operation, _connection = _migration_with_counts(
        monkeypatch,
        upload_rows=upload_rows,
        job_references=job_references,
    )

    with pytest.raises(RuntimeError, match="legacy GCS object references remain"):
        migration.upgrade()

    operation.drop_table.assert_not_called()
