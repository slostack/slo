"""Shared test fixtures."""

import importlib
import shutil
from pathlib import Path

from tests.state_isolation import (
    INHERITED_STATE_OVERRIDES,
    FakeHerdrFixture,
    FakeHerdrSpawnGuard,
    SLO_HOME_BINDINGS,
    inherited_herdr_names,
    isolate_suite_slo_home,
)

# Collection imports application state, so fixtures alone are too late.
_SUITE_SLO_HOME: Path = isolate_suite_slo_home()

import pytest  # noqa: E402


def pytest_unconfigure(config: pytest.Config) -> None:
    """Remove the suite-owned state after pytest finishes, including failed runs.

    Args:
        config (pytest.Config): The finishing pytest configuration (unused).
    """
    assert _SUITE_SLO_HOME.resolve() == _SUITE_SLO_HOME
    shutil.rmtree(path=_SUITE_SLO_HOME, ignore_errors=True)


@pytest.fixture(autouse=True)
def isolated_slo_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Give each test its own default state, including import-bound paths.

    WHO: All tests use this fixture before their own patches. Tests may request
    the root explicitly. Monkeypatch restores the bindings after each test.

    Args:
        tmp_path_factory (pytest.TempPathFactory): Allocator for owned roots.
        monkeypatch (pytest.MonkeyPatch): Per-test environment and binding lifetime.

    Returns:
        Path: The resolved, initially empty per-test SLO_HOME.
    """
    for name in inherited_herdr_names():
        monkeypatch.delenv(name=name, raising=False)
    monkeypatch.setenv(name="SLO_HERDR_DISABLED", value="1")
    root: Path = tmp_path_factory.mktemp("slo-home").resolve()
    monkeypatch.setenv(name="SLO_HOME", value=str(root))
    monkeypatch.setenv(name="SLO_AUTH_FILE", value=str(root / "global" / "authentication.json"))
    monkeypatch.setenv(name="HOME", value=str(root / "home"))
    for name in INHERITED_STATE_OVERRIDES:
        monkeypatch.delenv(name=name, raising=False)
    for module_name, attribute in SLO_HOME_BINDINGS:
        monkeypatch.setattr(target=importlib.import_module(module_name), name=attribute, value=root)
    _isolate_config_defaults(root=root, monkeypatch=monkeypatch)
    refresher = importlib.import_module("src.auth.credential_refresher")
    monkeypatch.setattr(target=refresher, name="_CREDENTIALS_LOCK_FILE", value=root / ".credentials.lock")
    resolver = importlib.import_module("src.auth.credential_resolver")
    monkeypatch.setattr(
        target=resolver.CredentialResolver,
        name="_CLAUDE_CREDENTIALS_PATH",
        value=root / "home/.claude/.credentials.json",
    )
    return root


def _isolate_config_defaults(*, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rebind cached config after earlier tests may have reloaded it.

    The autouse fixture calls this before each test; patching the existing
    mapping preserves unrelated settings without reloading application modules.

    Args:
        root (Path): Current test's state root.
        monkeypatch (pytest.MonkeyPatch): Restores constants and mappings on teardown.
    """
    configuration = importlib.import_module("config.cfg")
    defaults: dict[str, Path | str] = {
        "SLO_HOME": root,
        "SLO_AUTH_FILE": root / "global/authentication.json",
        "USER_SKILLS_DIR": str(root / "user_skills"),
        "USER_WORKFLOWS_DIR": str(root / "user_workflows"),
        "SLO_KB_DIR": str(root / "KnowledgeBase/KB"),
    }
    for name, value in defaults.items():
        monkeypatch.setattr(target=configuration, name=name, value=value)
        monkeypatch.setitem(dic=configuration.__cfg__, name=name, value=str(value))
    for name in ("PREFERENCES_FILE", "SCHEDULES_DIR", "CONNECTORS_DIR", "MODEL_CATALOG_OVERRIDES_FILE"):
        monkeypatch.setattr(target=configuration, name=name, value=None)
        monkeypatch.setitem(dic=configuration.__cfg__, name=name, value=None)
    location = configuration.ResolvedDirectory(
        path=str(root / "KnowledgeBase/KB"), source="the default `$SLO_HOME/KnowledgeBase/KB`"
    )
    monkeypatch.setattr(target=configuration, name="KB_LOCATION", value=location)
    prompts = importlib.import_module("src.agents.slo_agent.prompts")
    monkeypatch.setattr(target=prompts, name="KB_LOCATION", value=location)
    agent = importlib.import_module("src.agents.slo_agent.agent")
    for name in ("USER_SKILLS_DIR", "USER_WORKFLOWS_DIR"):
        monkeypatch.setattr(target=agent, name=name, value=defaults[name])


