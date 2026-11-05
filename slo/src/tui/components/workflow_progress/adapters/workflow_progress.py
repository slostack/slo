"""Manage workflow session-list updates, progress dialogs, and abort confirmation."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable
from functools import partial
from typing import Optional, Protocol, Self, TYPE_CHECKING

if TYPE_CHECKING:
    from src.tui.components.workflow_progress.commands import PresentSessionsDAO

from src.tui.components.workflow_progress.events import (
    WorkflowProgressUpdate,
    SessionsUpdatedDAO,
    ProgressUpdatedDAO,
    MinimizeProgressDAO,
    MembershipRemovedDAO,
    ObservationFailedDAO,
    ConfirmAbortDAO,
)
from src.tui.components.workflow_progress.host import WorkflowProgressHost
from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    ProgressViewportDAO,
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.session_progress_screen import SessionProgressScreen

PROGRESS_VIEWPORT_CACHE_LIMIT: int = 64
"""Most recently visited session keys whose reading position the progress adapter keeps."""

PROGRESS_DIALOG_CONFLICT_NOTICE: str = "Close the current dialog before inspecting progress."
"""Shown when a list selection arrives while an unrelated modal is open."""

PROGRESS_MEMBERSHIP_REMOVED_NOTICE: str = "This session is no longer in the current workflow list."
"""Shown when the selected session left the owner's list."""

PROGRESS_REFRESH_FAILED_NOTICE: str = "Progress refresh unavailable; retrying on the next tick."
"""Shown once per failure streak when an observation refresh fails unexpectedly."""


class SessionListPresenter(Protocol):
    """The WorkflowProgressComponent operations this adapter paints through (consumer-owned)."""

    async def handle(self, *, command: PresentSessionsDAO) -> None:
        """Paint list rows for the exact bound sink, without stealing focus."""
        ...


