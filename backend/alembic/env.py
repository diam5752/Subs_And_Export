from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

try:
    from backend.app.db import models as _models  # noqa: F401  # ensure models are registered
    from backend.app.db.base import Base
except ModuleNotFoundError:  # pragma: no cover
    from app.db import models as _models  # noqa: F401  # ensure models are registered
    from app.db.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
alembic_config = context.config

# Interpret the config file for Python logging.
if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    env_url = os.getenv("GSP_DATABASE_URL")
    if not env_url:
        raise RuntimeError(
            "GSP_DATABASE_URL environment variable is required for migrations. "
            "Set it to your PostgreSQL connection string, e.g.: "
            "postgresql+psycopg://user:pass@localhost:5432/dbname"
        )
    if not env_url.startswith("postgresql"):
        raise RuntimeError(
            f"Only PostgreSQL is supported. Got: {env_url.split('://')[0]}. "
            "Please set GSP_DATABASE_URL to a PostgreSQL connection string."
        )
    return env_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    configuration = alembic_config.get_section(alembic_config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _resolve_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
