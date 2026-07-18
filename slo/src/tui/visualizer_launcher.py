"""VisualizerLauncher — open ``slo visualize`` in a separate OS terminal window.

When the interactive TUI promotes a session to orchestrator mode and the first
sub-agent is spawned, the operator should not have to remember to run
``slo visualize`` by hand. This module opens a fresh terminal window running

    slo visualize --session <parent_session_id> --follow

so the sub-agent workflow is visualised live alongside the orchestrator TUI.

Design notes:
  - **Best-effort.** ``launch`` never raises; a failed spawn returns ``False``
    so the caller can fall back to printing a manual-invocation hint.
  - **Env-faithful.** Every ``SLO_*`` variable set in the parent process is
    re-exported inside the new window so the child visualiser reads the same
    session store (``SLO_HOME``), environment, and skills directory.
  - **Platform-aware.** macOS uses ``osascript`` to drive Terminal.app (or
    iTerm); Linux probes a list of common terminal emulators. Any other
    platform (or a headless session with no window server) returns ``False``.
  - **Testable.** The subprocess spawn is injected via the ``spawn`` parameter
    and the platform / executable-resolution helpers are pure functions, so the
    argv construction can be asserted without opening a real window.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from typing import Callable, Optional

from config import cfg as cfg_module
from config.logger import log_warning

__all__ = ["VisualizerLauncher"]

# Callable that receives the fully-built argv and starts the detached process.
# Injected in tests to capture the argv without spawning a real terminal.
SpawnCallable = Callable[[list[str]], object]

# Env vars re-exported into the visualiser window. Deliberately an allowlist of
# non-secret runtime settings — provider keys and deploy tokens are never
# forwarded, since a spawned command's argv is world-readable via ``ps``. The
# visualiser is a read-only viewer; it only needs to locate the same session
# store (``SLO_HOME``), honour the same env/cadence, and (for source checkouts)
# resolve ``src.cli`` on ``PYTHONPATH``.
_FORWARDED_ENV_KEYS: tuple[str, ...] = (
    "SLO_HOME",
    "SLO_ENV",
    "SLO_APP_NAME",
    "SLO_VISUALIZER_REFRESH_SECONDS",
    "SLO_VISUALIZER_TERMINAL_APP",
    "SLO_AUTO_VISUALIZE",
    "PYTHONPATH",
)

# Linux terminal emulators probed in order when no override is configured. Each
# entry is the executable name; ``-e`` is the near-universal "run this command"
# flag across the listed emulators.
_LINUX_TERMINAL_CANDIDATES: tuple[str, ...] = (
    "x-terminal-emulator",
    "gnome-terminal",
    "konsole",
    "xfce4-terminal",
    "alacritty",
    "kitty",
    "xterm",
)


class VisualizerLauncher:
    """Open the workflow visualiser for a session in a new terminal window.

    The single public entry point is :meth:`launch`. All other methods are
    pure helpers that build the argv/command strings and are exercised directly
    by unit tests.
    """

    @classmethod
    def launch(
        cls,
        *,
        parent_session_id: str,
        spawn: Optional[SpawnCallable] = None,
        platform: Optional[str] = None,
    ) -> bool:
        """Open ``slo visualize`` for ``parent_session_id`` in a new window.

        No-ops (returning ``False``) when auto-visualise is disabled, the
        platform is unsupported, or no terminal emulator can be resolved. Never
        raises — any spawn failure is logged and reported as ``False``.

        Args:
            parent_session_id (str): The orchestrator session id whose
                sub-agent workflow should be visualised.
            spawn (Optional[SpawnCallable]): Override for the process spawner;
                defaults to a detached ``subprocess.Popen``. Injected in tests.
            platform (Optional[str]): Override for ``sys.platform``; injected in
                tests. Defaults to the running platform.

        Returns:
            bool: ``True`` when a terminal window was spawned, ``False`` when the
                launch was skipped or failed.
        """
        if not cls._auto_visualize_enabled():
            return False
        if not parent_session_id:
            return False
        active_platform: str = platform or sys.platform
        argv: Optional[list[str]] = cls._build_argv(
            parent_session_id=parent_session_id,
            platform=active_platform,
        )
        if argv is None:
            return False
        return cls._spawn_detached(argv=argv, spawn=spawn)

    # ── argv construction ────────────────────────────────────────────────────

    @classmethod
    def _build_argv(
        cls,
        *,
        parent_session_id: str,
        platform: str,
    ) -> Optional[list[str]]:
        """Build the terminal-launch argv for the active platform.

        Args:
            parent_session_id (str): Orchestrator session id to visualise.
            platform (str): The platform string (``sys.platform`` form).

        Returns:
            Optional[list[str]]: The argv to spawn, or ``None`` when the
                platform is unsupported or no terminal emulator is available.
        """
        command: str = cls._shell_command(parent_session_id=parent_session_id)
        if platform == "darwin":
            return cls._macos_argv(command=command)
        if platform.startswith("linux"):
            return cls._linux_argv(command=command)
        return None

    @classmethod
    def _shell_command(cls, *, parent_session_id: str) -> str:
        """Build the shell one-liner run inside the new terminal window.

        Re-exports every ``SLO_*`` env var currently set, changes into the
        parent's working directory, then runs the visualise command. Keeps the
        child faithful to the parent's session store and environment.

        Args:
            parent_session_id (str): Orchestrator session id to visualise.

        Returns:
            str: A ``bash``-compatible command string.
        """
        exports: list[str] = cls._env_export_prefix()
        visualize: str = shlex.join(cls._visualize_argv(parent_session_id=parent_session_id))
        cd_clause: str = f"cd {shlex.quote(os.getcwd())}"
        return " && ".join([*exports, cd_clause, visualize])

    @classmethod
    def _visualize_argv(cls, *, parent_session_id: str) -> list[str]:
        """Build the bare ``slo visualize`` argv (executable + flags).

        Prefers the installed ``slo`` console script; falls back to
        ``<python> -m src.cli`` for source checkouts where ``slo`` is not on
        ``PATH``.

        Args:
            parent_session_id (str): Orchestrator session id to visualise.

        Returns:
            list[str]: The visualise command argv.
        """
        base: list[str] = cls._slo_entrypoint()
        return [
            *base,
            "visualize",
            "--session",
            parent_session_id,
            "--follow",
        ]

    @staticmethod
    def _slo_entrypoint() -> list[str]:
        """Resolve how to invoke the ``slo`` CLI in the new window.

        Returns:
            list[str]: ``["slo"]`` when the console script is on ``PATH``,
                otherwise ``["<python>", "-m", "src.cli"]``.
        """
        slo_bin: Optional[str] = shutil.which("slo")
        if slo_bin is not None:
            return [slo_bin]
        return [sys.executable, "-m", "src.cli"]

    @staticmethod
    def _env_export_prefix() -> list[str]:
        """Build ``export KEY=VALUE`` clauses for the forwarded env allowlist.

        Only variables in :data:`_FORWARDED_ENV_KEYS` that are actually set are
        emitted — secrets are never forwarded into the world-readable argv.

        Returns:
            list[str]: One ``export`` clause per set allowlisted variable.
        """
        clauses: list[str] = []
        for key in _FORWARDED_ENV_KEYS:
            value: Optional[str] = os.environ.get(key)
            if value is None:
                continue
            clauses.append(f"export {key}={shlex.quote(value)}")
        return clauses

    # ── platform-specific argv ───────────────────────────────────────────────

    @classmethod
    def _macos_argv(cls, *, command: str) -> list[str]:
        """Build the ``osascript`` argv that opens the command in a mac terminal.

        Uses iTerm when ``SLO_VISUALIZER_TERMINAL_APP`` names it, otherwise the
        stock Terminal.app.

        Args:
            command (str): The shell command to run in the new window.

        Returns:
            list[str]: The ``osascript`` argv.
        """
        app_name: str = (cfg_module.VISUALIZER_TERMINAL_APP or "Terminal").strip()
        script: str = cls._applescript_for(app_name=app_name, command=command)
        return ["osascript", "-e", script]

    @classmethod
    def _applescript_for(cls, *, app_name: str, command: str) -> str:
        """Build the AppleScript that runs ``command`` in ``app_name``.

        Args:
            app_name (str): Terminal application name (``Terminal`` / ``iTerm``).
            command (str): Shell command to run in the new window.

        Returns:
            str: A single AppleScript program string.
        """
        escaped: str = cls._applescript_escape(text=command)
        if app_name.lower() in ("iterm", "iterm2", "iterm.app"):
            return (
                'tell application "iTerm"\n'
                "  create window with default profile\n"
                f'  tell current session of current window to write text "{escaped}"\n'
                "  activate\n"
                "end tell"
            )
        return f'tell application "{app_name}"\n' f'  do script "{escaped}"\n' "  activate\n" "end tell"

    @staticmethod
    def _applescript_escape(*, text: str) -> str:
        """Escape a shell command for embedding inside an AppleScript string.

        Backslashes and double quotes are the only characters AppleScript
        string literals treat specially.

        Args:
            text (str): Raw shell command.

        Returns:
            str: AppleScript-safe string contents (without surrounding quotes).
        """
        return text.replace("\\", "\\\\").replace('"', '\\"')

    @classmethod
    def _linux_argv(cls, *, command: str) -> Optional[list[str]]:
        """Build the terminal-emulator argv for Linux.

        Resolves the emulator from ``SLO_VISUALIZER_TERMINAL_APP`` or the probe
        list, then wraps the command so the window stays open after the
        visualiser exits.

        Args:
            command (str): The shell command to run in the new window.

        Returns:
            Optional[list[str]]: The emulator argv, or ``None`` when no
                emulator is available.
        """
        terminal: Optional[str] = cls._resolve_linux_terminal()
        if terminal is None:
            return None
        inner: str = f"{command}; exec bash"
        return [terminal, "-e", "bash", "-lc", inner]

    @classmethod
    def _resolve_linux_terminal(cls) -> Optional[str]:
        """Resolve a Linux terminal emulator executable path.

        Honours ``SLO_VISUALIZER_TERMINAL_APP`` first, then probes the
        candidate list.

        Returns:
            Optional[str]: Absolute path to a terminal emulator, or ``None``.
        """
        override: Optional[str] = cfg_module.VISUALIZER_TERMINAL_APP
        candidates: tuple[str, ...] = (
            (override,) + _LINUX_TERMINAL_CANDIDATES if override else _LINUX_TERMINAL_CANDIDATES
        )
        for name in candidates:
            resolved: Optional[str] = shutil.which(name)
            if resolved is not None:
                return resolved
        return None

    # ── spawn ────────────────────────────────────────────────────────────────

    @classmethod
    def _spawn_detached(cls, *, argv: list[str], spawn: Optional[SpawnCallable]) -> bool:
        """Spawn the terminal-launch argv, swallowing and logging any failure.

        Args:
            argv (list[str]): The command argv to spawn.
            spawn (Optional[SpawnCallable]): Override spawner; defaults to a
                detached ``subprocess.Popen``.

        Returns:
            bool: ``True`` when the spawn call succeeded, ``False`` otherwise.
        """
        spawner: SpawnCallable = spawn or cls._default_spawn
        try:
            spawner(argv)
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort; never crash the TUI.
            log_warning(msg="visualizer_launch_failed", error=str(exc), argv=argv)
            return False

    @staticmethod
    def _default_spawn(argv: list[str]) -> object:
        """Start the terminal-launch process fully detached from the TUI.

        Args:
            argv (list[str]): The command argv to spawn.

        Returns:
            object: The ``subprocess.Popen`` handle (unused by the caller).
        """
        return subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    @staticmethod
    def _auto_visualize_enabled() -> bool:
        """Return whether auto-launch is enabled, reading the live env value.

        Reads ``cfg("AUTO_VISUALIZE")`` so a test-time ``monkeypatch.setenv``
        of ``SLO_AUTO_VISUALIZE`` is respected without re-importing the module.

        Returns:
            bool: ``True`` when auto-visualise is enabled.
        """
        raw: Optional[str] = cfg_module.cfg("SLO_AUTO_VISUALIZE")
        if raw is not None:
            return raw.strip() not in ("0", "false", "no", "")
        return cfg_module.AUTO_VISUALIZE
