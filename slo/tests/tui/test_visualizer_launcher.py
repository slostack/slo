"""Tests for VisualizerLauncher — auto-launch of ``slo visualize`` in a new window."""

from __future__ import annotations

import os
import shlex
from typing import Optional

import pytest

from src.tui.visualizer_launcher import VisualizerLauncher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clear_slo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all forwarded SLO_* env vars so export output is deterministic.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture used to delete env vars.
    """
    for key in (
        "SLO_HOME",
        "SLO_ENV",
        "SLO_APP_NAME",
        "SLO_VISUALIZER_REFRESH_SECONDS",
        "SLO_VISUALIZER_TERMINAL_APP",
        "SLO_AUTO_VISUALIZE",
        "PYTHONPATH",
    ):
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# _visualize_argv
# ---------------------------------------------------------------------------


class TestVisualizeArgv:
    """The bare ``slo visualize`` argv is well-formed."""

    def test_includes_session_and_follow(self) -> None:
        """The argv carries --session <id> and --follow."""
        argv = VisualizerLauncher._visualize_argv(parent_session_id="sess-42")

        assert "visualize" in argv
        assert argv[-3:] == ["--session", "sess-42", "--follow"]

    def test_prefers_slo_binary_when_on_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When ``slo`` is on PATH the entrypoint is that single executable."""
        monkeypatch.setattr(
            "src.tui.visualizer_launcher.shutil.which",
            lambda name: "/usr/local/bin/slo",
        )
        argv = VisualizerLauncher._visualize_argv(parent_session_id="s")

        assert argv[0] == "/usr/local/bin/slo"
        assert argv[1] == "visualize"

    def test_falls_back_to_python_module_when_no_binary(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without ``slo`` on PATH it falls back to ``<python> -m src.cli``."""
        monkeypatch.setattr(
            "src.tui.visualizer_launcher.shutil.which",
            lambda name: None,
        )
        argv = VisualizerLauncher._visualize_argv(parent_session_id="s")

        assert argv[1:3] == ["-m", "src.cli"]
        assert argv[3] == "visualize"


# ---------------------------------------------------------------------------
# _shell_command / _env_export_prefix
# ---------------------------------------------------------------------------


class TestShellCommand:
    """The shell one-liner forwards allowlisted env, cds, and runs visualize."""

    def test_forwards_only_allowlisted_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SLO_HOME is forwarded; a secret provider key is not."""
        _clear_slo_env(monkeypatch)
        monkeypatch.setenv("SLO_HOME", "/tmp/slo-home")
        monkeypatch.setenv("SLO_ANTHROPIC_API_KEY", "sk-secret")

        command = VisualizerLauncher._shell_command(parent_session_id="s")

        assert "export SLO_HOME=/tmp/slo-home" in command
        assert "sk-secret" not in command
        assert "SLO_ANTHROPIC_API_KEY" not in command

    def test_quotes_paths_with_spaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A SLO_HOME containing a space is shell-quoted."""
        _clear_slo_env(monkeypatch)
        monkeypatch.setenv("SLO_HOME", "/tmp/my slo home")

        command = VisualizerLauncher._shell_command(parent_session_id="s")

        assert f"export SLO_HOME={shlex.quote('/tmp/my slo home')}" in command

    def test_includes_cd_and_visualize(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The command cds to the current working dir then runs visualize."""
        _clear_slo_env(monkeypatch)

        command = VisualizerLauncher._shell_command(parent_session_id="s")

        assert f"cd {shlex.quote(os.getcwd())}" in command
        assert "visualize --session s --follow" in command


# ---------------------------------------------------------------------------
# platform argv builders
# ---------------------------------------------------------------------------


class TestMacosArgv:
    """macOS uses osascript to drive a terminal application."""

    def test_default_targets_terminal_app(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no override the AppleScript targets Terminal.app via do script."""
        monkeypatch.setattr("src.tui.visualizer_launcher.cfg_module.VISUALIZER_TERMINAL_APP", None)
        argv = VisualizerLauncher._macos_argv(command="echo hi")

        assert argv[0] == "osascript"
        assert argv[1] == "-e"
        assert 'tell application "Terminal"' in argv[2]
        assert "do script" in argv[2]

    def test_iterm_override_uses_iterm_script(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An iTerm override produces an iTerm-flavoured AppleScript."""
        monkeypatch.setattr("src.tui.visualizer_launcher.cfg_module.VISUALIZER_TERMINAL_APP", "iTerm")
        argv = VisualizerLauncher._macos_argv(command="echo hi")

        assert 'tell application "iTerm"' in argv[2]
        assert "write text" in argv[2]

    def test_command_with_quotes_is_escaped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Double quotes in the command are escaped for the AppleScript string."""
        monkeypatch.setattr("src.tui.visualizer_launcher.cfg_module.VISUALIZER_TERMINAL_APP", None)
        argv = VisualizerLauncher._macos_argv(command='echo "x"')

        assert '\\"x\\"' in argv[2]


class TestLinuxArgv:
    """Linux resolves a terminal emulator and wraps the command."""

    def test_returns_none_when_no_emulator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No emulator on PATH → None (unsupported)."""
        monkeypatch.setattr("src.tui.visualizer_launcher.cfg_module.VISUALIZER_TERMINAL_APP", None)
        monkeypatch.setattr("src.tui.visualizer_launcher.shutil.which", lambda name: None)

        assert VisualizerLauncher._linux_argv(command="echo hi") is None

    def test_uses_resolved_emulator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A resolved emulator is used with a bash -lc wrapper."""
        monkeypatch.setattr("src.tui.visualizer_launcher.cfg_module.VISUALIZER_TERMINAL_APP", None)
        monkeypatch.setattr(
            "src.tui.visualizer_launcher.shutil.which",
            lambda name: "/usr/bin/xterm" if name == "xterm" else None,
        )
        argv = VisualizerLauncher._linux_argv(command="echo hi")

        assert argv is not None
        assert argv[0] == "/usr/bin/xterm"
        assert "bash" in argv
        assert "echo hi; exec bash" in argv[-1]


# ---------------------------------------------------------------------------
# _build_argv platform dispatch
# ---------------------------------------------------------------------------


class TestBuildArgv:
    """Platform dispatch selects the right builder or returns None."""

    def test_windows_is_unsupported(self) -> None:
        """win32 returns None."""
        result = VisualizerLauncher._build_argv(parent_session_id="s", platform="win32")
        assert result is None

    def test_darwin_returns_osascript(self) -> None:
        """darwin returns an osascript argv."""
        result = VisualizerLauncher._build_argv(parent_session_id="s", platform="darwin")
        assert result is not None
        assert result[0] == "osascript"


# ---------------------------------------------------------------------------
# launch()
# ---------------------------------------------------------------------------


class TestLaunch:
    """End-to-end launch behaviour with an injected spawner."""

    def test_disabled_returns_false_without_spawning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SLO_AUTO_VISUALIZE=0 skips the launch entirely."""
        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "0")
        spawned: list[list[str]] = []

        result = VisualizerLauncher.launch(
            parent_session_id="s",
            spawn=lambda argv: spawned.append(argv),
            platform="darwin",
        )

        assert result is False
        assert spawned == []

    def test_empty_session_id_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An empty parent session id is a no-op."""
        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
        spawned: list[list[str]] = []

        result = VisualizerLauncher.launch(
            parent_session_id="",
            spawn=lambda argv: spawned.append(argv),
            platform="darwin",
        )

        assert result is False
        assert spawned == []

    def test_unsupported_platform_returns_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An unsupported platform returns False and does not spawn."""
        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
        spawned: list[list[str]] = []

        result = VisualizerLauncher.launch(
            parent_session_id="s",
            spawn=lambda argv: spawned.append(argv),
            platform="win32",
        )

        assert result is False
        assert spawned == []

    def test_success_spawns_and_returns_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A supported platform spawns the terminal argv and returns True."""
        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
        spawned: list[list[str]] = []

        result = VisualizerLauncher.launch(
            parent_session_id="sess-99",
            spawn=lambda argv: spawned.append(argv),
            platform="darwin",
        )

        assert result is True
        assert len(spawned) == 1
        assert spawned[0][0] == "osascript"
        assert "sess-99" in spawned[0][2]

    def test_spawn_failure_is_swallowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A raising spawner is caught and reported as False."""
        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")

        def _boom(_argv: list[str]) -> None:
            raise OSError("no window server")

        result = VisualizerLauncher.launch(
            parent_session_id="s",
            spawn=_boom,
            platform="darwin",
        )

        assert result is False


# ---------------------------------------------------------------------------
# Suite-wide real-terminal guard (tests/conftest.py)
# ---------------------------------------------------------------------------


class TestSuiteNeverSpawnsRealTerminals:
    """The autouse guard keeps tests from opening terminal windows.

    ``launch()`` with no injected spawner falls through to
    ``VisualizerLauncher._default_spawn``, which on a developer machine opens
    a REAL Terminal/iTerm window running ``slo visualize --follow`` that
    outlives the test suite. ``tests/conftest.py`` stubs that seam for every
    test; these regression tests fail loudly if the guard is ever removed.
    """

    def test_default_spawn_is_stubbed_suite_wide(self) -> None:
        """The autouse fixture replaced ``_default_spawn`` with the test stub."""
        assert getattr(VisualizerLauncher._default_spawn, "__test_stub__", False) is True

    def test_unpatched_launch_spawns_no_real_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The worst case — auto-visualize on, no injected spawner — stays inert.

        This is the exact path an unpatched TUI test takes when it streams a
        ``sub_agent_spawned`` event or a ``launch_workflow`` tool result:
        ``launch()`` must still report success semantics without any
        ``subprocess.Popen`` ever running.
        """
        import subprocess

        monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")

        def _forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError(
                "a test tried to open a real terminal window via subprocess.Popen"
            )

        monkeypatch.setattr(subprocess, "Popen", _forbidden)

        result = VisualizerLauncher.launch(parent_session_id="sess-guard", platform="darwin")

        assert result is True  # stubbed spawn "succeeds" — but no process exists
