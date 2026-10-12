"""Opt-in real Git/pipx outage proof with disposable installation and shell roots."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT: Path = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("SLO_MIRROR_INSTALL_E2E") != "1",
        reason="opt-in: requires network, real pipx, and GitHub read access while the mirror is private",
    ),
]


def _environment(*, root: Path, git: str) -> dict[str, str]:
    """Isolate writable roots and reject GitLab operations at the Git boundary.

    All other Git operations use the real executable, including the GitHub clone.
    Existing Git authentication is external; no credentials are put in URLs.

    Args:
        root: Disposable pytest-owned directory.
        git: Real Git executable to delegate non-GitLab operations to.

    Returns:
        Environment for real pipx installation and updater subprocesses.
    """
    bin_dir: Path = root / "bin"
    bin_dir.mkdir()
    wrapper: Path = bin_dir / "git"
    wrapper.write_text(
        '#!/bin/sh\ncase "$*" in\n'
        '  *gitlab.com/core-27/slo.git*) echo "simulated GitLab outage" >&2; exit 128 ;;\n'
        f'esac\nexec "{git}" "$@"\n'
    )
    wrapper.chmod(0o755)
    home: Path = root / "home"
    home.mkdir()
    retained = {
        "PATH",
        "LANG",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "GIT_ASKPASS",
        "SLO_MIRROR_TEST_TOKEN",
        "GIT_CONFIG_COUNT",
        "GIT_CONFIG_KEY_0",
        "GIT_CONFIG_VALUE_0",
    }
    environment = {
        name: value
        for name, value in os.environ.items()
        if name in retained or name.lower().endswith("_proxy")
    }
    environment.update(
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(root / "xdg-config"),
            "XDG_DATA_HOME": str(root / "xdg-data"),
            "XDG_CACHE_HOME": str(root / "xdg-cache"),
            "PIPX_HOME": str(root / "pipx-home"),
            "PIPX_BIN_DIR": str(root / "pipx-bin"),
            "PIPX_SHARED_LIBS": str(root / "pipx-shared"),
            "PIPX_DEFAULT_PYTHON": sys.executable,
            "PIPX_DEFAULT_BACKEND": "pip",
            "SLO_HOME": str(root / "slo-home"),
            "SLO_AUTO_VISUALIZE": "0",
            "GIT_TERMINAL_PROMPT": "0",
            "PYTHONPATH": str(ROOT),
            "PATH": f"{bin_dir}{os.pathsep}{root / 'pipx-bin'}{os.pathsep}{os.environ['PATH']}",
        }
    )
    return environment


def _run(*, argv: list[str], environment: dict[str, str], root: Path) -> str:
    """Run a bounded real installation command and retain failure diagnostics.

    Args:
        argv: Command argument vector, containing no credentials.
        environment: Isolated process environment.
        root: Disposable working directory.

    Returns:
        Combined process output for behavioral assertions.
    """
    result = subprocess.run(
        args=argv,
        env=environment,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    return output


def test_real_pipx_install_and_update_during_gitlab_outage(tmp_path: Path) -> None:
    """Install/update through real GitHub fetches without changing the host install."""
    git = shutil.which("git")
    assert git is not None and shutil.which("pipx") is not None
    assert sys.version_info[:2] == (3, 11)
    environment = _environment(root=tmp_path, git=git)
    ref = os.environ.get("SLO_MIRROR_E2E_REF", "main")
    environment["SLO_REF"] = ref
    # Only toolchain provisioning is outside this smoke: the real installer
    # functions fetch/build with pipx, then finalize launcher and shell defaults.
    install = _run(
        argv=[
            "bash",
            "-c",
            'source "$1"; slo_install; slo_finalize_isolated_launcher; slo_finalize_shell_environment',
            "mirror-smoke",
            str(ROOT / "install.sh"),
        ],
        environment=environment,
        root=tmp_path,
    )
    assert "primary repository inaccessible; trying the mirror" in install
    launcher = tmp_path / "pipx-bin" / "slo"
    assert "slo isolated launcher" in launcher.read_text()
    assert (tmp_path / "home" / ".slo" / "shell" / "environment.sh").is_file()
    _run(argv=[str(launcher), "--help"], environment=environment, root=tmp_path)
    # Run the updater-under-test, even before the feature is merged on GitHub.
    update = _run(
        argv=[sys.executable, "-m", "src.cli.update", "--ref", ref],
        environment=environment,
        root=tmp_path,
    )
    assert "primary repository inaccessible; trying the mirror" in update
    assert "slo isolated launcher" in launcher.read_text()
    _run(argv=[str(launcher), "--help"], environment=environment, root=tmp_path)
    release = _run(
        argv=[
            sys.executable,
            "-c",
            "from src.cli.update import Updater; print(Updater.resolve_latest_release_tag())",
        ],
        environment=environment,
        root=tmp_path,
    )
    assert "trying the mirror" in release
    assert any(line.startswith("v") for line in release.splitlines())
