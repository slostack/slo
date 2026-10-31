"""Offline release-source contracts at the Docker argv and nested installer boundary."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SMOKE_PATH = Path(__file__).with_name("test_install_smoke.py")
SPEC = importlib.util.spec_from_file_location("installer_smoke", SMOKE_PATH)
assert SPEC is not None and SPEC.loader is not None
SMOKE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SMOKE)


@pytest.mark.parametrize("tag", ["v0.3.1", "v12.34.56"])
def test_docker_forwards_tag_and_both_installs_resolve_it(tmp_path: Path, tag: str) -> None:
    """Capture actual Docker argv, then exercise both calls with real ref resolution."""
    docker = tmp_path / "docker"
    capture = tmp_path / "argv.json"
    docker.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))\n"
        "print('SMOKE-OK')\n"
    )
    docker.chmod(0o700)
    environment = {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "CAPTURE": str(capture),
        "CI_COMMIT_TAG": tag,
        "SLO_VERSION": "dev",
        "SLO_REF": "wrong",
        "SLO_INSTALL_SMOKE_IMAGE": "debian:13",
    }
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            patch.delenv(name)
        for name, value in environment.items():
            patch.setenv(name, value)
        SMOKE.test_installer_bootstraps_and_finalises_shell_environment(image="debian:13")
    argv = json.loads(capture.read_text())
    assert f"CI_COMMIT_TAG={tag}" in argv
    assert f"SLO_REF={tag}" in argv
    assert "SLO_VERSION=" in argv
    assert argv[-4:-1] == ["debian:13", "bash", "-lc"]
    assert tag not in argv[-1]  # Identity is data, never shell program text.
    assert f"{SMOKE.REPOSITORY_ROOT.parent}:/src:ro" in argv

    script = SMOKE.CONTAINER_SCRIPT.read_text()
    installer_function = script.split("run_public_installer() {", 1)[1].split("\n}", 1)[0]
    # Only this source path is substituted; all writes remain in tmp_path.
    installer_function = installer_function.replace("/src/slo/install.sh", str(SMOKE.INSTALL_SH))
    installer_function = installer_function.replace("/tmp/slo-install.", f"{tmp_path}/slo-install.")
    program = (
        "set -euo pipefail\n"
        'bash() { ( source "$1"; printf \'%s\\n\' "$SLO_REF"; ); }\n'
        "run_public_installer() {" + installer_function + "\n}\n"
        "run_public_installer\nrun_public_installer\n"
    )
    forwarded = dict(argument.split("=", 1) for argument in argv if "=" in argument)
    result = subprocess.run(
        args=["/bin/bash", "-c", program],
        env={"PATH": "/usr/bin:/bin", **forwarded},
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.splitlines() == [tag, tag]


@pytest.mark.parametrize("tag", ["", "main", "v0.3.1;touch /tmp/injected", "$(id)", "v0.3.1\n", "-v0.3.1"])
def test_release_matrix_rejects_missing_or_invalid_tag(tag: str) -> None:
    """An assigned release image cannot silently install main or shell input."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "environ", {"CI_COMMIT_TAG": tag, "SLO_INSTALL_SMOKE_IMAGE": "debian:13"})
        with pytest.raises(ValueError, match="CI_COMMIT_TAG"):
            SMOKE._installer_environment_args()


def test_local_smoke_retains_installer_default() -> None:
    """Ordinary local invocations still use the raw installer's main default."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "environ", {})
        assert SMOKE._installer_environment_args() == []
