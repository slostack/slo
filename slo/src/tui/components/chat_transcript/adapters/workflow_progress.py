"""Manage workflow session-list updates, progress dialogs, and abort confirmation."""

from __future__ import annotations

from collections import OrderedDict
from functools import partial
from typing import TYPE_CHECKING, Optional, Self

from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.dao import (
    ChildAbortTargetDAO,
    ProgressViewportDAO,
    SessionProgressSnapshotDAO,
    WorkflowSessionKeyDAO,
    WorkflowSessionSnapshotDAO,
)
from src.tui.workflows.session_progress_screen import SessionProgressScreen

if TYPE_CHECKING:
    from src.tui.app import SloTUI


PROGRESS_VIEWPORT_CACHE_LIMIT: int = 64
"""Most recently visited session keys whose reading position the progress adapter keeps."""

PROGRESS_DIALOG_CONFLICT_NOTICE: str = "Close the current dialog before inspecting progress."
"""Shown when a list selection arrives while an unrelated modal is open."""

PROGRESS_MEMBERSHIP_REMOVED_NOTICE: str = "This session is no longer in the current workflow list."
"""Shown when the selected session left the owner's list."""

PROGRESS_REFRESH_FAILED_NOTICE: str = "Progress refresh unavailable; retrying on the next tick."
"""Shown once per failure streak when an observation refresh fails unexpectedly."""


