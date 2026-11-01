"""Execute the Linux CI pipx bootstrap across the disposable HOME boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

CI_FILE: Path = Path(__file__).resolve().parents[3] / ".gitlab-ci.yml"


@pytest.mark.parametrize(
    "job_name", [".release-e2e", "release-docker-installer-matrix", ".hosted-installer-smoke"]
)
def test_ci_pipx_runs_when_smoke_changes_home(tmp_path: Path, job_name: str) -> None:
    """Run actual CI tool provisioning, then query pipx with a different HOME.

    Args:
        tmp_path: Sole writable root for the tool, cache and both home directories.
        job_name: Linux CI owner whose bootstrap is executed without Poetry or Docker.
    """
    pipeline = yaml.safe_load(CI_FILE.read_text())
    commands: list[str] = pipeline[job_name]["before_script"]
    bootstrap: list[str] = [
        command for command in commands if "pipx" in command or command.startswith("export PATH=")
    ]
    original_home: Path = tmp_path / "bootstrap-home"
    smoke_home: Path = tmp_path / "smoke-home"
    original_home.mkdir()
    smoke_home.mkdir()
    # Do not inherit pip target/user-base overrides or developer credentials.
    environment: dict[str, str] = {
        "HOME": str(original_home),
        "PATH": f"{Path(sys._base_executable).parent}{os.pathsep}/usr/bin:/bin",  # type: ignore[attr-defined]
        "CI_PROJECT_DIR": str(tmp_path),
        "PIP_CACHE_DIR": str(tmp_path / "cache"),
        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIPX_HOME": str(tmp_path / "pipx-home"),
        "PIPX_BIN_DIR": str(tmp_path / "pipx-bin"),
        "SMOKE_HOME": str(smoke_home),
    }
    script: str = "\n".join(
        [
            "set -eu",
            *bootstrap,
            'export HOME="$SMOKE_HOME"',
            "pipx --version",
            'test "$(pipx environment --value PIPX_HOME)" = "$PIPX_HOME"',
        ]
    )
    result: subprocess.CompletedProcess[str] = subprocess.run(
        args=["/bin/bash", "-c", script],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
