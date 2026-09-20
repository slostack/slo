"""Opt-in hermetic Docker smoke tests for the public Linux installer (spec 80).

Hermetic contract (80.a.2, M1): the repository source parent is mounted at
``/src:ro`` (read-only); the container copies ``/src/install.sh`` to a fresh
writable in-container temporary file **before each install run** and never
executes the mounted file directly. Every runtime root (HOME, XDG, pipx,
pyenv) is created in-container under a ``mktemp -d`` directory; no host home,
pipx root, profile, or output directory is mounted.

The assertions live in ``install_smoke_container.sh`` (mounted read-only
alongside the installer) so the container command stays a two-line bootstrap:
install prerequisites, then run the assertion script. The script proves the
managed environment file (0644, one marker pair, real ``INDEX.md`` under a
non-``~/.slo`` ``SLO_SKILLS_DIR``), fresh Bash/Zsh login and interactive
non-login shells, POSIX ``.profile`` fallback, explicit-override survival,
user-skill preservation with absent ``user_workflows``, and second-run
idempotency with a working ``slo --help``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

INSTALL_SH: Path = Path(__file__).resolve().parents[2] / "install.sh"
CONTAINER_SCRIPT: Path = Path(__file__).resolve().parent / "install_smoke_container.sh"
# debian:11 was dropped from the matrix in spec 80: its deb.debian.org
# bullseye-security index advertises point releases whose binary debs are 404
# on deb.debian.org, archive.debian.org, and snapshot.debian.org, while the
# image itself pre-installs those exact versions — every apt install that
# needs perl (git included) deadlocks on "held broken packages". The image is
# unrecoverable by any sources-list repair; debian:13 keeps a two-generation
# Debian matrix alongside the two Ubuntu LTS bases.
IMAGES: list[str] = ["ubuntu:22.04", "ubuntu:24.04", "debian:12", "debian:13"]


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
def test_installer_bootstraps_and_finalises_shell_environment(image: str) -> None:
    """Run the hermetic container smoke for one base image.

    Args:
        image (str): Docker base image to smoke-test.
    """
    assert CONTAINER_SCRIPT.is_file(), f"missing container script: {CONTAINER_SCRIPT}"
    bootstrap: str = (
        "set -e; "
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get update && apt-get install -y curl ca-certificates zsh; "
        "bash /src/tests/cli/install_smoke_container.sh"
    )
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{INSTALL_SH.parent}:/src:ro",
            image,
            "bash",
            "-lc",
            bootstrap,
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    assert result.returncode == 0, (
        f"container smoke failed on {image}:\n"
        f"--- stdout (tail) ---\n{result.stdout[-4000:]}\n"
        f"--- stderr (tail) ---\n{result.stderr[-4000:]}"
    )
    assert "SMOKE-OK" in result.stdout
