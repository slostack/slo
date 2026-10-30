"""Session-owned editor request mechanics; visible panes belong to the user."""

from __future__ import annotations

import asyncio
import shlex
import unicodedata
from collections.abc import Callable
from typing import Optional, Protocol

from .dao import HerdrCliCommandDAO, HerdrCommandAdmission, HerdrCommandResultDAO, VisualizerLaunchOutcomeDAO
from .service import HerdrTaskJoin
from .visualizer import HerdrVisualizerLauncher


class EditorPaneTransport(Protocol):
    """Reporter-owned serialized Herdr command boundary."""

    @property
    def closed(self) -> bool:
        """Whether the reporter sealed this shared transport."""
        ...

    async def invoke(
        self, *, command: HerdrCliCommandDAO, admission: HerdrCommandAdmission
    ) -> HerdrCommandResultDAO:
        """Recheck admission under the shared lock and return bounded evidence."""
        ...


class HerdrEditorLauncher:
    """Split beside the captured owner and submit one safely quoted editor command."""

    def __init__(
        self, *, transport: EditorPaneTransport, owner_pane_id: str, authority: Callable[[], bool]
    ) -> None:
        """Bind session-owned transport/authority without ambient discovery or effects.

        Args:
            transport: Reporter-owned shared command lock and process lifetime.
            owner_pane_id: Captured Slo pane, unaffected by focus drift.
            authority: Live reporter permission, rechecked for each locked operation.
        """
        self._transport = transport
        self._owner_pane_id = owner_pane_id
        self._authority = authority
        self._closing = False
        self._pending: set[asyncio.Task[VisualizerLaunchOutcomeDAO]] = set()

    async def invoke(self, *, argv: tuple[str, ...]) -> VisualizerLaunchOutcomeDAO:
        """Own one split/run attempt; never retry ambiguous effects or claim readiness.

        Args:
            argv: Validated editor executable, --, absolute file path.

        Returns:
            Submission/failure evidence only; known panes remain user-owned.
        """
        if not self._permitted() or not self._safe_line_argv(argv=argv):
            return VisualizerLaunchOutcomeDAO(status="failed")
        task = asyncio.create_task(coro=self._split_and_submit(argv=argv))
        self._pending.add(task)
        try:
            return await asyncio.shield(arg=task)
        finally:
            # Cancellation cannot release an operation still using shared transport.
            await HerdrTaskJoin.wait(task=task)
            if not task.cancelled():
                task.exception()
            self._pending.discard(task)

    def _permitted(self) -> bool:
        """Read live session authority; only close revokes local permission."""
        return not self._closing and not self._transport.closed and self._authority()

    @staticmethod
    def _safe_line_argv(*, argv: tuple[str, ...]) -> bool:
        """Refuse controls: pane run sends a line through the terminal shell editor.

        Args:
            argv: Editor command, not an arbitrary shell program.

        Returns:
            Whether quoting can represent this bounded single-line command safely.
        """
        return (
            len(argv) == 3
            and argv[1] == "--"
            and all(argv)
            and not any(unicodedata.category(char).startswith("C") for word in argv for char in word)
        )

    async def _split_and_submit(self, *, argv: tuple[str, ...]) -> VisualizerLaunchOutcomeDAO:
        """Keep known pane evidence on any run error; never delete or resend input."""
        pane_id: Optional[str] = None
        try:
            pane_id = await self._split_pane()
            if pane_id is None:
                return VisualizerLaunchOutcomeDAO(status="failed")
            return await self._submit_to_pane(argv=argv, pane_id=pane_id)
        except Exception:
            return VisualizerLaunchOutcomeDAO(status="failed", pane_id=pane_id)

    async def _split_pane(self) -> Optional[str]:
        """Request an unfocused adjacent pane and decode only confirmed pane identity."""
        split = await self._send(
            command=HerdrCliCommandDAO(
                argv=("pane", "split", "--pane", self._owner_pane_id, "--direction", "right", "--no-focus"),
                capture_json=True,
            )
        )
        return HerdrVisualizerLauncher._parse_split_pane_id(result=split)

    async def _submit_to_pane(self, *, argv: tuple[str, ...], pane_id: str) -> VisualizerLaunchOutcomeDAO:
        """Submit one literal command with fresh authority; report submission, not readiness."""
        run = await self._send(command=HerdrCliCommandDAO(argv=("pane", "run", pane_id, shlex.join(argv))))
        return VisualizerLaunchOutcomeDAO(
            status="submitted" if run.outcome.status == "ok" and not self._transport.closed else "failed",
            pane_id=pane_id,
        )

    async def _send(self, *, command: HerdrCliCommandDAO) -> HerdrCommandResultDAO:
        """Attach fresh one-shot live authority to each shared-lock invocation."""
        return await self._transport.invoke(
            command=command, admission=EditorPaneAdmission(authority=self._permitted)
        )

    async def close(self) -> None:
        """Revoke and cancel/join command mechanics, never close panes or transport."""
        self._closing = True
        tasks = tuple(self._pending)
        for task in tasks:
            task.cancel()
        for task in tasks:
            await HerdrTaskJoin.wait(task=task)


class EditorPaneAdmission:
    """One-use permission checked synchronously under the reporter transport lock."""

    def __init__(self, *, authority: Callable[[], bool]) -> None:
        """Capture a live predicate rather than an ambient/cached permission."""
        self._authority = authority
        self._attempted = False

    def try_admit(self) -> bool:
        """Consume this operation once, even when authority was revoked."""
        if self._attempted:
            return False
        self._attempted = True
        return self._authority()

    def complete(self, *, result: HerdrCommandResultDAO) -> None:
        """Never renew submission authority after success, failure or uncertainty."""
        del result
