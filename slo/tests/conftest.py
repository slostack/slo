"""Shared test fixtures."""

import pytest


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
