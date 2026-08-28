"""Direct upgrade/downgrade contracts for the Beta login promotion schema."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import sql
from sqlalchemy.engine import make_url


def _run_alembic(
    database_url: str,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["alembic", *arguments],
        cwd=os.path.dirname(os.path.dirname(__file__)),
        env={**os.environ, "GSP_DATABASE_URL": database_url},
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )


@contextmanager
def _isolated_database() -> Iterator[tuple[str, str]]:
    configured_url = make_url(
        os.environ.get(
            "GSP_DATABASE_URL",
            "postgresql+psycopg://gsp:gsp@localhost:5432/gsp_test",
        )
    )
    database_name = f"gsp_beta_promo_{uuid.uuid4().hex[:12]}"
    admin_url = configured_url.set(
        drivername="postgresql",
        database="postgres",
    ).render_as_string(hide_password=False)
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(database_name),
                )
            )
    except psycopg.errors.InsufficientPrivilege:
        pytest.skip("Database role cannot create the isolated migration database")

    database_url = configured_url.set(
        database=database_name,
    ).render_as_string(hide_password=False)
    connection_url = configured_url.set(
        drivername="postgresql",
        database=database_name,
    ).render_as_string(hide_password=False)
    try:
        yield database_url, connection_url
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s
                  AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(database_name),
                )
            )


def test_beta_login_promotion_downgrades_only_before_any_slot_is_awarded() -> None:
    with _isolated_database() as (database_url, connection_url):
        upgraded = _run_alembic(database_url, "upgrade", "head")
        assert upgraded.returncode == 0, upgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                """
                SELECT max_claims, credit_amount, claimed_count
                FROM credit_promotion_campaigns
                WHERE id = 'beta_first_20_logins_v1'
                """
            ).fetchone() == (50, 30, 0)

        clean_downgrade = _run_alembic(
            database_url,
            "downgrade",
            "0022_cancelling_job_status",
        )
        assert clean_downgrade.returncode == 0, clean_downgrade.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT to_regclass('public.credit_promotion_campaigns')"
            ).fetchone() == (None,)

        reupgraded = _run_alembic(database_url, "upgrade", "head")
        assert reupgraded.returncode == 0, reupgraded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            # A persistent ordinal covers the account-deletion case where the
            # personal claim and ledger rows have already been erased.
            connection.execute(
                """
                UPDATE credit_promotion_campaigns
                SET claimed_count = 1
                WHERE id = 'beta_first_20_logins_v1'
                """
            )

        refused = _run_alembic(
            database_url,
            "downgrade",
            "0022_cancelling_job_status",
        )
        assert refused.returncode != 0
        assert (
            "Cannot downgrade the Beta login promotion after any campaign "
            "slot was awarded."
        ) in refused.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0025_expand_beta_login_promotion",)
            assert connection.execute(
                """
                SELECT claimed_count
                FROM credit_promotion_campaigns
                WHERE id = 'beta_first_20_logins_v1'
                """
            ).fetchone() == (1,)


def test_beta_login_promotion_expands_in_place_and_refuses_unsafe_rollback() -> None:
    with _isolated_database() as (database_url, connection_url):
        original = _run_alembic(
            database_url,
            "upgrade",
            "0024_product_feedback",
        )
        assert original.returncode == 0, original.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            connection.execute(
                """
                UPDATE credit_promotion_campaigns
                SET claimed_count = 20
                WHERE id = 'beta_first_20_logins_v1'
                """
            )

        expanded = _run_alembic(database_url, "upgrade", "head")
        assert expanded.returncode == 0, expanded.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                """
                SELECT max_claims, credit_amount, claimed_count
                FROM credit_promotion_campaigns
                WHERE id = 'beta_first_20_logins_v1'
                """
            ).fetchone() == (50, 30, 20)
            connection.execute(
                """
                UPDATE credit_promotion_campaigns
                SET claimed_count = 21
                WHERE id = 'beta_first_20_logins_v1'
                """
            )

        refused = _run_alembic(
            database_url,
            "downgrade",
            "0024_product_feedback",
        )
        assert refused.returncode != 0
        assert "more than 20 campaign slots were awarded" in refused.stderr
        with psycopg.connect(connection_url, autocommit=True) as connection:
            assert connection.execute(
                "SELECT version_num FROM alembic_version"
            ).fetchone() == ("0025_expand_beta_login_promotion",)
            assert connection.execute(
                """
                SELECT max_claims, claimed_count
                FROM credit_promotion_campaigns
                WHERE id = 'beta_first_20_logins_v1'
                """
            ).fetchone() == (50, 21)
