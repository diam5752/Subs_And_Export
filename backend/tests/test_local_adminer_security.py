from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
STARTUP = REPOSITORY_ROOT / ".codex/scripts/start_adminer.sh"


def test_local_database_viewer_uses_the_qualified_php_image_and_startup_guard() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.override.yml").read_text(encoding="utf-8")
    adminer = compose.split("  adminer:\n", 1)[1].split("\nvolumes:", 1)[0]

    assert "image: adminer:6.1.2@sha256:4e3a6514c26c625de2020c549d1eb24ddd2515f18311aa4bf32c823713c2f6fe" in adminer
    assert 'command: ["sh", "/usr/local/bin/gsubs-start-adminer.sh"]' in adminer
    assert "./.codex/scripts/start_adminer.sh:/usr/local/bin/gsubs-start-adminer.sh:ro" in adminer
    assert "ADMINER_DESIGN=hydra" in adminer
    assert "depends_on:\n      - db" in adminer


@pytest.mark.parametrize("check_exit", [0, 1, 126, 127])
def test_adminer_never_serves_http_after_a_failed_runtime_check(tmp_path: Path, check_exit: int) -> None:
    php = tmp_path / "php"
    php.write_text(
        '#!/bin/sh\nif [ "$1" = "-r" ]; then exit "$PHP_CHECK_EXIT"; fi\nprintf "%s\\n" "$@" > "$PHP_SERVER_CALL"\n',
        encoding="utf-8",
    )
    php.chmod(0o755)
    server_call = tmp_path / "server-call"

    result = subprocess.run(
        ["sh", str(STARTUP)],
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.defpath,
            "PHP_CHECK_EXIT": str(check_exit),
            "PHP_SERVER_CALL": str(server_call),
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    if check_exit:
        assert result.returncode != 0
        assert "Adminer blocked" in result.stderr
        assert not server_call.exists()
    else:
        assert result.returncode == 0
        assert server_call.read_text(encoding="utf-8").splitlines() == [
            "-S",
            "[::]:8080",
            "-t",
            "/var/www/html",
        ]
