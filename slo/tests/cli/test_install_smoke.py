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
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[2]
INSTALL_SH: Path = REPOSITORY_ROOT / "install.sh"
CONTAINER_SCRIPT: Path = Path(__file__).resolve().parent / "install_smoke_container.sh"
# debian:11 was dropped from the matrix in spec 80: its deb.debian.org
# bullseye-security index advertises point releases whose binary debs are 404
# on deb.debian.org, archive.debian.org, and snapshot.debian.org, while the
# image itself pre-installs those exact versions — every apt install that
# needs perl (git included) deadlocks on "held broken packages". The image is
# unrecoverable by any sources-list repair; debian:13 keeps a two-generation
# Debian matrix alongside the two Ubuntu LTS bases.
IMAGES: list[str] = ["ubuntu:22.04", "ubuntu:24.04", "debian:12", "debian:13"]


def _selected_images() -> list[str]:
    """Return the full documented matrix or one CI-assigned supported image.

    Returns:
        list[str]: All supported images locally, or the validated image assigned
            through ``SLO_INSTALL_SMOKE_IMAGE`` by the GitLab matrix.

    Raises:
        ValueError: If CI assigns an image outside the documented smoke matrix.
    """
    assigned_image: str = os.environ.get("SLO_INSTALL_SMOKE_IMAGE", "")
    if not assigned_image:
        return IMAGES
    if assigned_image not in IMAGES:
        raise ValueError(f"SLO_INSTALL_SMOKE_IMAGE is unsupported: {assigned_image}")
    return [assigned_image]


def _installer_environment_args() -> list[str]:
    """Pin nested release installs without changing ordinary local defaults.

    The matrix image assignment identifies release mode even if its tag is
    missing. Docker does not inherit parent variables; pass captured values as
    argv data and clear the installer's higher-precedence SLO_VERSION override.

    Returns:
        list[str]: Explicit Docker environment arguments, or none locally.

    Raises:
        ValueError: If release mode has no valid immutable version tag.
    """
    tag: str = os.environ.get("CI_COMMIT_TAG", "")
    if not tag and not os.environ.get("SLO_INSTALL_SMOKE_IMAGE", ""):
        return []
    if re.fullmatch(pattern=r"v[0-9]+\.[0-9]+\.[0-9]+", string=tag) is None:
        raise ValueError("CI_COMMIT_TAG must be an immutable vMAJOR.MINOR.PATCH tag")
    return ["--env", f"CI_COMMIT_TAG={tag}", "--env", f"SLO_REF={tag}", "--env", "SLO_VERSION="]


def _require_docker_for_requested_e2e() -> str:
    """Return Docker's executable path or fail an explicitly requested E2E run.

    Returns:
        str: Docker executable path.
    """
    docker: str | None = shutil.which("docker")
    if docker is None:
        pytest.fail("SLO_INSTALL_E2E=1 requires a usable docker executable on PATH")
    return docker


def test_requested_e2e_fails_when_docker_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit E2E request cannot silently downgrade to a skip without Docker."""
    monkeypatch.setattr(shutil, "which", lambda _: None)

    with pytest.raises(pytest.fail.Exception, match="SLO_INSTALL_E2E=1 requires"):
        _require_docker_for_requested_e2e()


@pytest.mark.skipif(
    os.environ.get("SLO_INSTALL_E2E") != "1",
    reason="opt-in only: set SLO_INSTALL_E2E=1",
)
@pytest.mark.parametrize("image", _selected_images())
def test_installer_bootstraps_and_finalises_shell_environment(image: str) -> None:
    """Run the hermetic container smoke for one base image.

    Args:
        image (str): Docker base image to smoke-test.
    """
    assert CONTAINER_SCRIPT.is_file(), f"missing container script: {CONTAINER_SCRIPT}"
    installer_environment: list[str] = _installer_environment_args()
    docker: str = _require_docker_for_requested_e2e()
    bootstrap: str = (
        "set -e; "
        "export DEBIAN_FRONTEND=noninteractive; "
        "apt-get update && apt-get install -y curl ca-certificates zsh; "
        "bash /src/slo/tests/cli/install_smoke_container.sh"
    )
    result = subprocess.run(
        [
            docker,
            "run",
            "--rm",
            *installer_environment,
            "-v",
            f"{REPOSITORY_ROOT.parent}:/src:ro",
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


@pytest.mark.skipif(
    os.environ.get("SLO_PLATFORM_SMOKE") != "macos",
    reason="macOS runner-only evidence: set SLO_PLATFORM_SMOKE=macos on macOS",
)
def test_macos_runner_contract_requires_a_real_macos_host() -> None:
    """Refuse fictional macOS evidence when this command runs on another platform."""
    assert sys.platform == "darwin", "SLO_PLATFORM_SMOKE=macos must run on a real macOS runner"
    assert os.environ.get("SLO_RELEASE_TAG", "").startswith("v")
    assert os.environ.get("SLO_INSTALL_URL", "").startswith("https://")
