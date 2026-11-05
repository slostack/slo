"""Behavioral coverage of interpreter isolation at every agent launch boundary."""

from __future__ import annotations

import json
import os
import subprocess
import shutil
import sys
import venv
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.agents.slo_agent.orchestrator.launch_tool import _build_argv
from src.agents.slo_agent.orchestrator.relaunch import WorkflowRelauncher
from src.agents.slo_agent.orchestrator.spawn_env import build_headless_child_env
from tests.agents.slo_agent.orchestrator.test_process import _make_process
from tests.agents.slo_agent.orchestrator.test_relaunch import _build_handle


def _launch_argv(*, launch: str) -> list[str]:
    """Return the actual production command for each supported launch boundary."""
    if launch == "sub-agent":
        process, _ = _make_process()
        return process._build_argv()
    if launch == "workflow":
        return _build_argv(
            brief="test isolation",
            orchestrator_session_id="orchestrator-1",
            owner_session_id="owner-1",
            model=None,
            cwd="/workspace",
        )
    return WorkflowRelauncher._build_argv(handle=_build_handle())


@pytest.fixture(scope="module")
def installed_python(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """Install this checkout's wheel offline into a disposable interpreter.

    The default launch contract requires installation; the pytest interpreter
    may intentionally be source-only. Never modify that interpreter or pipx.
    System site packages supply existing dependencies, not the Slo source.
    """
    root: Path = Path(__file__).resolve().parents[4]
    with TemporaryDirectory(prefix="installed-launch-", dir=tmp_path_factory.getbasetemp()) as directory:
        yield _install_checkout(root=root, temporary=Path(directory))


def _install_checkout(*, root: Path, temporary: Path) -> Path:
    """Build and install only the local wheel; never fetch dependencies or alter the parent."""
    source: Path = temporary / "source"
    source.mkdir()
    for name in ("src", "config"):
        shutil.copytree(src=root / name, dst=source / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "install.sh"):
        shutil.copyfile(src=root / name, dst=source / name)
    subprocess.run(
        args=[sys.executable, "-c", "from poetry.core.masonry.api import build_wheel; build_wheel('dist')"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    environment: Path = temporary / "venv"
    venv.EnvBuilder(system_site_packages=True, with_pip=False).create(env_dir=environment)
    interpreter: Path = environment / "bin" / "python"
    subprocess.run(
        args=[
            sys.executable,
            "-m",
            "pip",
            "--python",
            str(interpreter),
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            str(next((source / "dist").glob("*.whl"))),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return interpreter


@pytest.mark.parametrize("launch", ["sub-agent", "workflow", "resume"])
def test_agent_isolation_does_not_isolate_project_commands(
    tmp_path: Path, launch: str, installed_python: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real Python ignores hostile agent imports but project commands can set PYTHONPATH.

    Exercise the production interpreter prefix with a finite probe instead of
    starting an LLM session. Retain hostile environment values deliberately to
    prove isolation independently of the environment allowlist.
    """
    monkeypatch.delenv(name="SLO_DEV_MODE", raising=False)
    hostile: Path = tmp_path / "hostile"
    hostile.mkdir()
    for directory in (tmp_path, hostile):
        package: Path = directory / "src"
        package.mkdir()
        (package / "__init__.py").write_text("raise RuntimeError('hostile src imported')\n")
    (hostile / "project_probe.py").write_text("VALUE = 'project-import-ok'\n")
    argv: list[str] = _launch_argv(launch=launch)
    prefix: list[str] = argv[: argv.index("-m")]
    assert prefix == [sys.executable, "-I"]
    # Run the unchanged production flags in the explicitly installed fixture.
    # The source-only parent interpreter contract is checked above, not patched.
    prefix = [str(installed_python), *prefix[1:]]
    script: str = """
import importlib.util, json, os, subprocess, sys
spec = importlib.util.find_spec('src')
project_env = dict(os.environ)
project_env.pop('PYTHONHOME', None)
project = subprocess.run(
    [sys.executable, '-c', 'import project_probe; print(project_probe.VALUE)'],
    env=project_env, capture_output=True, text=True, timeout=10, check=True,
)
print(json.dumps({
    'isolated': sys.flags.isolated,
    'path': sys.path,
    'src_origin': spec.origin if spec else None,
    'timeout': os.environ['SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS'],
    'project': project.stdout.strip(),
}))
"""
    env: dict[str, str] = {
        **os.environ,
        "PYTHONPATH": str(hostile),
        "PYTHONHOME": str(hostile / "nonexistent-python-home"),
        "SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS": "8123",
    }
    result = subprocess.run(
        args=[*prefix, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    observed = json.loads(result.stdout)
    assert observed["isolated"] == 1
    assert "" not in observed["path"]
    assert str(tmp_path) not in observed["path"]
    assert str(hostile) not in observed["path"]
    assert observed["src_origin"] is not None, (
        "Managed children require Slo installed in the parent interpreter; "
        "cwd/PYTHONPATH cannot supply src under -I"
    )
    assert Path(observed["src_origin"]).is_relative_to(installed_python.parent.parent)
    assert observed["src_origin"] not in (
        str(tmp_path / "src" / "__init__.py"),
        str(hostile / "src" / "__init__.py"),
    )
    assert observed["timeout"] == "8123"
    assert observed["project"] == "project-import-ok"


def test_timeout_forwarding_and_pythonpath_filter_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Interpreter isolation does not change the existing child environment policy."""
    timeouts: dict[str, str] = {
        "SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS": "12000",
        "SLO_SUBAGENT_INACTIVITY_TIMEOUT_SECONDS": "8000",
        "SLO_SUBAGENT_TERMINATE_GRACE_SECONDS": "7",
        "SLO_BASH_DEFAULT_TIMEOUT_SECONDS": "1900",
        "SLO_BASH_TEARDOWN_GRACE_SECONDS": "8",
    }
    for name, value in timeouts.items():
        monkeypatch.setenv(name=name, value=value)
    monkeypatch.setenv(name="PYTHONPATH", value="/hostile")
    monkeypatch.setenv(name="PYTHONHOME", value="/hostile")
    env: dict[str, str] = build_headless_child_env()
    assert {name: env[name] for name in timeouts} == timeouts
    assert "PYTHONPATH" not in env
    assert "PYTHONHOME" not in env
