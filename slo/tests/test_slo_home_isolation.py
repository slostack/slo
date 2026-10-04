"""Regression coverage for collection-time and per-test state isolation."""

import ast
import importlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.state_isolation import INHERITED_STATE_OVERRIDES, SLO_HOME_BINDINGS


@pytest.mark.parametrize(argnames="remove_overrides", argvalues=[True, False])
@pytest.mark.parametrize(argnames="layer", argvalues=["suite", "per-test"])
def test_isolate_suite_slo_home_when_environment_is_hostile_rebinds_before_import(
    tmp_path: Path,
    remove_overrides: bool,
    layer: str,
) -> None:
    """Run the root conftest before application imports in an owned hostile HOME.

    The isolation suite checks import-bound paths in a fresh process, then asks
    pytest's teardown hook to remove only the suite root it created.
    """
    repository: Path = Path(__file__).resolve().parents[1]
    scratch: Path = tmp_path / "scratch"
    hostile: Path = tmp_path / "hostile"
    for path in (scratch, hostile):
        assert path.resolve().is_relative_to(tmp_path.resolve())
        path.mkdir()
    sentinel: Path = hostile / "sentinel"
    assert sentinel.resolve().is_relative_to(tmp_path.resolve())
    sentinel.write_bytes(b"external state must stay unchanged")
    script: str = """
import os, runpy, sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, sys.argv[1])
from tests import state_isolation
if sys.argv[2] == 'False':
    state_isolation.INHERITED_STATE_OVERRIDES = ()
namespace = runpy.run_path(sys.argv[1] + '/tests/conftest.py')
import config.cfg
from src.auth.credential_resolver import CredentialResolver
root = config.cfg.SLO_HOME.resolve()
assert root.is_relative_to(Path(os.environ['TMPDIR']).resolve()), root
assert CredentialResolver._CLAUDE_CREDENTIALS_PATH.is_relative_to(root)
assert Path.home() == root / 'home'
assert config.cfg.SLO_AUTH_FILE.is_relative_to(root)
from tests.state_isolation import INHERITED_STATE_OVERRIDES
namespace['pytest_unconfigure'](config=None)
assert not root.exists(), root
if sys.argv[3] == 'per-test':
    os.environ['SLO_CAPTURE_DIR'] = sys.argv[4]
    class Factory:
        def mktemp(self, basename: str) -> Path:
            return Path(tempfile.mkdtemp(prefix=basename))
    with pytest.MonkeyPatch.context() as patcher:
        per_test_root = namespace['isolated_slo_home'].__wrapped__(
            tmp_path_factory=Factory(), monkeypatch=patcher
        )
        assert 'SLO_CAPTURE_DIR' not in os.environ, 'override-removal-disabled'
        assert Path.home() == per_test_root / 'home'
    os.environ.pop('SLO_CAPTURE_DIR', None)
assert 'SLO_CAPTURE_DIR' not in os.environ, 'override-removal-disabled'
assert all(Path(value).is_relative_to(root) for value in (
    config.cfg.USER_SKILLS_DIR, config.cfg.USER_WORKFLOWS_DIR, config.cfg.SLO_KB_DIR
))
assert not set(INHERITED_STATE_OVERRIDES).intersection(os.environ)
"""
    result: subprocess.CompletedProcess[str] = subprocess.run(
        args=[
            sys.executable,
            "-B",
            "-c",
            script,
            str(repository),
            str(remove_overrides),
            layer,
            str(hostile / "capture"),
        ],
        cwd=tmp_path,
        env={
            **{name: str(hostile / name) for name in INHERITED_STATE_OVERRIDES},
            "PATH": os.defpath,
            "HOME": str(hostile),
            "SLO_HOME": str(hostile / "slo"),
            "SLO_AUTH_FILE": str(hostile / "authentication.json"),
            "SLO_CAPTURE_DIR": str(hostile / "capture"),
            "TMPDIR": str(scratch),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    receipts: dict[str, str] = {
        "probe-command.json": json.dumps(result.args),
        "probe-output.log": result.stdout + result.stderr,
        "probe-exit.txt": str(result.returncode),
    }
    for name, content in receipts.items():
        receipt: Path = tmp_path / name
        assert receipt.resolve().is_relative_to(tmp_path.resolve())
        receipt.write_text(data=content, encoding="utf-8")
    expected_exit: int = 0 if remove_overrides else 1
    assert result.returncode == expected_exit, result.stdout + result.stderr
    if not remove_overrides:
        assert "override-removal-disabled" in result.stderr
    assert list(hostile.iterdir()) == [sentinel]
    assert sentinel.read_bytes() == b"external state must stay unchanged"


def _module_level_slo_home_bindings(*, source_root: Path) -> set[tuple[str, str]]:
    """Discover import-bound state for the registry guard before checking coverage.

    Args:
        source_root (Path): Application source tree, or an owned sensitivity specimen.

    Returns:
        set[tuple[str, str]]: Module names and bound attributes needing isolation.
    """
    bindings: set[tuple[str, str]] = set()
    for path in source_root.rglob("*.py"):
        module_name: str = ".".join(path.relative_to(source_root.parent).with_suffix("").parts)
        imports = (
            node
            for node in ast.parse(path.read_text(encoding="utf-8")).body
            if isinstance(node, ast.ImportFrom) and node.module == "config.cfg"
        )
        for node in imports:
            bindings.update(
                (module_name, alias.asname or alias.name) for alias in node.names if alias.name == "SLO_HOME"
            )
    return bindings


def test_isolated_slo_home_when_test_runs_rebinds_default_state(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """Check the active test owns HOME, config aliases, auth and refresh locks."""
    root: Path = Path(os.environ["SLO_HOME"])
    assert root.is_relative_to(tmp_path_factory.getbasetemp())
    assert Path.home() == root / "home"
    configuration = importlib.import_module("config.cfg")
    assert configuration.SLO_HOME == root
    assert configuration.SLO_AUTH_FILE == root / "global" / "authentication.json"
    assert configuration.cfg("SLO_AUTH_FILE") == str(root / "global" / "authentication.json")
    source_root: Path = Path(__file__).resolve().parents[1] / "src"
    for module_name, attribute in _module_level_slo_home_bindings(source_root=source_root):
        assert getattr(importlib.import_module(module_name), attribute) == root
    refresher = importlib.import_module("src.auth.credential_refresher")
    assert refresher._CREDENTIALS_LOCK_FILE == root / ".credentials.lock"
    resolver = importlib.import_module("src.auth.credential_resolver")
    assert resolver.CredentialResolver._CLAUDE_CREDENTIALS_PATH == root / "home/.claude/.credentials.json"
    assert not set(INHERITED_STATE_OVERRIDES).intersection(os.environ)


def test_isolated_slo_home_when_config_was_reloaded_rebinds_derived_defaults(
    isolated_slo_home: Path,
) -> None:
    """Require config's cached fallbacks and copied content paths to belong to this test."""
    configuration = importlib.import_module("config.cfg")
    for name in ("SLO_HOME", "SLO_AUTH_FILE", "USER_SKILLS_DIR", "USER_WORKFLOWS_DIR", "SLO_KB_DIR"):
        assert Path(configuration.__cfg__[name]).is_relative_to(isolated_slo_home), name
        assert Path(getattr(configuration, name)).is_relative_to(isolated_slo_home), name
    agent = importlib.import_module("src.agents.slo_agent.agent")
    assert Path(agent.USER_SKILLS_DIR).is_relative_to(isolated_slo_home)
    assert Path(agent.USER_WORKFLOWS_DIR).is_relative_to(isolated_slo_home)
    prompts = importlib.import_module("src.agents.slo_agent.prompts")
    assert Path(prompts.KB_LOCATION.path).is_relative_to(isolated_slo_home)


def test_isolated_slo_home_when_src_binds_slo_home_lists_every_binding() -> None:
    """Fail when a new module copies SLO_HOME without joining the fixture registry."""
    source_root: Path = Path(__file__).resolve().parents[1] / "src"
    assert _module_level_slo_home_bindings(source_root=source_root) == set(SLO_HOME_BINDINGS)


def test_binding_guard_when_new_alias_is_unlisted_detects_it(tmp_path: Path) -> None:
    """Prove guard sensitivity using a source specimen, never editing production code."""
    specimen: Path = tmp_path / "new_owner.py"
    assert specimen.resolve().is_relative_to(tmp_path.resolve())
    specimen.write_text(data="from config.cfg import SLO_HOME as NEW_HOME\n", encoding="utf-8")
    discovered = _module_level_slo_home_bindings(source_root=tmp_path)
    assert discovered == {(f"{tmp_path.name}.new_owner", "NEW_HOME")}
    with pytest.raises(expected_exception=AssertionError):
        assert discovered <= set(SLO_HOME_BINDINGS)


def _state_override_names(*, source: str) -> set[str]:
    """Find path-shaped Slo settings for the source-inventory regression guard.

    Args:
        source (str): Python source containing settings names.

    Returns:
        set[str]: State-path and workflow-completion names, excluding source location.
    """
    pattern: str = r"SLO_[A-Z_]*(?:DIR|FILE|HOME|ROOT|SOURCE|COMPLETION|WORKFLOW_ID)"
    return {
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and re.fullmatch(pattern=pattern, string=node.value)
        and node.value != "SLO_APP_DIR"  # Source location, not a user-state directory.
    }


def test_override_guard_when_source_adds_state_setting_requires_classification() -> None:
    """Keep path-like settings exhaustive rather than checking only today's environment."""
    repository: Path = Path(__file__).resolve().parents[1]
    known: set[str] = set(INHERITED_STATE_OVERRIDES) | {"SLO_HOME", "SLO_AUTH_FILE"}
    for folder in ("src", "config"):
        for path in (repository / folder).rglob("*.py"):
            assert _state_override_names(source=path.read_text(encoding="utf-8")) <= known, path
    with pytest.raises(expected_exception=AssertionError):
        assert _state_override_names(source='PATH = "SLO_NEW_STATE_DIR"') <= known


_OBSERVED_ROOTS: set[Path] = set()


@pytest.mark.parametrize(argnames="iteration", argvalues=[1, 2])
def test_isolated_slo_home_when_next_test_runs_allocates_distinct_root(
    isolated_slo_home: Path,
    iteration: int,
) -> None:
    """Require separate empty roots across independent fixture invocations."""
    assert iteration in (1, 2)
    assert isolated_slo_home not in _OBSERVED_ROOTS
    assert list(isolated_slo_home.iterdir()) == []
    _OBSERVED_ROOTS.add(isolated_slo_home)


def test_installer_stub_when_python_is_needed_uses_project_interpreter(tmp_path: Path) -> None:
    """Check wrapper text without ever executing the forbidden system Python.

    The full isolation gate includes installer tests; their temp-local wrappers
    must use the same approved interpreter as pytest, not a system-path lookup.
    """
    from tests.cli.test_install import FakeBin

    assert tmp_path.resolve() == tmp_path
    FakeBin(root=tmp_path)
    wrapper: str = (tmp_path / "bin/python3").read_text(encoding="utf-8")
    assert f"exec {sys.executable} " in wrapper
