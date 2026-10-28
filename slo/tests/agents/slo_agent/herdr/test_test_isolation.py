"""Offline environment prerequisites; transport activation belongs to T2."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY: Path = Path(__file__).resolve().parents[4]
HOSTILE_NAMES: tuple[str, ...] = (
    "HERDR_ENV",
    "herdr_pane_id",
    "HeRdR_BIN_PATH",
    "HERDR_FUTURE_SETTING",
    "SLO_HERDR_METADATA_PROFILE",
    "slo_herdr_metadata_profile",
)


@pytest.mark.parametrize(argnames="layer", argvalues=["suite", "per-test"])
def test_inherited_herdr_is_removed_before_import(tmp_path: Path, layer: str) -> None:
    """Observe actual bootstrap and rebinding boundaries in a fresh interpreter."""
    script: str = """
import builtins, os, runpy, sys, tempfile
from pathlib import Path
import pytest
sys.path.insert(0, sys.argv[1])
names = sys.argv[3:]
def assert_isolated():
    assert not any(name in os.environ for name in names), 'inherited-herdr-retained'
    assert os.environ.get('SLO_HERDR_DISABLED') == '1', 'herdr-not-disabled'
    assert os.environ['NOT_HERDR_ENV'] == 'preserved'
original_import = builtins.__import__
observed = []
def checked_import(name, *args, **kwargs):
    if name == 'config.cfg':
        assert_isolated()
        observed.append(name)
    return original_import(name, *args, **kwargs)
builtins.__import__ = checked_import
namespace = runpy.run_path(sys.argv[1] + '/tests/conftest.py')
try:
    import config.cfg
    assert observed
    assert_isolated()
    if sys.argv[2] == 'per-test':
        for name in names:
            os.environ[name] = 'synthetic-only'
        os.environ['SLO_HERDR_DISABLED'] = '0'
        original_module_import = namespace['importlib'].import_module
        rebound = []
        def checked_module_import(name, *args, **kwargs):
            assert_isolated()
            rebound.append(name)
            return original_module_import(name, *args, **kwargs)
        namespace['importlib'].import_module = checked_module_import
        class Factory:
            def mktemp(self, basename):
                return Path(tempfile.mkdtemp(prefix=basename))
        with pytest.MonkeyPatch.context() as patcher:
            namespace['isolated_slo_home'].__wrapped__(
                tmp_path_factory=Factory(), monkeypatch=patcher)
            assert_isolated()
            assert rebound
        assert os.environ['SLO_HERDR_DISABLED'] == '0'
        assert all(name in os.environ for name in names)
finally:
    namespace['pytest_unconfigure'](config=None)
