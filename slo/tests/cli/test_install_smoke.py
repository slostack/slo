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
    script: str = (
        "set -e; "
        "apt-get update && apt-get install -y curl ca-certificates; "
        "bash /src/install.sh; "
        "~/.local/bin/slo --help"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{INSTALL_SH.parent}:/src",
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
