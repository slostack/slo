"""Conservative one-shot Herdr workflow viewer; created panes remain user-owned."""

import json
import asyncio
import functools
from collections.abc import Callable
import unicodedata
from typing import Optional

from src.agents.slo_agent.herdr.dao import (
    HerdrCommandResultDAO,
    HerdrCliCommandDAO,
    HerdrVisualizerAttemptDAO,
    HerdrVisualizerRequestDAO,
    HerdrViewerOperation,
    VisualizerLaunchOutcomeDAO,
)
from src.agents.slo_agent.herdr.service import HerdrCliTransport, HerdrTaskJoin
from src.agents.slo_agent.sessions.identity import is_canonical_uuid_session_id


class HerdrVisualizerLauncher:
    """Retain viewer attempts for one parent/session lifetime."""

    def __init__(
        self, *, transport: HerdrCliTransport, owner_pane_id: str, authority: Callable[[], bool]
    ) -> None:
        """Bind inert viewer dependencies for one session-owned lifetime.

        Args:
            transport (HerdrCliTransport): Reporter-owned shared transport; this
                launcher drains its launches but never closes the transport.
            owner_pane_id (str): Captured parent pane, never current-focus discovery.
            authority (Callable[[], bool]): Nonthrowing synchronous live predicate,
                checked again under the transport lock before each command.
        """
        self._transport = transport
        self._owner_pane_id = owner_pane_id
        self._authority = authority
        self._closing = False
        self._close_task: Optional[asyncio.Task[None]] = None
        self._attempt_by_parent: dict[str, HerdrVisualizerAttemptDAO] = {}
        self._pending_by_parent: dict[str, asyncio.Task[VisualizerLaunchOutcomeDAO]] = {}

    async def close(self) -> None:
        """Revoke and join owned launches without closing transport or visible panes.

        The session calls this before reporter withdrawal. Repeated calls join
        the same cleanup task; pending launches are cancelled and joined, while
        attempted/known panes remain in the lifetime ledger for manual recovery.

        Raises:
            asyncio.CancelledError: Only after all owned launch tasks are terminal.
        """
        self._closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(coro=self._close_once())
        cancelled = await HerdrTaskJoin.wait(task=self._close_task)
        self._close_task.result()
        if cancelled:
            raise asyncio.CancelledError

    async def _close_once(self) -> None:
        """Cancel each shared launch once and retain the registry throughout drain."""
        tasks = tuple(self._pending_by_parent.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def invoke(self, *, request: HerdrVisualizerRequestDAO) -> VisualizerLaunchOutcomeDAO:
        """Join shared work; caller cancellation does not cancel the owned launch.

        Call on the owning event loop after session eligibility validation.
        Closing returns skipped and absent live authority returns failed without
        creating a task. Concurrent callers for one parent share the first
        request's task; the session must retain and close this launcher.

        Args:
            request (HerdrVisualizerRequestDAO): Session-validated eligible parent
                and captured history root. Eligibility is the session's responsibility.

        Returns:
            VisualizerLaunchOutcomeDAO: Submission or manual-recovery evidence,
                never viewer liveness. One attempted split/run per parent survives
                failure and cancellation; later calls never focus or retry panes.

        Raises:
            asyncio.CancelledError: This waiter was cancelled; close owns shared work.
        """
        if self._closing:
            return VisualizerLaunchOutcomeDAO(status="skipped")
        if not self._authority():
            return VisualizerLaunchOutcomeDAO(status="failed")
        task = self._pending_by_parent.get(request.parent_session_id)
        if task is None:
            task = asyncio.create_task(coro=self._launch_or_reuse(request=request))
            self._pending_by_parent[request.parent_session_id] = task
            task.add_done_callback(
                functools.partial(self._on_launch_done, parent_session_id=request.parent_session_id)
            )
        return await asyncio.shield(arg=task)

    def _on_launch_done(
        self, task: asyncio.Task[VisualizerLaunchOutcomeDAO], *, parent_session_id: str
    ) -> None:
        """Retrieve completion and remove only the identical registered task."""
        if not task.cancelled():
            task.exception()
        if self._pending_by_parent.get(parent_session_id) is task:
            del self._pending_by_parent[parent_session_id]

    async def _launch_or_reuse(self, *, request: HerdrVisualizerRequestDAO) -> VisualizerLaunchOutcomeDAO:
        """Reserve before split or return a retained manual-selection outcome."""
        attempt = self._attempt_by_parent.get(request.parent_session_id)
        if attempt is not None:
            return VisualizerLaunchOutcomeDAO(
                status="reused" if attempt.state == "pane_known" else "failed", pane_id=attempt.pane_id
            )
        self._attempt_by_parent[request.parent_session_id] = HerdrVisualizerAttemptDAO(
            state="split_attempted"
        )
        return await self._split_and_submit(request=request)

    async def _split_and_submit(self, *, request: HerdrVisualizerRequestDAO) -> VisualizerLaunchOutcomeDAO:
        """Retain every possible effect; cancellation never grants another attempt."""
        parent = request.parent_session_id
        try:
            result = await self._send_viewer_operation(parent_session_id=parent, operation="split")
            pane_id = self._parse_split_pane_id(result=result)
            if pane_id is None:
                return self._mark_uncertain(parent_session_id=parent)
            previous = self._attempt_by_parent[parent]
            self._attempt_by_parent[parent] = previous.model_copy(
                update={"state": "pane_known", "pane_id": pane_id}
            )
            return await self._label_and_submit(parent_session_id=parent, pane_id=pane_id)
        except asyncio.CancelledError:
            self._mark_uncertain(parent_session_id=parent)
            raise
        except Exception:
            return self._mark_uncertain(parent_session_id=parent)

    def _mark_uncertain(self, *, parent_session_id: str) -> VisualizerLaunchOutcomeDAO:
        """Preserve known targets and consumed operations after an ambiguous failure."""
        previous = self._attempt_by_parent[parent_session_id]
        if previous.state != "pane_known":
            self._attempt_by_parent[parent_session_id] = previous.model_copy(update={"state": "uncertain"})
        return VisualizerLaunchOutcomeDAO(status="failed", pane_id=previous.pane_id)

    async def _label_and_submit(self, *, parent_session_id: str, pane_id: str) -> VisualizerLaunchOutcomeDAO:
        """Continue after rejected labeling; successful input means queued, not painted."""
        await self._send_viewer_operation(parent_session_id=parent_session_id, operation="rename")
        result = await self._send_viewer_operation(parent_session_id=parent_session_id, operation="run")
        return VisualizerLaunchOutcomeDAO(
            status="submitted" if result.outcome.status == "ok" and not self._transport.closed else "failed",
            pane_id=pane_id,
        )

    async def _send_viewer_operation(
        self, *, parent_session_id: str, operation: HerdrViewerOperation
    ) -> HerdrCommandResultDAO:
        """Send once through the shared lock using freshly captured reservation identity."""
        attempt = self._attempt_by_parent[parent_session_id]
        command = self._viewer_command(
            parent_session_id=parent_session_id, operation=operation, attempt=attempt
        )
        admission = HerdrViewerAdmission(
            launcher=self, parent_session_id=parent_session_id, attempt=attempt, operation=operation
        )
        return await self._transport.invoke(command=command, admission=admission)

    def _admit_viewer_operation(
        self,
        *,
        parent_session_id: str,
        attempt: HerdrVisualizerAttemptDAO,
        operation: HerdrViewerOperation,
    ) -> bool:
        """Consume current one-shot authority synchronously under the transport lock."""
        if self._closing or not self._authority():
            return False
        if self._attempt_by_parent.get(parent_session_id) is not attempt:
            return False
        if operation in attempt.admitted_operations:
            return False
        if operation != "split" and attempt.state != "pane_known":
            return False
        self._attempt_by_parent[parent_session_id] = attempt.model_copy(
            update={"admitted_operations": attempt.admitted_operations | frozenset((operation,))}
        )
        return True

    def _viewer_command(
        self,
        *,
        parent_session_id: str,
        operation: HerdrViewerOperation,
        attempt: HerdrVisualizerAttemptDAO,
    ) -> HerdrCliCommandDAO:
        """Build fixed argv without shell quoting or caller-provided command text.

        Args:
            parent_session_id (str): Canonical opaque workflow identity.
            operation (HerdrViewerOperation): One supported pane operation.
            attempt (HerdrVisualizerAttemptDAO): Current reservation.

        Returns:
            HerdrCliCommandDAO: Exact semantic argv for the shared transport.

        Raises:
            ValueError: Invalid identity or missing destination pane.
        """
        if not is_canonical_uuid_session_id(value=parent_session_id):
            raise ValueError("Invalid workflow identity.")
        if operation == "split":
            return HerdrCliCommandDAO(
                argv=("pane", "split", "--pane", self._owner_pane_id, "--direction", "right", "--no-focus"),
                capture_json=True,
            )
        if attempt.pane_id is None:
            raise ValueError("Missing viewer pane.")
        if operation == "rename":
            return HerdrCliCommandDAO(
                argv=("pane", "rename", attempt.pane_id, f"Slo workflow {parent_session_id[:8]}")
            )
        return HerdrCliCommandDAO(
            argv=("pane", "run", attempt.pane_id, f"slo visualize --session {parent_session_id} --follow")
        )

    @classmethod
    def _parse_split_pane_id(cls, *, result: HerdrCommandResultDAO) -> Optional[str]:
        """Accept only bounded successful stdout in the documented envelope.

        Args:
            result (HerdrCommandResultDAO): Private transport result.

        Returns:
            Optional[str]: Validated pane identity, never inferred from other text.
        """
        if result.outcome.status != "ok" or result.json_bytes is None:
            return None
        try:
            payload: object = json.loads(result.json_bytes)
        except (ValueError, UnicodeError):
            return None
        if not isinstance(payload, dict) or "error" in payload:
            return None
        envelope = payload.get("result")
        if not isinstance(envelope, dict):
            return None
        pane = envelope.get("pane")
        if not isinstance(pane, dict):
            return None
        pane_id = pane.get("pane_id")
        if not isinstance(pane_id, str) or not pane_id:
            return None
        if any(unicodedata.category(character).startswith("C") for character in pane_id):
            return None
        try:
            return pane_id if len(pane_id.encode(encoding="utf-8")) <= 128 else None
        except UnicodeError:
            return None


class HerdrViewerAdmission:
    """Bind one transport invocation to the launcher's immutable reservation."""

    def __init__(
        self,
        *,
        launcher: HerdrVisualizerLauncher,
        parent_session_id: str,
        attempt: HerdrVisualizerAttemptDAO,
        operation: HerdrViewerOperation,
    ) -> None:
        """Capture one immutable viewer reservation before transport lock wait.

        Args:
            launcher (HerdrVisualizerLauncher): Session-owned attempt ledger.
            parent_session_id (str): Validated parent identity.
            attempt (HerdrVisualizerAttemptDAO): Exact current reservation object.
            operation (HerdrViewerOperation): Split, rename or run authority to consume.
        """
        self._launcher = launcher
        self._parent_session_id = parent_session_id
        self._attempt = attempt
        self._operation = operation
        self._attempted = False
        self._admitted = False
        self._completed = False

    def try_admit(self) -> bool:
        """Consume authority once under the shared transport lock.

        Returns:
            bool: Whether the exact attempt and live reporter authority permit
                this operation; refusal also consumes this admission object.
        """
        if self._attempted:
            return False
        self._attempted = True
        self._admitted = self._launcher._admit_viewer_operation(
            parent_session_id=self._parent_session_id, attempt=self._attempt, operation=self._operation
        )
        return self._admitted

    def complete(self, *, result: HerdrCommandResultDAO) -> None:
        """Retain consumed operations regardless of acknowledgement or cancellation.

        Args:
            result (HerdrCommandResultDAO): Terminal transport evidence; no result
                permits another split/run. Unadmitted/repeated completion is ignored.
        """
        if not self._admitted or self._completed:
            return
        self._completed = True
