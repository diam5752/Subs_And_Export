#!/usr/bin/env python3

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urlparse

import psycopg
from psycopg import sql

REPO_ROOT = Path(__file__).resolve().parents[2]
JAVA_GATE = REPO_ROOT / ".codex" / "scripts" / "run_java_gate.py"
DEFAULT_ADMIN_URL = "postgresql://gsp:gsp@127.0.0.1:5432/postgres"


def normalized_admin_url() -> str:
    value = os.environ.get("GSP_JAVA_TEST_ADMIN_DATABASE_URL", DEFAULT_ADMIN_URL).strip()
    return value.replace("postgresql+psycopg://", "postgresql://", 1)


def temporary_database_url(admin_url: str, database_name: str) -> str:
    parsed = urlparse(admin_url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
        raise ValueError("GSP_JAVA_TEST_ADMIN_DATABASE_URL must be a PostgreSQL URL with a host")

    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    port = parsed.port or 5432
    credentials = ""
    if parsed.username is not None:
        username = quote(unquote(parsed.username), safe="")
        password = quote(unquote(parsed.password or ""), safe="")
        credentials = f"{username}:{password}@"
    return f"postgresql://{credentials}{host}:{port}/{database_name}"


def drop_database(connection: psycopg.Connection[tuple[object, ...]], database_name: str) -> None:
    connection.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s",
        (database_name,),
    )
    connection.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))


def main() -> int:
    admin_url = normalized_admin_url()
    parsed = urlparse(admin_url)
    database_name = f"gsp_java_it_{os.getpid()}_{secrets.token_hex(4)}"

    try:
        connection = psycopg.connect(admin_url, autocommit=True)
    except psycopg.Error as exception:
        host = parsed.hostname or "unknown"
        port = parsed.port or 5432
        print(
            f"BLOCKED check:java: PostgreSQL is unavailable at {host}:{port}: {exception.__class__.__name__}",
            file=sys.stderr,
        )
        return 2

    with connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        environment = os.environ.copy()
        environment["GSP_JAVA_TEST_DATABASE_URL"] = temporary_database_url(admin_url, database_name)

        try:
            completed = subprocess.run(
                [sys.executable, str(JAVA_GATE), "./mvnw", "-B", "clean", "verify"],
                cwd=REPO_ROOT,
                env=environment,
                check=False,
            )
            return completed.returncode
        finally:
            drop_database(connection, database_name)


if __name__ == "__main__":
    raise SystemExit(main())