class WorkflowProgressUpdatesAdapter:
    """Turn workflow updates into session rows and a progress screen.

    Remember the selected session and recent scroll positions. Open and close
    only the progress screen owned by this adapter; leave other dialogs alone.
    Ask the host to handle lifecycle actions rather than creating services,
    changing coordinator state, or cancelling running agents directly.

    Once closed, reject new updates and ignore delayed UI callbacks. Use a
    new adapter when starting a new progress listener."""

    def __init__(self, *, host: WorkflowProgressHost, presenter: SessionListPresenter) -> None:
        """Save the host and row presenter and start with no displayed progress."""
        self._host: WorkflowProgressHost = host
        self._presenter: SessionListPresenter = presenter
        self._retired: bool = False
        self._delivery_lock = asyncio.Lock()
        self._progress_version = 0
        self._resetting = 0
        self._close_task: Optional[asyncio.Task[None]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._screen: Optional[SessionProgressScreen] = None
        self._screen_mount: Optional[Awaitable[None]] = None
        # Keep recent scroll positions last and limit the number remembered.
        self._viewports: OrderedDict[WorkflowSessionKeyDAO, ProgressViewportDAO] = OrderedDict()
        # Remember each session’s execution and dispatch IDs from the latest list.
        self._identities: dict[WorkflowSessionKeyDAO, tuple[str, str]] = {}
        # Remember which execution the open row referred to, if known.
        self._selected_identity: Optional[tuple[str, str]] = None
        self._failure_notified: bool = False
        # Keep track of the confirmation dialog opened by this adapter.
        self._confirmation: Optional[AbortConfirmationScreen] = None

    @classmethod
    def register(cls, *, host: WorkflowProgressHost, presenter: SessionListPresenter) -> Self:
        """Return a fresh inactive sink without subscribing or opening a screen.

        The component publishes this sink only after binding admission succeeds.
        Registration borrows both collaborators and does not capture a loop.

        Args:
            host: UI and workflow-control destination, not owned by this sink.
            presenter: Session-row destination for the admitted binding.

        Returns:
            An independent adapter lifetime, even if another registration closed.
        """
        return cls(host=host, presenter=presenter)

    def _ensure_progress_adapter_open(self) -> None:
        """Reject retired updates before capturing a loop or touching borrowed targets."""
        if self._retired:
            raise RuntimeError("Workflow progress adapter is closed")

    def _update_delivery_loop(self) -> None:
        """Store the first delivery/reset loop, then require that same running loop.

        Registration captures no loop. The mounted component owns UI admission;
        this adapter only prevents later cross-loop delivery.
        """
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        self._ensure_delivery_loop(loop=loop)

    def _ensure_delivery_loop(self, *, loop: asyncio.AbstractEventLoop) -> None:
        """Raise RuntimeError if the running loop differs from the stored delivery loop."""
        if loop is not self._loop:
            raise RuntimeError("Workflow progress delivery requires the UI loop")

    async def handle(self, *, event: WorkflowProgressUpdate) -> None:
        """Apply each update in order and wait until it has been applied, not just scheduled."""
        self._ensure_progress_adapter_open()
        self._update_delivery_loop()
        progress_version = self._progress_version
        async with self._delivery_lock:
            self._ensure_progress_adapter_open()
            self._update_delivery_loop()
            if progress_version != self._progress_version or self._resetting:
                raise RuntimeError("Workflow update belongs to a retired presentation")
            await self._present_update(event=event)

    async def _present_update(self, *, event: WorkflowProgressUpdate) -> None:
        """Choose the display action for the accepted update type."""
        if isinstance(event, SessionsUpdatedDAO):
            await self._present_sessions(snapshot=event.snapshot)
        elif isinstance(event, ProgressUpdatedDAO):
            await self._present_progress(snapshot=event.snapshot)
        elif isinstance(event, MinimizeProgressDAO):
            self._release_owned_view()
        elif isinstance(event, MembershipRemovedDAO):
            self._viewports.pop(event.key, None)
            self._host.notify_progress(message=PROGRESS_MEMBERSHIP_REMOVED_NOTICE)
        elif isinstance(event, ObservationFailedDAO):
            self._observation_failed()
        elif isinstance(event, ConfirmAbortDAO):
            self._confirm_abort(target=event.target)
        else:
            raise TypeError(f"Unsupported workflow update: {type(event).__name__}")

    async def reset(self) -> None:
        """Wait for active updates and clear display state without closing the supplied host or presenter."""
        self._ensure_progress_adapter_open()
        self._update_delivery_loop()
        self._progress_version += 1
        self._resetting += 1
        task = asyncio.create_task(self._reset_presentation())
        try:
            await self._join_retirement(task=task)
        finally:
            self._resetting -= 1

    def begin_close(self) -> None:
        """Immediately stop callbacks from updating a binding that is being removed."""
        self._retired = True
        self._progress_version += 1

    async def close(self) -> None:
        """Stop accepting updates and wait for cleanup. Allow cleanup to be retried if it fails."""
        self.begin_close()
        if self._close_task is None or (self._close_task.done() and self._close_task.exception() is not None):
            self._close_task = asyncio.create_task(self._reset_presentation())
        await self._join_retirement(task=self._close_task)

    async def _reset_presentation(self) -> None:
        """Wait for accepted updates, then close owned screens and clear saved state."""
        async with self._delivery_lock:
            self._release_owned_view()
            self._viewports.clear()
            self._identities.clear()
            self._selected_identity = None
            self._failure_notified = False

    @staticmethod
    async def _join_retirement(*, task: asyncio.Task[None]) -> None:
        """Finish cleanup before reporting cancellation, even if the caller is cancelled repeatedly."""
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        task.result()
        if cancelled:
            raise asyncio.CancelledError

    def open_progress(self, *, key: WorkflowSessionKeyDAO) -> bool:
        """Open a session’s progress screen without covering an unrelated dialog.

        Keep the existing screen if it already shows this session. Otherwise,
        replace the owned screen and restore the saved scroll position. Return
        whether the coordinator can use this selection.
        """
        self._ensure_progress_adapter_open()
        self._update_delivery_loop()
        if self._resetting:
            return False
        if self._screen is not None and self._screen.key == key:
            return True
        if not self._host.may_open_progress(current=self._screen):
            self._host.notify_progress(message=PROGRESS_DIALOG_CONFLICT_NOTICE)
            return False
        self._release_owned_view()
        self._screen = SessionProgressScreen(
            key=key, viewport=self._viewports.get(key, ProgressViewportDAO())
        )
        self._selected_identity = self._identities.get(key)
        self._screen_mount = self._host.present_progress(
            screen=self._screen,
            on_closed=partial(
                self._progress_closed, screen=self._screen, progress_version=self._progress_version
            ),
        )
        return True

    async def _present_sessions(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Update session rows without taking focus and discard outdated scroll positions.

        Tell the host if the open session now refers to a different execution
        before updating the stored session identities.
        """
        if self._retired:
            return
        self._failure_notified = False
        self._close_reused_selection(snapshot=snapshot)
        self._delete_obsolete_progress_viewports(snapshot=snapshot)
        from src.tui.components.workflow_progress.commands import PresentSessionsDAO

        await self._presenter.handle(command=PresentSessionsDAO(sink=self, snapshot=snapshot))

    def _confirm_abort(self, *, target: ChildAbortTargetDAO) -> None:
        """Ask for confirmation to abort the exact child shown in the active progress screen.

        Ignore other targets and repeated requests while a dialog is open. Keep
        the original target in the callback even if the displayed rows change.
        """
        if self._retired:
            return
        screen: Optional[SessionProgressScreen] = self._screen
        # An open confirmation takes focus, so repeated requests are ignored too.
        if screen is None or screen.key != target.key or not self._host.is_active_progress(screen=screen):
            return
        confirmation: AbortConfirmationScreen = AbortConfirmationScreen(target=target)
        self._confirmation = confirmation
        self._host.present_confirmation(
            screen=confirmation,
            on_closed=partial(self._confirmed, confirmation=confirmation, target=target),
        )

    async def _present_progress(self, *, snapshot: SessionProgressSnapshotDAO) -> None:
        """Send validated progress only to the screen that is still selected."""
        if self._retired:
            return
        screen: Optional[SessionProgressScreen] = self._screen
        if screen is None or screen.key != snapshot.key:
            return
        progress_version = self._progress_version
        if self._screen_mount is not None:
            await self._screen_mount
        if progress_version != self._progress_version:
            return
        self._deliver_progress(screen=screen, snapshot=snapshot)

    def _observation_failed(self) -> None:
        """Keep the last successful display and show one warning until a list read succeeds."""
        if self._retired or self._failure_notified:
            return
        self._failure_notified = True
        self._host.notify_progress(message=PROGRESS_REFRESH_FAILED_NOTICE, warning=True)

    def _release_owned_view(self) -> None:
        """Close this adapter’s confirmation dialog and progress screen, if present."""
        screen: Optional[SessionProgressScreen] = self._screen
        if screen is None:
            return
        self._withdraw_confirmation()
        self._update_progress_viewport(screen=screen)
        screen.retire()
        self._screen = None
        self._screen_mount = None
        self._selected_identity = None

    def _confirmed(
        self,
        confirmed: Optional[bool],
        *,
        confirmation: AbortConfirmationScreen,
        target: ChildAbortTargetDAO,
    ) -> None:
        """Submit the captured abort request once, only for an explicit True from the current dialog.

        Ignore cancelled, repeated, replaced, or outdated dialog callbacks.
        """
        if self._confirmation is not confirmation:
            return
        self._confirmation = None
        if self._retired or self._resetting or confirmed is not True:
            return
        self._host.child_abort_confirmed(target=target)

    def _withdraw_confirmation(self) -> None:
        """Close this adapter’s confirmation dialog with a False result before closing its progress screen."""
        confirmation: Optional[AbortConfirmationScreen] = self._confirmation
        if confirmation is not None:
            confirmation.withdraw()
        self._confirmation = None

    def _progress_closed(
        self, _result: None, *, screen: SessionProgressScreen, progress_version: int
    ) -> None:
        """Return focus once an owned view has actually left the screen stack.

        Args:
            _result (None): Unused dismissal result of the progress screen.
        """
        if self._retired or progress_version != self._progress_version:
            return
        if self._screen is not None and self._screen is not screen:
            return
        self._host.progress_closed()

    def _update_progress_viewport(self, *, screen: SessionProgressScreen) -> None:
        """Save the closing screen’s scroll position and limit how many positions are remembered."""
        if not screen.is_live:
            return
        self._viewports[screen.key] = screen.capture_viewport()
        self._viewports.move_to_end(screen.key)
        while len(self._viewports) > PROGRESS_VIEWPORT_CACHE_LIMIT:
            self._viewports.popitem(last=False)

    def _close_reused_selection(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Tell the host when an open session key now points to a different execution.

        Do not silently switch the reader to another execution. Leave missing
        sessions to the coordinator’s removal handling; discard the old scroll
        position during the following cleanup.
        """
        if self._screen is None:
            return
        key: WorkflowSessionKeyDAO = self._screen.key
        row = next((row for row in snapshot.rows if row.key == key), None)
        identity: tuple[str, str] = (row.execution_id, row.dispatch_id) if row is not None else ("", "")
        if row is None or self._selected_identity == identity:
            return
        self._host.progress_incarnation_changed(key=key)
        self._release_owned_view()

    def _delete_obsolete_progress_viewports(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Forget scroll positions for sessions that were removed or now refer to another execution."""
        identities: dict[WorkflowSessionKeyDAO, tuple[str, str]] = {
            row.key: (row.execution_id, row.dispatch_id) for row in snapshot.rows
        }
        for key in tuple(self._viewports):
            if key not in identities or self._identities.get(key) != identities[key]:
                self._viewports.pop(key, None)
        self._identities = identities

    def _deliver_progress(
        self, *, screen: SessionProgressScreen, snapshot: SessionProgressSnapshotDAO
    ) -> None:
        """Ignore a delayed update if its original screen was closed, even if a new screen uses the same key."""
        if self._retired:
            return
        if self._screen is screen and screen.is_live:
            screen.apply_snapshot(snapshot=snapshot)
