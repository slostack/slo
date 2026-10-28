"""Literal file validation and local editor submission, never content attachment."""

from __future__ import annotations

import asyncio
import shlex
import shutil
from pathlib import Path
from typing import Optional, Protocol

from src.agents.slo_agent.herdr.service import HerdrTaskJoin
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.editor_platform_terminal import PlatformEditorTerminal


class EditorExecutableLookup(Protocol):
    """Resolve the editor without running it."""

    def __call__(self, *, cmd: str) -> Optional[str]:
        """Return an executable path or None for an unavailable editor."""
        ...


class EditorTerminal(Protocol):
    """Submit validated argv to a separate user-owned terminal surface."""

    async def submit(self, *, argv: tuple[str, ...], session: SloAgentSession) -> str:
        """Return safe submission evidence, not editor readiness."""
        ...


class SessionEditorTerminal:
    """Delegate terminal authority to the captured session, not ambient settings."""

    def __init__(self, *, platform_terminal: Optional[PlatformEditorTerminal] = None) -> None:
        """Bind captured platform identity; Herdr authority remains reporter-owned.

        Args:
            platform_terminal: Inert platform boundary; defaults to captured host hints.
        """
        self._platform_terminal = platform_terminal or PlatformEditorTerminal()

    async def submit(self, *, argv: tuple[str, ...], session: SloAgentSession) -> str:
        """Prefer session Herdr authority; selected-backend failure never falls back.

        Args:
            argv: Validated literal editor command.
            session: Captured session owning Herdr admission and transport.

        Returns:
            Safe submission-only or failed/impossible notice.
        """
        if session.workflow_visualizer_destination == "platform":
            return await self._platform_terminal.submit(argv=argv)
        outcome = await session.open_editor(argv=argv)
        if outcome.status == "submitted":
            return "Editor command submitted to Herdr; readiness not confirmed. Select the new pane manually."
        return "Herdr editor launch failed or authority unavailable; no alternate terminal was opened."


class EditorRequestError(Exception):
    """A fixed, operator-safe validation diagnostic."""


class EditorLauncher:
    """Validate one literal file off-loop and submit it without owning the editor."""

    def __init__(
        self,
        *,
        terminal: Optional[EditorTerminal] = None,
        executable_lookup: Optional[EditorExecutableLookup] = None,
    ) -> None:
        """Bind inert launch boundaries; no files or terminal processes are opened.

        Args:
            terminal: Submission collaborator, defaulting to session authority.
            executable_lookup: Off-thread executable discovery, defaulting to PATH.
        """
        self._terminal = terminal or SessionEditorTerminal()
        self._executable_lookup = executable_lookup or shutil.which

    async def invoke(self, *, argument: str, session: SloAgentSession) -> str:
        """Resolve a literal path then submit; cancellation joins filesystem work.

        Args:
            argument: Raw single shell-style token, not evaluated by a shell.
            session: Captured selected session and cwd authority.

        Returns:
            Fixed safe validation/failure or submission notice; never file contents.
        """
        validation = asyncio.create_task(
            coro=asyncio.to_thread(self._validated_argv, argument=argument, workdir=session.workdir)
        )
        cancelled = await HerdrTaskJoin.wait(task=validation)
        if cancelled:
            validation.exception()
            raise asyncio.CancelledError
        try:
            argv = validation.result()
            return await self._terminal.submit(argv=argv, session=session)
        except EditorRequestError as error:
            return str(error)
        except Exception:
            return "Editor launch failed; no alternate terminal was opened."

    def _validated_argv(self, *, argument: str, workdir: Path) -> tuple[str, ...]:
        """Validate metadata only; never open/read the file or interpolate its name.

        Args:
            argument: One quoted/escaped path token.
            workdir: Session cwd, independent of process cwd.

        Returns:
            Absolute editor executable, option terminator and absolute file path.

        Raises:
            EditorRequestError: Invalid token, missing/non-file path or missing nvim.
        """
        token = self._validate_token(argument=argument)
        path = self._resolve_file(token=token, workdir=workdir)
        return (self._discover_executable(), "--", str(path))

    def _discover_executable(self) -> str:
        """Anchor PATH discovery to process cwd without dereferencing launcher symlinks.

        Returns:
            Absolute invocation spelling, independent of the destination terminal cwd.

        Raises:
            EditorRequestError: No editor was found on PATH.
        """
        discovery_cwd = Path.cwd()
        executable = self._executable_lookup(cmd="nvim")
        if executable is None:
            raise EditorRequestError("nvim is unavailable; install/configure it before using /code.")
        return str(discovery_cwd / executable)

    @staticmethod
    def _validate_token(*, argument: str) -> str:
        """Decode exactly one nonempty, NUL-free literal shell-style path token.

        Args:
            argument: Raw operator path; quoting is decoded, never evaluated.

        Returns:
            Validated literal token for filesystem resolution.

        Raises:
            EditorRequestError: Fixed usage diagnostic for malformed input.
        """
        try:
            tokens = shlex.split(s=argument)
        except ValueError:
            raise EditorRequestError("Usage: /code <file_path> (quote paths containing spaces).") from None
        if len(tokens) != 1 or not tokens[0] or "\x00" in tokens[0]:
            raise EditorRequestError("Usage: /code <file_path> (quote paths containing spaces).")
        return tokens[0]

    @staticmethod
    def _resolve_file(*, token: str, workdir: Path) -> Path:
        """Resolve a validated token against session cwd and require a regular file.

        Args:
            token: Literal validated path with optional home prefix.
            workdir: Captured session cwd, not executable discovery cwd.

        Returns:
            Absolute existing file path, following file symlinks.

        Raises:
            EditorRequestError: Fixed diagnostic for inaccessible/non-file targets.
        """
        try:
            path = Path(token).expanduser()
            path = (path if path.is_absolute() else workdir / path).resolve(strict=True)
            if path.is_file():
                return path
        except (OSError, RuntimeError, ValueError):
            pass
        raise EditorRequestError("/code requires an accessible existing file, not a directory.")
