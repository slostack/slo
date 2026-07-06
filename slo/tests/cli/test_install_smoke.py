"""Opt-in Docker smoke tests for the Linux installer path."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

INSTALL_SH: Path = Path(__file__).resolve().parents[2] / "install.sh"
IMAGES: list[str] = ["ubuntu:22.04", "ubuntu:24.04", "debian:11", "debian:12"]


def _docker_available() -> bool:
    """Return True when a usable docker CLI is on PATH.

    Returns:
        bool: Whether docker can be invoked for the smoke run.
    """
    return shutil.which("docker") is not None


def _require_deploy_token_env() -> None:
    """Fail loudly when the deploy-token credentials are absent from the environment.

    Checks the deploy-token env vars by NAME only so a missing credential produces
    a clear message without ever echoing the secret value into pytest output.

    Raises:
        Failed: If SLO_DEPLOY_TOKEN_USERNAME or SLO_DEPLOY_TOKEN is unset or empty.
    """
    missing: list[str] = [
        name
        for name in ("SLO_DEPLOY_TOKEN_USERNAME", "SLO_DEPLOY_TOKEN")
        if not os.environ.get(name)
    ]
    if missing:
        pytest.fail(f"missing required deploy-token env vars: {', '.join(missing)}")


@pytest.mark.skipif(
    os.environ.get("SLO_INSTALL_E2E") != "1" or not _docker_available(),
    reason="opt-in only: set SLO_INSTALL_E2E=1 and have Docker available",
)
@pytest.mark.parametrize("image", IMAGES)
def test_installer_bootstraps_and_runs(image: str) -> None:
    """Run install.sh in a bare distro image and assert ``slo --help`` works.

    Args:
        image (str): Docker base image to smoke-test.
    """
    _require_deploy_token_env()
    script: str = (
        "set -e; "
        "apt-get update && apt-get install -y curl ca-certificates; "
        "bash /src/install.sh; "
        "~/.local/bin/slo --help"
    )
    # Forward the deploy-token credentials by NAME only: docker reads each value
    # from this process's inherited environment (subprocess.run passes os.environ
    # through by default), so the secret never appears in the argv that pytest
    # would dump in the CompletedProcess repr on failure.
    env_flags: list[str] = ["-e", "SLO_DEPLOY_TOKEN_USERNAME", "-e", "SLO_DEPLOY_TOKEN"]
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{INSTALL_SH.parent}:/src",
            *env_flags,
            image,
            "bash",
            "-lc",
            script,
        ],
        capture_output=True,
        text=True,
        timeout=1800,
    )
    assert result.returncode == 0, result.stderr[-4000:]
    assert "usage" in result.stdout.lower() or "slo" in result.stdout.lower()
