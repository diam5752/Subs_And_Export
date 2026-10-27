from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


def render_compose(root: Path, relative: str, values: dict[str, str]) -> subprocess.CompletedProcess[str]:
    if shutil.which("docker") is None:
        pytest.skip("Docker Compose is required for the deployment contract check")
    environment = {key: value for key, value in os.environ.items() if key != "POSTGRES_IMAGE"}
    environment.update(values)
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "-f",
            relative,
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = "deploy/hetzner/docker-compose.production.yml"
IMAGE = "sha256:8ffedfbad54433138b8fb59d5dab4118bafb2449d04805657c78d44278d59da4"
VALUES = {
    "SUBFRAME_ENV_FILE": "/dev/null",
    "SUBFRAME_FEEDBACK_API_ENV_FILE": "/dev/null",
    "SUBFRAME_FEEDBACK_WORKER_ENV_FILE": "/dev/null",
    "SUBFRAME_RELEASE_SHA": "a" * 40,
    "GSP_OBSERVABILITY_ADMIN_USER_IDS": "contract-check",
    "ELEVENLABS_API_KEY": "contract-check-no-provider-call",
    "CADDY_IMAGE": "caddy-config-check:local",
}


@pytest.mark.parametrize("supplied", [None, ""])
def test_production_database_requires_an_explicit_image(supplied: str | None) -> None:
    values = dict(VALUES)
    if supplied is not None:
        values["POSTGRES_IMAGE"] = supplied
    result = render_compose(ROOT, COMPOSE, values)
    assert result.returncode != 0
    assert "POSTGRES_IMAGE" in result.stderr


def test_production_database_pin_preserves_the_canonical_volume() -> None:
    result = render_compose(ROOT, COMPOSE, dict(VALUES, POSTGRES_IMAGE=IMAGE))
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config["services"]["db"]["image"] == IMAGE
    mount = config["services"]["db"]["volumes"][0]
    assert mount["target"] == "/var/lib/postgresql/data"
    assert config["volumes"][mount["source"]]["name"] == "subframe-postgres-data"
