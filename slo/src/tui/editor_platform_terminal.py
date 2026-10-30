"""Bounded editor destinations: active tmux or an existing owning iTerm2 window."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from collections.abc import Mapping
from typing import Optional, Protocol

from src.agents.slo_agent.herdr.service import HerdrTaskJoin


class EditorTerminalProcess(Protocol):
    """Finite process request boundary; no Slo stdin or shell is inherited."""

    def run(self, *, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Execute one argv and return its exit/stdout evidence."""
        ...


class LocalEditorTerminalProcess:
    """Run terminal APIs with a finite wait and private diagnostic capture."""

    def run(self, *, argv: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        """Execute without a shell; timeout kills/reaps only this request process.

        Args:
            argv: Terminal API executable and literal arguments.

        Returns:
            Exit status and captured output, not editor readiness.

        Raises:
            OSError: The terminal API executable cannot run.
            subprocess.TimeoutExpired: Submission outcome may be ambiguous.
        """
        return subprocess.run(
            args=argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5, check=False
        )


class PlatformEditorTerminal:
    """Capture terminal identity once; never choose a focused window at launch time.

    The app retains the caller task. Each off-thread API call is joined before
    cancellation propagates; validation cancellation cannot submit a later call.
    Created surfaces are user-owned and are never closed, retried or redirected.
    """

    def __init__(
        self,
        *,
        environment: Optional[Mapping[str, str]] = None,
        platform: Optional[str] = None,
        process: Optional[EditorTerminalProcess] = None,
    ) -> None:
        """Capture inert owner hints without probing terminals or creating surfaces.

        Args:
            environment: Launch environment; copied now, defaulting to os.environ.
            platform: Host platform, defaulting to sys.platform.
            process: Injected finite process boundary, defaulting to local execution.
        """
        self._environment = dict(os.environ if environment is None else environment)
        self._platform = sys.platform if platform is None else platform
        self._process = process or LocalEditorTerminalProcess()

    async def submit(self, *, argv: tuple[str, ...]) -> str:
        """Select active tmux before iTerm2, with no fallback after selection.

        Args:
            argv: Validated editor executable, -- and absolute file path.

        Returns:
            Fixed safe impossibility, failure or submission-only notice.

        Raises:
            asyncio.CancelledError: After the in-progress API call is joined.
        """
        if not argv or any(unicodedata.category(char).startswith("C") for arg in argv for char in arg):
            return "Editor launch refused: terminal command contains control characters."
        try:
            if self._environment.get("TMUX"):
                return await self._submit_tmux(argv=argv)
            if self._supports_iterm():
                return await self._submit_iterm(argv=argv)
        except Exception:
            return "Editor terminal launch failed; no alternate terminal was opened."
        return "Opening an adjacent terminal tab is not possible in the current setup."

    async def _request(self, *, argv: tuple[str, ...]) -> str:
        """Join one finite API call; consume output before reporting cancellation.

        Args:
            argv: Literal API request.

        Returns:
            Successful stdout, kept internal to the selected backend.

        Raises:
            asyncio.CancelledError: After request completion, before any next step.
            RuntimeError: Nonzero API exit; private stderr is never exposed.
        """
        task = asyncio.create_task(coro=asyncio.to_thread(self._process.run, argv=argv))
        cancelled = await HerdrTaskJoin.wait(task=task)
        if cancelled:
            task.exception()
            raise asyncio.CancelledError
        result = task.result()
        if result.returncode != 0:
            raise RuntimeError("Terminal API request failed")
        return result.stdout.strip()

    async def _submit_tmux(self, *, argv: tuple[str, ...]) -> str:
        """Verify the captured pane on its server, then insert a detached new window."""
        socket, pane = self._tmux_owner()
        owner = await self._request(
            argv=(
                "tmux",
                "-S",
                socket,
                "display-message",
                "-p",
                "-t",
                pane,
                "#{session_id} #{window_id} #{pane_id}",
            )
        )
        target = self._tmux_target(owner=owner, pane=pane)
        await self._request(
            argv=("tmux", "-S", socket, "new-window", "-a", "-d", "-t", target, shlex.join(argv))
        )
        return "Editor command submitted to tmux new window (not a GUI tab); readiness not confirmed."

    def _tmux_owner(self) -> tuple[str, str]:
        """Reject incomplete/stale environment hints rather than probing ambient focus."""
        socket = self._environment["TMUX"].rsplit(sep=",", maxsplit=2)[0]
        pane = self._environment.get("TMUX_PANE", "")
        if not socket.startswith("/") or not re.fullmatch(pattern=r"%\d+", string=pane):
            raise ValueError("No captured tmux owner")
        return socket, pane

    @staticmethod
    def _tmux_target(*, owner: str, pane: str) -> str:
        """Accept only server-resolved stable IDs for the exact captured pane."""
        match = re.fullmatch(pattern=r"(\$\d+) (@\d+) (%\d+)", string=owner)
        if match is None or match[3] != pane:
            raise ValueError("Captured tmux pane is not active")
        return match[1] + ":" + match[2]

    def _supports_iterm(self) -> bool:
        """Require macOS iTerm2 and its inherited session identity, not installation."""
        return (
            self._platform == "darwin"
            and self._environment.get("TERM_PROGRAM") == "iTerm.app"
            and bool(self._environment.get("ITERM_SESSION_ID"))
        )

    async def _submit_iterm(self, *, argv: tuple[str, ...]) -> str:
        """Use iTerm2's supported AppleScript create-tab API in the owning window only."""
        identity = self._environment["ITERM_SESSION_ID"].split(":")[-1]
        if not re.fullmatch(pattern=r"[A-Za-z0-9-]+", string=identity):
            raise ValueError("Invalid iTerm2 session identity")
        await self._request(
            argv=("/usr/bin/osascript", "-e", self._iterm_script(), "--", identity, shlex.join(argv))
        )
        return "Editor command submitted to iTerm2 new tab; readiness not confirmed."

    @staticmethod
    def _iterm_script() -> str:
        """Keep command/identity in run argv, never interpolate AppleScript source.

        iTerm2's session unique ID identifies the owning window even after focus
        changes. No matching session/window means error, never create-window.
        """
        return """on run arguments
    set ownerID to item 1 of arguments
    set editorCommand to item 2 of arguments
    if application id "com.googlecode.iterm2" is not running then
        error "iTerm2 is not running"
    end if
    tell application id "com.googlecode.iterm2"
        repeat with ownerWindow in windows
            repeat with ownerTab in tabs of ownerWindow
                repeat with ownerSession in sessions of ownerTab
                    if unique ID of ownerSession is ownerID then
                        tell ownerWindow
                            create tab with default profile command editorCommand
                        end tell
                        return "submitted"
                    end if
                end repeat
            end repeat
        end repeat
        error "Owning iTerm2 window unavailable"
    end tell
end run"""
