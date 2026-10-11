"""One subprocess seam for frozen released Slo on each test's synthetic state."""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict

RELEASED_TAG: str = "v0.20.1"
REPOSITORY_ROOT: Path = Path(__file__).resolve().parents[3]


class ReleasedRunDAO(BaseModel):
    """Exit status, complete diagnostics and the final JSON report of a released step."""

    model_config = ConfigDict(frozen=True)
    returncode: int
    stdout: str
    stderr: str
    result: dict[str, object]


def run_released_slo(
    *, source: Path, slo_home: Path, script: str, extra_env: Optional[dict[str, str]] = None
) -> ReleasedRunDAO:
    """Run a frozen program against the new code's per-test state, then reap it.

    WHO: Compatibility tests call this for each released half of an alternating
    sequence. Only COMPAT_* script inputs are accepted; no inherited state or
    credential environment reaches the process. Writes stay beneath slo_home.

    Args:
        source (Path): Extracted released source directory.
        slo_home (Path): Fixture-owned, resolved state root.
        script (str): Released-side Python program.
        extra_env (Optional[dict[str, str]]): COMPAT_* inputs. Defaults to None.

    Returns:
        ReleasedRunDAO: Actual exit, diagnostics, and final JSON object if printed.
    """
    assert slo_home.is_absolute() and slo_home.resolve() == slo_home
    inputs = extra_env or {}
    assert all(name.startswith("COMPAT_") for name in inputs)
    directories = {name: slo_home / name for name in ("released-home", "released-workdir", "released-tmp")}
    for directory in directories.values():
        assert directory.resolve().is_relative_to(slo_home)
        directory.mkdir(exist_ok=True)
    environment = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(directories["released-home"]),
        "SLO_HOME": str(slo_home),
        "SLO_AUTH_FILE": str(slo_home / "global/authentication.json"),
        "TMPDIR": str(directories["released-tmp"]),
        "SLO_ENV": "test",
        "SLO_LOG_FORMAT": "text",
        "SLO_AUTO_VISUALIZE": "0",
        "SLO_PLUGINS_DISABLED": "1",
        "SLO_DEFAULT_MODEL_NAME": "gpt-5.4",
        "PYTHONPATH": str(source),
        "PYTHONDONTWRITEBYTECODE": "1",
        **inputs,
    }
    completed = subprocess.run(
        args=[sys.executable, "-B", "-c", script],
        env=environment,
        cwd=directories["released-workdir"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    lines = completed.stdout.strip().splitlines()
    return ReleasedRunDAO(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        result=json.loads(lines[-1]) if lines else {},
    )