"""
    result = subprocess.run(
        args=[sys.executable, "-B", "-c", script, str(REPOSITORY), layer, *HOSTILE_NAMES],
        cwd=tmp_path,
        env={
            "PATH": os.defpath,
            "TMPDIR": str(tmp_path),
            "HOME": str(tmp_path),
            "SLO_HERDR_DISABLED": "0",
            "NOT_HERDR_ENV": "preserved",
            **dict.fromkeys(HOSTILE_NAMES, "synthetic-only"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_fixture_disables_herdr_and_preserves_terminal_blocker() -> None:
    """The ordinary autouse path keeps both independent safety defaults."""
    from src.tui.visualizer_launcher import VisualizerLauncher

    assert os.environ.get("SLO_HERDR_DISABLED") == "1"
    assert not any(name.upper().startswith("HERDR_") for name in os.environ)
    assert "SLO_HERDR_METADATA_PROFILE" not in os.environ
    assert getattr(VisualizerLauncher._default_spawn, "__test_stub__", False)


def _write_owned(*, root: Path, path: Path, content: str) -> None:
    """Write a new fixture file only after proving containment.

    Args:
        root (Path): Fresh pytest-owned directory.
        path (Path): New direct child, never an existing file or link.
        content (str): Synthetic fixture content.
    """
    assert path.parent == root
    assert path.resolve().is_relative_to(root.resolve())
    assert not path.is_symlink() and not path.exists()
    with path.open(mode="x", encoding="utf-8") as stream:
        stream.write(content)


@pytest.mark.parametrize(argnames="target", argvalues=["test", "smoke"])
@pytest.mark.parametrize(argnames="local_environment", argvalues=[False, True])
def test_make_forces_disabled_after_environment_selection(
    tmp_path: Path, target: str, local_environment: bool
) -> None:
    """Execute tracked recipes with a new temp-owned poetry stub, never pytest/Herdr."""
    _write_owned(root=tmp_path, path=tmp_path / "Makefile", content=(REPOSITORY / "Makefile").read_text())
    stub: Path = tmp_path / "poetry"
    _write_owned(
        root=tmp_path,
        path=stub,
        content='#!/bin/sh\n[ "$SLO_HERDR_DISABLED" = 1 ] || exit 42\nprintf "disabled\\n"\n',
    )
    assert stub.resolve().is_relative_to(tmp_path.resolve()) and not stub.is_symlink()
    stub.chmod(mode=0o700)
    if local_environment:
        environment_dir: Path = tmp_path / "environments"
        assert environment_dir.resolve().is_relative_to(tmp_path.resolve())
        environment_dir.mkdir()
        _write_owned(
            root=environment_dir, path=environment_dir / "tests.env", content="SLO_HERDR_DISABLED=0\n"
        )
    result = subprocess.run(
        args=["/usr/bin/make", target],
        cwd=tmp_path,
        env={"PATH": f"{tmp_path}:{os.defpath}", "SLO_HERDR_DISABLED": "0"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "disabled"


@pytest.mark.parametrize("surface", ["mounted", "headless"])
async def test_actual_guard_refuses_activation_inside_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, surface: str
) -> None:
    """Real runtime consumers cannot turn synthetic environment into spawn authority."""
    from langchain_core.messages import AIMessage
    from src.agents.providers.faux import FauxChatModel
    from src.agents.slo_agent.agent import SloAgent
    from src.agents.slo_agent.sessions.service import SloAgentSession
    from src.agents.slo_agent.sessions.dao import SessionConfigDAO
    from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO, HerdrReporterConfigDAO
    from src.agents.slo_agent.herdr.service import HerdrCliTransport
    from src.cli.headless import HeadlessRunner
    from src.tui.app import SloTUI

    executable = tmp_path / "unregistered"
    _write_owned(root=tmp_path, path=executable, content="#!/bin/sh\nexit 99\n")
    executable.chmod(0o700)
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_BIN_PATH", str(executable))
    monkeypatch.setenv("HERDR_PANE_ID", "synthetic")
    monkeypatch.setenv("SLO_HERDR_DISABLED", "0")
    transport = HerdrCliTransport(
        config=HerdrReporterConfigDAO(
            pane_id="synthetic", binary_path=executable, state_root=tmp_path, metadata_profile="compact"
        ),
        environment={},
    )
    session = SloAgentSession(
        session_id="00000000-0000-4000-8000-000000000001",
        agent=SloAgent(llm=FauxChatModel(responses=[AIMessage(content="offline")])),
        workdir=tmp_path,
        enable_history=False,
    )
    calls: list[str] = []

    async def attempted_spawn(event: object) -> None:
        """Exercise the actual autouse transport guard from the runtime event path."""
        with pytest.raises(AssertionError, match="Unregistered"):
            await transport._spawn(command=HerdrCliCommandDAO(argv=("pane", "split")))
        calls.append("refused")

    session.subscribe(handler=attempted_spawn)
    if surface == "mounted":
        app = SloTUI(session=session)
        async with app.run_test():
            async for _ in session.invoke(text="offline"):
                pass
    else:
        monkeypatch.setattr(SloAgentSession, "build", lambda **kwargs: session)
        runner = HeadlessRunner(config=SessionConfigDAO(workdir=tmp_path, enable_history=False))
        assert await runner.invoke(prompt="offline") == 0
    assert calls
    assert transport.resources_drained


def test_tracked_template_documents_runtime_defaults_and_test_override() -> None:
    """Runtime defaults do not silently become suite activation permission."""
    template: str = (REPOSITORY / "environments/.env.template").read_text(encoding="utf-8")
    assert "SLO_HERDR_DISABLED=0" in template
    assert "SLO_HERDR_METADATA_PROFILE=compact" in template
    assert "SLO_HERDR_DISABLED=1" in template
