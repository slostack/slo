"""WorkflowProgressComponent — the one composed owner of workflow-progress presentation (feature 96.f.1).

The app composes one ``WorkflowProgressComponent`` below the editor. It contains the
existing ``SubAgentFleetPanel``, owns one observation-lifetime
``WorkflowProgressUpdatesAdapter`` per ``bind_observation``, and carries the
list apply/reset mechanics that used to live on ``SloTUI``. The app keeps the
coordinator and the service as the observation and control owners; progress and
abort-confirmation screens stay on Textual's global screen stack. Presentation
never cancels execution, redirects an abort, or paints a retired session's
results into a new owner.
"""

from __future__ import annotations

import asyncio
from importlib.resources import files
from typing import ClassVar, Optional

from textual.app import ComposeResult
from textual.containers import Vertical

from src.tui.components.workflow_progress.adapters.workflow_progress import (
    WorkflowProgressUpdatesAdapter,
)
from src.tui.components.workflow_progress.commands import WorkflowProgressCommand, PresentSessionsDAO
from src.tui.components.workflow_progress.events import ConfirmAbortDAO
from src.tui.components.workflow_progress.host import WorkflowProgressHost
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.workflows.dao import WorkflowSessionSnapshotDAO
from src.tui.workflows.progress_coordinator import WorkflowProgressSink

__all__ = ["WorkflowProgressComponent"]


