"""Opt-in local candidate installation, isolated recovery and managed-child provenance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import sysconfig
import tomllib
import venv
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("SLO_QUOTA_INSTALL_E2E") != "1",
        reason="opt-in disposable local wheel installation; no provider or operator upgrade",
    ),
]


def _run(*, argv: list[str], root: Path, environment: dict[str, str]) -> str:
    """Run a bounded command only in the owned disposable installation root."""
    assert root.resolve().is_relative_to(Path(environment["HOME"]).parent.resolve())
    result = subprocess.run(
        args=argv,
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def test_installed_quota_recovery_outside_checkout(tmp_path: Path) -> None:
    """Install the real wheel and prove SDK recovery plus real managed child identity."""
    root = tmp_path.resolve()
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(root / "home"),
        "SLO_HOME": str(root / "state"),
        "SLO_HERDR_DISABLED": "1",
        "SLO_AUTO_VISUALIZE": "0",
        "SLO_PLUGINS_DISABLED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONPATH": str(ROOT),
        "PIP_CACHE_DIR": str(root / "pip-cache"),
        "XDG_CACHE_HOME": str(root / "cache"),
    }
    (root / "home").mkdir()
    source = root / "source"
    source.mkdir()
    for name in ("src", "config", "skills", "plugins"):
        shutil.copytree(src=ROOT / name, dst=source / name, ignore=shutil.ignore_patterns("__pycache__"))
    for name in ("pyproject.toml", "README.md", "install.sh"):
        shutil.copyfile(src=ROOT / name, dst=source / name)
    _run(
        argv=[sys.executable, "-c", "from poetry.core.masonry.api import build_wheel; build_wheel('dist')"],
        root=source,
        environment=environment,
    )
    wheel = next((source / "dist").glob("*.whl"))
    wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
    target = root / "venv"
    venv.EnvBuilder(system_site_packages=True, with_pip=False).create(env_dir=target)
    python = target / "bin/python"
    # A venv's system-site-packages points at the base Python, not the invoking
    # harness venv. Borrow only its dependency directory after candidate packages;
    # path entries do not process that directory's editable-install .pth files.
    dependency_path = Path(sysconfig.get_paths()["purelib"])
    local_site = target / "lib/python3.11/site-packages"
    (local_site / "quota-test-dependencies.pth").write_text(str(dependency_path) + "\n", encoding="utf-8")
    _run(
        argv=[
            sys.executable,
            "-m",
            "pip",
            "--python",
            str(python),
            "install",
            "--no-index",
            "--no-deps",
            "--no-compile",
            str(wheel),
        ],
        root=root,
        environment=environment,
    )
    # Only test support is copied. No src/config replacement or editable install.
    support = root / "support"
    (support / "tests/cli").mkdir(parents=True)
    (support / "tests/bridges/claude").mkdir(parents=True)
    for relative in (
        "tests/__init__.py",
        "tests/cli/__init__.py",
        "tests/bridges/__init__.py",
        "tests/bridges/claude/__init__.py",
        "tests/cli/test_claude_bridge.py",
        "tests/bridges/claude/test_quota_recovery.py",
    ):
        destination = support / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (ROOT / relative).exists():
            shutil.copyfile(src=ROOT / relative, dst=destination)
        else:
            destination.write_text("", encoding="utf-8")
    runner = root / "installed_probe.py"
    shutil.copyfile(src=ROOT / "tests/cli/claude_quota_installed_probe.py", dst=runner)
    version = _run(
        argv=[str(python), "-I", str(target / "bin/slo"), "--version"], root=root, environment=environment
    )
    output = _run(
        argv=[str(python), "-I", str(runner), str(root), str(ROOT)],
        root=root,
        environment=environment,
    )
    negative = subprocess.run(
        args=[
            str(python),
            "-I",
            "-c",
            "import runpy,sys;sys.path.insert(0,sys.argv[3]);sys.argv=[sys.argv[1],sys.argv[2],sys.argv[3]];runpy.run_path(sys.argv[0],run_name='__main__')",
            str(runner),
            str(root),
            str(ROOT),
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert negative.returncode != 0 and "checkout import rejected" in negative.stderr
    (root / "isolation-negative.log").write_text(negative.stderr, encoding="utf-8")
    receipt = json.loads((root / "installed-receipt.json").read_text())
    with (source / "pyproject.toml").open(mode="rb") as package_metadata_file:
        expected_version: str = tomllib.load(package_metadata_file)["project"]["version"]
    assert receipt["parent"]["version"] == receipt["child"]["version"] == expected_version
    assert version.strip() == expected_version
    assert receipt["parent"]["modules"] == receipt["child"]["modules"]
    assert receipt["parent"]["hashes"] == receipt["child"]["hashes"]
    assert receipt["parent"]["executable"] == receipt["child"]["executable"] == str(python)
    source_hashes = {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in (
            "src/bridges/claude/bridge.py",
            "src/bridges/claude/sdk/sdk_runtime.py",
            "src/bridges/claude/sdk/transport.py",
        )
    }
    assert receipt["parent"]["hashes"]["bridge"] == source_hashes["src/bridges/claude/bridge.py"]
    assert receipt["parent"]["hashes"]["runtime"] == source_hashes["src/bridges/claude/sdk/sdk_runtime.py"]
    assert receipt["parent"]["hashes"]["transport"] == source_hashes["src/bridges/claude/sdk/transport.py"]
    receipt.update(
        {
            "wheel_sha256": wheel_hash,
            "wheel": str(wheel),
            "slo_version": version.strip(),
            "source_hashes": source_hashes,
            "checkout_rejected": True,
        }
    )
    (root / "installed-receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True))
    assert "installed-quota-ok" in output