class WorkflowProgressUpdatesAdapter:
    """Keep the workflow session list and the selected agent's progress dialog up to date.

    The app creates this adapter with ``register(tui=self)`` when it starts
    watching the current session's workflows. ``WorkflowProgressCoordinator``
    calls it after reading fresh data, normally every five seconds and when
    a refresh is requested. ``apply_sessions()`` updates the session list;
    ``apply_progress()`` updates the open progress dialog.

    When the user selects an agent, ``open_progress()`` opens its dialog.
    Minimizing saves the reading position so reopening can restore it. The
    adapter keeps track of its own dialogs and refuses to replace unrelated
    dialogs. It also prevents delayed updates from changing a closed view or
    silently switching the reader to a different execution.

    When the user chooses Abort child, it opens a confirmation dialog and
    passes an explicitly confirmed request back to the app. It does not
    cancel agents itself. If a refresh fails, it keeps the last displayed
    data and shows: "Progress refresh unavailable; retrying on the next tick."

    Unlike ``WorkflowNoticeAdapter``, this adapter manages the progress UI;
    it does not write notices into the main chat. It does not read progress
    files, schedule refreshes, or run agents. Those jobs belong to the
    workflow service and coordinator.
    """

    @classmethod
    def register(cls, *, tui: SloTUI) -> Self:
        """Create this presentation adapter bound to one app instance."""
        return cls(tui=tui)

    def __init__(self, *, tui: SloTUI) -> None:
        """Bind the adapter to the owning app with empty presentation state.

        Args:
            tui (SloTUI): App whose screens, panel and prompt the adapter drives.
        """
        self._tui: SloTUI = tui
        self._screen: Optional[SessionProgressScreen] = None
        # Most recently visited last; at most PROGRESS_VIEWPORT_CACHE_LIMIT keys.
        self._viewports: OrderedDict[WorkflowSessionKeyDAO, ProgressViewportDAO] = OrderedDict()
        # (execution_id, dispatch_id) per key from the latest applied list.
        self._identities: dict[WorkflowSessionKeyDAO, tuple[str, str]] = {}
        # Identity of the open view's row when it was opened; None when unknown.
        self._selected_identity: Optional[tuple[str, str]] = None
        self._failure_notified: bool = False
        # The confirmation this adapter opened above its progress view, if any.
        self._confirmation: Optional[AbortConfirmationScreen] = None

    def open_progress(self, *, key: WorkflowSessionKeyDAO) -> bool:
        """Open one owned view, refusing to stack behind unrelated modals.

        WHAT: Keeps an already open view of the same key (double click never
            stacks), refuses while another modal is active, otherwise replaces any
            previous view with a new screen opened at the key's saved viewport.
        WHO: ``WorkflowProgressCoordinator.select``.
        WHEN: On each list activation.

        Args:
            key (WorkflowSessionKeyDAO): Exact selected session.

        Returns:
            bool: Whether the coordinator may adopt this selection.
        """
        if self._screen is not None and self._screen.key == key:
            return True
        if len(self._tui.screen_stack) > 1 and self._tui.screen is not self._screen:
            self._tui.notify(message=PROGRESS_DIALOG_CONFLICT_NOTICE, markup=False)
            return False
        self.minimize_progress()
        self._screen = SessionProgressScreen(
            key=key, viewport=self._viewports.get(key, ProgressViewportDAO())
        )
        self._selected_identity = self._identities.get(key)
        self._tui.push_screen(screen=self._screen, callback=self._progress_closed)
        return True

    def minimize_progress(self) -> None:
        """Save the current viewport and give up this adapter's progress screen.

        WHAT: Withdraws an owned confirmation first (answering False, so no
            abort is submitted), then retires the view: it closes at once when it
            is on top, or as soon as the modal above it closes; an unrelated
            modal is never popped. Focus returns when the view leaves the stack.
        WHO: The coordinator's ``minimize`` (Escape, removal, incarnation change),
            ``open_progress`` when replacing a view, and ``dispose``.
        WHEN: After the coordinator invalidated its generation.
        """
        screen: Optional[SessionProgressScreen] = self._screen
        if screen is None:
            return
        self._withdraw_confirmation()
        self._remember_viewport(screen=screen)
        self._screen = None
        self._selected_identity = None
        screen.retire()

    async def apply_sessions(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Paint rows without stealing focus and invalidate obsolete saved positions.

        WHAT: Routes a same-key incarnation change of the open view through the
            app before overwriting identities, prunes viewports of removed or
            reused keys, then paints the panel (which returns focus only from an
            emptied, focused base list).
        WHO: The coordinator after every list read.
        WHEN: Before the selected progress read of the same refresh.

        Args:
            snapshot (WorkflowSessionSnapshotDAO): Current or explicitly retained rows.
        """
        self._failure_notified = False
        self._close_reused_selection(snapshot=snapshot)
        self._prune_viewports(snapshot=snapshot)
        await self._tui._apply_session_snapshot(snapshot=snapshot)

    def confirm_abort(self, *, target: ChildAbortTargetDAO) -> None:
        """Open one owned confirmation for the exact target the active view displayed.

        WHAT: Ignores targets of another key and requests while the view is not
            the active screen, which includes repeats while a confirmation is open. The target is
            retained in the callback closure, never replaced by refreshed rows.
        WHO: SloTUI's ``AbortRequested`` handler.
        WHEN: When the operator activates Abort child on the progress view.

        Args:
            target (ChildAbortTargetDAO): Identity captured from the displayed snapshot.
        """
        screen: Optional[SessionProgressScreen] = self._screen
        # An open confirmation is the active screen, so this also absorbs repeats.
        if screen is None or screen.key != target.key or self._tui.screen is not screen:
            return
        confirmation: AbortConfirmationScreen = AbortConfirmationScreen(target=target)
        self._confirmation = confirmation
        self._tui.push_screen(
            screen=confirmation,
            callback=partial(self._confirmed, confirmation=confirmation, target=target),
        )

    def apply_progress(self, *, snapshot: SessionProgressSnapshotDAO) -> None:
        """Deliver bounded public content only to the still-selected screen object.

        Args:
            snapshot (SessionProgressSnapshotDAO): Service-validated observation.
        """
        screen: Optional[SessionProgressScreen] = self._screen
        if screen is None or screen.key != snapshot.key:
            return
        if not screen.is_live:
            self._tui.call_after_refresh(self._deliver_progress, screen=screen, snapshot=snapshot)
            return
        self._deliver_progress(screen=screen, snapshot=snapshot)

    def membership_removed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Forget a removed view after the coordinator invalidated its generation.

        Args:
            key (WorkflowSessionKeyDAO): Former selected identity.
        """
        self._viewports.pop(key, None)
        self._tui.notify(message=PROGRESS_MEMBERSHIP_REMOVED_NOTICE, markup=False)

    def observation_failed(self) -> None:
        """Keep last-good paint and notify once per failure streak (reset by a good list)."""
        if self._failure_notified:
            return
        self._failure_notified = True
        self._tui.notify(message=PROGRESS_REFRESH_FAILED_NOTICE, markup=False, severity="warning")

    def dispose(self) -> None:
        """Discard observation UI only after coordinator and service work are joined.

        WHO: ``SloTUI._close_workflow_observation``.
        WHEN: On owner replacement and unmount, after ``coordinator.close``.
        """
        self.minimize_progress()
        self._viewports.clear()
        self._identities.clear()
        self._selected_identity = None

    def _confirmed(
        self,
        confirmed: Optional[bool],
        *,
        confirmation: AbortConfirmationScreen,
        target: ChildAbortTargetDAO,
    ) -> None:
        """Forget the closed confirmation; submit only on an explicit True.

        Args:
            confirmed (Optional[bool]): Confirmation result; False/None submit nothing.
            confirmation (AbortConfirmationScreen): Screen this callback belongs to.
            target (ChildAbortTargetDAO): Target captured when it opened.
        """
        if self._confirmation is confirmation:
            self._confirmation = None
        if confirmed is True:
            self._tui._on_child_abort_confirmed(target=target)

    def _withdraw_confirmation(self) -> None:
        """Close only the owned confirmation (answering False) before its view goes."""
        confirmation: Optional[AbortConfirmationScreen] = self._confirmation
        self._confirmation = None
        if confirmation is not None:
            confirmation.withdraw()

    def _progress_closed(self, _result: None) -> None:
        """Return focus once an owned view has actually left the screen stack.

        Args:
            _result (None): Unused dismissal result of the progress screen.
        """
        self._tui._focus_after_progress()

    def _remember_viewport(self, *, screen: SessionProgressScreen) -> None:
        """Bound saved positions whenever the adapter minimizes or replaces a view.

        Args:
            screen (SessionProgressScreen): Owned screen being dismissed.
        """
        if not screen.is_live:
            return
        self._viewports[screen.key] = screen.capture_viewport()
        self._viewports.move_to_end(screen.key)
        while len(self._viewports) > PROGRESS_VIEWPORT_CACHE_LIMIT:
            self._viewports.popitem(last=False)

    def _close_reused_selection(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Route an incarnation change of the open view through the app, before pruning.

        A key absent from the rows is left to the coordinator's removal path. Any
        other identity mismatch, including a view opened before its identity was
        known, closes the view so a reader is never silently retargeted to
        another execution. The old viewport is purged by the pruning that follows.

        Args:
            snapshot (WorkflowSessionSnapshotDAO): Fresh or retained list evidence.
        """
        if self._screen is None:
            return
        key: WorkflowSessionKeyDAO = self._screen.key
        row = next((row for row in snapshot.rows if row.key == key), None)
        identity: tuple[str, str] = (row.execution_id, row.dispatch_id) if row is not None else ("", "")
        if row is None or self._selected_identity == identity:
            return
        self._tui._on_progress_incarnation_changed(key=key)

    def _prune_viewports(self, *, snapshot: WorkflowSessionSnapshotDAO) -> None:
        """Forget removed or reused keys after authoritative service reconciliation.

        Args:
            snapshot (WorkflowSessionSnapshotDAO): Retains rows on transient failures.
        """
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
        """Reject deferred paint addressed to a dismissed instance with the same key.

        Args:
            screen (SessionProgressScreen): Object captured when scheduling delivery.
            snapshot (SessionProgressSnapshotDAO): Validated progress to paint.
        """
        if self._screen is screen and screen.is_live:
            screen.apply_snapshot(snapshot=snapshot)
