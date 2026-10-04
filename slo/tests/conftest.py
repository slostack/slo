"""Shared test fixtures."""

import importlib
import shutil
from pathlib import Path

from tests.state_isolation import INHERITED_STATE_OVERRIDES, SLO_HOME_BINDINGS, isolate_suite_slo_home

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