class WorkflowProgressComponent(Vertical):
    """Show running agents and their workflow progress.

    Connect one progress listener at a time and clean it up before connecting
    another. If cleanup fails, finish that cleanup before accepting a new
    listener. Stay mounted when the user starts a new session, but do not
    accept new listeners after the component is closed."""

    DEFAULT_CSS: ClassVar[str] = (
        files("src.tui.components.workflow_progress").joinpath("css.tcss").read_text(encoding="utf-8")
    )

    SCOPED_CSS: ClassVar[bool] = False
    """Textual's default CSS scoping would prefix every rule with the component
    type, breaking the deliberate ``Screen``-level breakpoint selectors."""

    def __init__(self, *, host: WorkflowProgressHost, panel: Optional[SubAgentFleetPanel] = None) -> None:
        """Create the session panel without starting any progress listeners."""
        super().__init__()
        self._host: WorkflowProgressHost = host
        self._fleet_panel: SubAgentFleetPanel = panel if panel is not None else SubAgentFleetPanel()
        self._bound_sink: Optional[WorkflowProgressUpdatesAdapter] = None
        self._retiring: bool = False
        self._retirement_task: Optional[asyncio.Task[None]] = None
        self._retirement_failure: Optional[BaseException] = None
        self._delivery_closed: bool = False
        self._delivery_lock = asyncio.Lock()
        self._binding_version = 0
        self._resetting = 0
        self._close_task: Optional[asyncio.Task[None]] = None
        self.display = False

    def _ensure_workflow_progress_open(self) -> None:
        """Reject closed component delivery before inspecting native mount or loop state."""
        if self._delivery_closed:
            raise RuntimeError("Workflow progress component is closed")

    def _ensure_workflow_progress_mounted(self) -> None:
        """Require native mounting before accessing the owning application."""
        if not self.is_mounted:
            raise RuntimeError("Workflow progress delivery requires the mounted UI loop")

    def _ensure_workflow_progress_ui_loop(self) -> None:
        """Raise RuntimeError unless the caller uses the mounted owner's event loop."""
        if asyncio.get_running_loop() is not self.app._loop:
            raise RuntimeError("Workflow progress delivery requires the mounted UI loop")

    def _get_binding_version(self) -> int:
        """Return the row-presentation lifetime captured before waiting for delivery."""
        return self._binding_version

    def _update_binding_version(self) -> None:
        """Retire queued row commands before reset, close or sink replacement."""
        self._binding_version += 1

    def _is_binding_version(self, *, expected_version: int) -> bool:
        """Compare a saved binding lifetime without changing or retiring its sink."""
        return expected_version == self._binding_version

    async def handle(self, *, command: WorkflowProgressCommand) -> None:
        """Apply a supported progress command on the UI loop and report errors to the caller."""
        self._ensure_workflow_progress_open()
        self._ensure_workflow_progress_mounted()
        self._ensure_workflow_progress_ui_loop()
        if isinstance(command, ConfirmAbortDAO):
            if self._bound_sink is not None and not self._retiring and not self._resetting:
                await self._bound_sink.handle(event=command)
            return
        binding_version = self._get_binding_version()
        async with self._delivery_lock:
            self._ensure_workflow_progress_open()
            self._ensure_workflow_progress_mounted()
            self._ensure_workflow_progress_ui_loop()
            if not self._is_binding_version(expected_version=binding_version) or self._resetting:
                raise RuntimeError("Workflow command belongs to a retired presentation")
            if not isinstance(command, PresentSessionsDAO):
                raise TypeError(f"Unsupported workflow command: {type(command).__name__}")
            await self._present_session_rows(sink=command.sink, snapshot=command.snapshot)

    async def reset(self) -> None:
        """Clear displayed progress while keeping the same progress listener connected."""
        self._ensure_workflow_progress_open()
        self._ensure_workflow_progress_mounted()
        self._ensure_workflow_progress_ui_loop()
        self._update_binding_version()
        self._resetting += 1
        task = asyncio.create_task(self._reset_bound_presentation())
        try:
            await WorkflowProgressUpdatesAdapter._join_retirement(task=task)
        finally:
            self._resetting -= 1

    async def _reset_bound_presentation(self) -> None:
        """Wait for adapter updates outside the component lock, then clear the session rows."""
        if self._bound_sink is not None:
            await self._bound_sink.reset()
        async with self._delivery_lock:
            await self._clear_session_rows()

    async def close(self) -> None:
        """Finish display cleanup without closing the app or its services. Allow failed cleanup to be retried."""
        self._delivery_closed = True
        self._update_binding_version()
        if self._bound_sink is not None:
            self._bound_sink.begin_close()
        if self._close_task is None or (self._close_task.done() and self._close_task.exception() is not None):
            self._close_task = asyncio.create_task(self._close_presentation())
        await WorkflowProgressUpdatesAdapter._join_retirement(task=self._close_task)

    async def _close_presentation(self) -> None:
        """Stop the connected listener before finishing session-row cleanup."""
        if self._bound_sink is not None:
            await self.retire_observation(sink=self._bound_sink)
        else:
            # Without a binding, the previous row cleanup has already finished.
            async with self._delivery_lock:
                pass

    def compose(self) -> ComposeResult:
        """Add the session panel to this component."""
        yield self._fleet_panel

    def bind_observation(self) -> WorkflowProgressSink:
        """Create and return one new progress adapter without reading any data.

        Reject the request if an adapter is still connected or being cleaned up,
        previous cleanup failed, or this component is closed. Give the coordinator
        the new adapter directly so old updates cannot reach a replacement.
        """
        if self._delivery_closed:
            raise RuntimeError("Workflow progress component is closed")
        if self._retirement_failure is not None or self._resetting:
            raise RuntimeError("Workflow observation binding unavailable")
        if self._bound_sink is not None:
            raise RuntimeError("Workflow observation already bound")
        sink: WorkflowProgressUpdatesAdapter = WorkflowProgressUpdatesAdapter.register(
            host=self._host, presenter=self
        )
        self._bound_sink = sink
        return sink

    async def retire_observation(self, *, sink: WorkflowProgressSink) -> None:
        """Disconnect the specified adapter and wait for its cleanup.

        Ignore adapters that are not the current binding. Concurrent callers wait
        for the same cleanup task. Release the binding only after cleanup succeeds;
        on failure, keep it reserved so a later call can retry safely.
        """
        if sink is not self._bound_sink:
            return
        if self._retirement_task is None or (
            self._retirement_task.done() and self._retirement_task.exception() is not None
        ):
            self._retiring = True
            self._bound_sink.begin_close()
            self._update_binding_version()
            self._retirement_task = asyncio.create_task(self._reset_presentation(sink=self._bound_sink))
        await WorkflowProgressUpdatesAdapter._join_retirement(task=self._retirement_task)

    def focus_sessions(self) -> None:
        """Focus the session list when it has rows; safe whether or not a sink is bound."""
        self._fleet_panel.focus_sessions()

    def is_session_list_focused(self) -> bool:
        """Return whether the session list (or one of its rows) holds focus.

        Returns:
            bool: True when the composed panel or a descendant is focused.
        """
        return self._fleet_panel.has_focus or self._fleet_panel.has_focus_within

    def is_session_list_visible(self) -> bool:
        """Return whether the panel is displaying session rows.

        Returns:
            bool: True while rows are mounted and the panel is displayed.
        """
        return bool(self._fleet_panel.display)

    async def _present_session_rows(
        self, *, sink: WorkflowProgressSink, snapshot: WorkflowSessionSnapshotDAO
    ) -> None:
        """Display rows only for the current, open adapter.

        Recheck the binding after waiting for the panel update. If the list becomes
        empty while it has focus on the base screen, return focus to the prompt.
        """
        if sink is not self._bound_sink or self._retiring or self._delivery_closed:
            return
        list_focused: bool = self.is_session_list_focused()
        try:
            await self._fleet_panel.apply_snapshot(snapshot=snapshot)
        except BaseException:
            # The panel update continues even if this caller is cancelled.
            # Match the wrapper’s visibility to the panel’s actual visibility
            # before passing the error back to the caller.
            if sink is self._bound_sink and not self._retiring:
                self.display = self._fleet_panel.display
            raise
        if sink is not self._bound_sink or self._retiring:
            return
        self.display = self._fleet_panel.display
        if not snapshot.rows and list_focused:
            self._host.return_prompt_focus()

    async def _reset_presentation(self, *, sink: WorkflowProgressSink) -> None:
        """Clear the retiring adapter’s rows before allowing a new adapter to bind.

        Wait for pending panel updates, hide the wrapper, and return focus if the
        list had it. Keep the binding reserved if cleanup fails so it can be retried.
        """
        try:
            await sink.close()
            async with self._delivery_lock:
                await self._clear_session_rows()
        except BaseException as error:
            self._retirement_failure = error
            raise
        self._bound_sink = None
        self._retiring = False
        self._retirement_failure = None
        self._retirement_task = None

    async def _clear_session_rows(self) -> None:
        """Wait for accepted row updates, empty the list, and return focus only if the list had it."""
        list_focused = self.is_session_list_focused()
        try:
            await self._fleet_panel.reset()
        finally:
            self.display = self._fleet_panel.display
        if list_focused:
            self._host.return_prompt_focus()

    async def on_unmount(self) -> None:
        """Close this component and wait for any pending listener cleanup.

        Do not close services or cancel agents; the app owns those operations.
        """
        await self.close()