@pytest.fixture(autouse=True)
def _enable_test_local_plugins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable synthetic plugin fixtures while the suite uses an isolated HOME.

    WHAT: Removes only the invocation-level plugin kill switch so plugin tests
        can load files they create below pytest-owned roots.
    WHO: Every test receives the fixture; plugin tests supply their own explicit
        managed, project, or CLI fixture paths.
    WHEN: Restored by pytest's monkeypatch teardown before the next test.
    """
    monkeypatch.delenv("SLO_PLUGINS_DISABLED", raising=False)


@pytest.fixture(autouse=True)
def _never_spawn_real_terminals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub ``VisualizerLauncher._default_spawn`` for every test.

    ``VisualizerLauncher.launch()`` opens a REAL terminal window on the
    developer's machine (``osascript`` → Terminal.app on macOS, a terminal
    emulator on Linux) running ``slo visualize --follow`` — a process that
    never exits on its own. Any test that reaches ``launch()`` without
    patching it (e.g. by streaming a ``sub_agent_spawned`` event or a
    ``launch_workflow`` tool result through ``SloTUI._render_event``) would
    leave a live terminal window behind after the suite finishes.

    This guard replaces only the innermost ``_default_spawn`` seam, so:

    - tests that patch ``VisualizerLauncher.launch`` or inject a ``spawn=``
      callable are unaffected (they never reach ``_default_spawn``);
    - tests exercising the real ``launch()`` path still observe ``True``
      (the stub "succeeds") without any process being created;
    - ``environments/tests.env`` additionally sets ``SLO_AUTO_VISUALIZE=0``
      for ``make test``, but this fixture also covers bare ``pytest`` runs
      that never source that file.
    """

    def _stubbed_spawn(argv: list[str]) -> object:
        """Pretend to spawn ``argv`` without creating any process."""
        return object()

    _stubbed_spawn.__test_stub__ = True  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "src.tui.visualizer_launcher.VisualizerLauncher._default_spawn",
        staticmethod(_stubbed_spawn),
    )

    def _refuse_editor_request(self: object, *, argv: tuple[str, ...]) -> None:
        """Refuse editor APIs under inherited tmux/iTerm hints; tests inject recorders."""
        raise AssertionError("Real editor terminal API forbidden in tests; inject process=")

    monkeypatch.setattr(
        target="src.tui.editor_platform_terminal.LocalEditorTerminalProcess.run",
        name=_refuse_editor_request,
    )


@pytest.fixture
def fake_herdr_guard(tmp_path: Path) -> "FakeHerdrSpawnGuard":
    """Allocate an ungranted per-test capability for T2's independent spawn guard."""
    return FakeHerdrSpawnGuard(root=tmp_path)


@pytest.fixture(autouse=True)
def _never_spawn_real_herdr(fake_herdr_guard: FakeHerdrSpawnGuard, monkeypatch: pytest.MonkeyPatch) -> None:
    """Refuse all transport spawn without this test's registered file capability."""
    import asyncio
    from src.agents.slo_agent.herdr.dao import HerdrCliCommandDAO
    from src.agents.slo_agent.herdr.service import HerdrCliTransport

    original_spawn = HerdrCliTransport._spawn

    async def guarded_spawn(
        transport: HerdrCliTransport, *, command: HerdrCliCommandDAO
    ) -> asyncio.subprocess.Process:
        """Revalidate every fixture identity immediately before delegation."""
        fake_herdr_guard.require_registered(path=transport._config.binary_path)
        return await original_spawn(transport, command=command)

    monkeypatch.setattr(target=HerdrCliTransport, name="_spawn", value=guarded_spawn)


@pytest.fixture
def fake_herdr(
    tmp_path: Path, fake_herdr_guard: "FakeHerdrSpawnGuard", monkeypatch: pytest.MonkeyPatch
) -> "FakeHerdrFixture":
    """Create and register only new contained files before synthetic activation."""
    import sys

    executable, capture, barrier = (tmp_path / name for name in ("fake-herdr", "capture.jsonl", "barrier"))
    script = (
        f"#!{sys.executable}\nimport json, os, sys\nfrom pathlib import Path\n"
        f"root = Path({str(tmp_path)!r})\n"
        f"capture = Path({str(capture)!r})\n"
        "assert not capture.is_symlink() and capture.resolve().parent == root.resolve()\n"
        "with capture.open('a') as stream: stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    for path, text in ((executable, script), (capture, ""), (barrier, "")):
        assert path.is_absolute() and ".." not in path.parts
        assert not any(p.is_symlink() for p in (path, *path.parents))
        assert path.parent.resolve(strict=True) == tmp_path.resolve(strict=True)
        with path.open(mode="x", encoding="utf-8") as stream:
            stream.write(text)
        path.chmod(0o700 if path == executable else 0o600)
    fake_herdr_guard.register(executable=executable, files=(capture, barrier))
    for name, value in {
        "HERDR_ENV": "1",
        "HERDR_PANE_ID": "synthetic-pane",
        "HERDR_BIN_PATH": str(executable),
        "SLO_HERDR_DISABLED": "0",
    }.items():
        monkeypatch.setenv(name=name, value=value)
    return FakeHerdrFixture(executable=executable, capture=capture, barrier=barrier, guard=fake_herdr_guard)
