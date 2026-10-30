"""WorkflowProgress — the one composed owner of workflow-progress presentation (feature 96.f.1).

The app composes one ``WorkflowProgress`` below the editor. It contains the
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
from src.tui.components.workflow_progress.host import WorkflowProgressHost
from src.tui.widgets.sub_agent_fleet_panel import SubAgentFleetPanel
from src.tui.workflows.dao import ChildAbortTargetDAO, WorkflowSessionSnapshotDAO
from src.tui.workflows.progress_coordinator import WorkflowProgressSink

__all__ = ["WorkflowProgress"]


class WorkflowProgress(Vertical):
    """Compose the fleet panel and own its observation-lifetime adapter.

    Invariants: at most one sink is bound or retiring at a time; the binding is
    released only after a successful, joined retirement; a failed retirement
    blocks binding permanently; a closed (unmounted) widget never binds again.
    The widget stays mounted across ``/new``; adapter disposal is irreversible.
    """

    DEFAULT_CSS: ClassVar[str] = (
        files("src.tui.components.workflow_progress").joinpath("css.tcss").read_text(encoding="utf-8")
    )

    SCOPED_CSS: ClassVar[bool] = False
    """Textual's default CSS scoping would prefix every rule with the component
    type, breaking the deliberate ``Screen``-level breakpoint selectors."""

    def __init__(self, *, host: WorkflowProgressHost) -> None:
        """Build the wrapper and its panel without starting any observation work.

        Args:
            host (WorkflowProgressHost): App-implemented global UI and control bridge.
        """
        super().__init__()
        self._host: WorkflowProgressHost = host
        self._fleet_panel: SubAgentFleetPanel = SubAgentFleetPanel()
        self._bound_sink: Optional[WorkflowProgressUpdatesAdapter] = None
        self._retiring: bool = False
        self._retirement_task: Optional[asyncio.Task[None]] = None
        self._retirement_failure: Optional[BaseException] = None
        self._closed: bool = False
        self.display = False

    def compose(self) -> ComposeResult:
        """Yield the single composed fleet panel."""
        yield self._fleet_panel

    def bind_observation(self) -> WorkflowProgressSink:
        """Bind one fresh observation-lifetime adapter to this component.

        Synchronous; starts no reads. The coordinator receives the returned sink
        directly, so it cannot forward old work into a successor.

        Returns:
            WorkflowProgressSink: The fresh adapter for this observation lifetime.

        Raises:
            RuntimeError: While a sink is bound or retiring, after a failed
                retirement, or after the widget is closed.
        """
        if self._closed or self._retirement_failure is not None:
            raise RuntimeError("Workflow observation binding unavailable")
        if self._bound_sink is not None:
            raise RuntimeError("Workflow observation already bound")
        sink: WorkflowProgressUpdatesAdapter = WorkflowProgressUpdatesAdapter(host=self._host, presenter=self)
        self._bound_sink = sink
        return sink

    async def retire_observation(self, *, sink: WorkflowProgressSink) -> None:
        """Retire the exact bound sink, joining any retirement already in progress.

        WHAT: A stale, foreign or already retired sink is a no-op and never
            resets current rows. The first caller for the bound sink disposes it
            synchronously, then starts the one tracked presentation reset;
            concurrent callers join the same task. The binding is released only
            on success; a failed reset keeps the binding reserved and is
            re-raised to later callers.
        WHO: ``SloTUI._dispose_workflow_observation``, after the captured
            coordinator and service close attempts.
        WHEN: Once per owner replacement or teardown; safe to repeat.

        Args:
            sink (WorkflowProgressSink): The exact sink ``bind_observation`` returned.

        Raises:
            BaseException: The recorded failure of a previous retirement attempt.
        """
        if sink is not self._bound_sink:
            return
        if self._retirement_failure is not None:
            raise self._retirement_failure
        if self._retirement_task is None:
            self._retiring = True
            self._bound_sink.dispose()
            self._retirement_task = asyncio.create_task(self._reset_presentation(sink=self._bound_sink))
        task: asyncio.Task[None] = self._retirement_task
        cancelled: bool = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        if cancelled:
            if not task.cancelled():
                task.exception()
            raise asyncio.CancelledError()
        task.result()

    def confirm_abort(self, *, target: ChildAbortTargetDAO) -> None:
        """Ask the bound sink to confirm the exact target the progress view displayed.

        No-op while unbound or retiring, so a request arriving during teardown
        never reaches a disposed adapter.

        Args:
            target (ChildAbortTargetDAO): Identity captured from the displayed snapshot.
        """
        if self._bound_sink is None or self._retiring:
            return
        self._bound_sink.confirm_abort(target=target)

    def focus_sessions(self) -> None:
        """Focus the session list when it has rows; safe whether or not a sink is bound."""
        self._fleet_panel.focus_sessions()

    def sessions_hold_focus(self) -> bool:
        """Return whether the session list (or one of its rows) holds focus.

        Returns:
            bool: True when the composed panel or a descendant is focused.
        """
        return self._fleet_panel.has_focus or self._fleet_panel.has_focus_within

    def has_visible_sessions(self) -> bool:
        """Return whether the panel is displaying session rows.

        Returns:
            bool: True while rows are mounted and the panel is displayed.
        """
        return bool(self._fleet_panel.display)

    async def present_session_rows(
        self, *, sink: WorkflowProgressSink, snapshot: WorkflowSessionSnapshotDAO
    ) -> None:
        """Paint list rows for the exact bound sink, joining the shielded apply.

        WHAT: Paints only while ``sink`` is still the bound, unretired sink and
            the widget is open; the identity is rechecked after the awaited
            apply so a retirement that started meanwhile owns visibility and
            focus. An emptied list that held focus returns focus to the prompt
            through the host, on the base screen only.
        WHO: The bound adapter's ``apply_sessions`` for every coordinator refresh.
        WHEN: Serialized through the panel's own shielded apply.

        Args:
            sink (WorkflowProgressSink): Adapter asking to paint.
            snapshot (WorkflowSessionSnapshotDAO): Ordered rows to display.
        """
        if sink is not self._bound_sink or self._retiring or self._closed:
            return
        list_focused: bool = self.sessions_hold_focus()
        try:
            await self._fleet_panel.apply_snapshot(snapshot=snapshot)
        except BaseException:
            # Includes cancellation of this waiter: the panel's shielded apply
            # continues independently, so reconcile the wrapper's display with
            # the panel's actual display before the exception escapes.
            if sink is self._bound_sink and not self._retiring:
                self.display = self._fleet_panel.display
            raise
        if sink is not self._bound_sink or self._retiring:
            return
        self.display = self._fleet_panel.display
        if not snapshot.rows and list_focused:
            self._host.return_prompt_focus()

    async def _reset_presentation(self, *, sink: WorkflowProgressSink) -> None:
        """Reset the panel for the retiring sink, releasing the binding last.

        Joins any unfinished shielded apply through the panel's reset, hides the
        wrapper, returns focus when the emptied list held it, and only then
        frees the binding for a successor. A failed reset keeps the binding
        reserved and records the failure against any later bind or retire.

        Args:
            sink (WorkflowProgressSink): The disposed sink this reset belongs to.

        Raises:
            BaseException: Whatever the panel's reset raised.
        """
        list_focused: bool = self.sessions_hold_focus()
        try:
            await self._fleet_panel.reset()
        except BaseException as error:
            self._retirement_failure = error
            self.display = self._fleet_panel.display
            raise
        self.display = False
        if list_focused:
            self._host.return_prompt_focus()
        self._bound_sink = None
        self._retiring = False
        self._retirement_task = None

    async def on_unmount(self) -> None:
        """Close the component: join any retirement, or retire the bound sink as a cutoff.

        WHAT: Sets the closed flag immediately so no paint or bind can follow,
            then joins an existing retirement or starts one for a still-bound
            sink. It never closes services or cancels execution; the app's own
            observation close remains the owner teardown.
        WHO: Textual when the widget leaves the DOM, after the app's observation
            close in the normal unmount order.
        WHEN: Once; a closed widget never binds again.
        """
        self._closed = True
        sink: Optional[WorkflowProgressUpdatesAdapter] = self._bound_sink
        if sink is None:
            return
        await self.retire_observation(sink=sink)
