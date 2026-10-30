"""Consumer-owned bridge from the WorkflowProgress component to the app's global UI (96.f.1).

The component and its observation-lifetime adapter never import the app at
runtime: every screen-stack, notice, focus and control operation they need is
one operation on this protocol, implemented directly by ``SloTUI``. Each
operation owns exactly one decision; nothing here exposes the session, the
panel, the coordinator or the service.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional, Protocol

from src.tui.workflows.abort_confirmation_screen import AbortConfirmationScreen
from src.tui.workflows.dao import ChildAbortTargetDAO, WorkflowSessionKeyDAO
from src.tui.workflows.session_progress_screen import SessionProgressScreen

__all__ = ["WorkflowProgressHost"]


class WorkflowProgressHost(Protocol):
    """Global UI and control bridge the component's adapter drives."""

    def may_open_progress(self, *, current: Optional[SessionProgressScreen]) -> bool:
        """Return whether a progress view may open without stacking behind an unrelated modal.

        Args:
            current (Optional[SessionProgressScreen]): The adapter's already open
                view, when one exists; it never counts as a blocker.

        Returns:
            bool: False while an unrelated modal covers the base screen.
        """
        ...

    def is_active_progress(self, *, screen: SessionProgressScreen) -> bool:
        """Return whether ``screen`` is the app's active (top) screen.

        Args:
            screen (SessionProgressScreen): Owned view to compare.
        """
        ...

    def present_progress(self, *, screen: SessionProgressScreen, on_closed: Callable[[None], None]) -> None:
        """Push one owned progress view and deliver its dismissal once.

        Args:
            screen (SessionProgressScreen): Fresh view to present.
            on_closed (Callable[[None], None]): Callback after the view leaves the stack.
        """
        ...

    def present_confirmation(
        self, *, screen: AbortConfirmationScreen, on_closed: Callable[[Optional[bool]], None]
    ) -> None:
        """Push one owned abort confirmation and deliver its result once.

        Args:
            screen (AbortConfirmationScreen): Confirmation to present.
            on_closed (Callable[[Optional[bool]], None]): Result callback; False or
                None submit nothing.
        """
        ...

    def notify_progress(self, *, message: str, warning: bool = False) -> None:
        """Show one fixed presentation notice.

        Args:
            message (str): Literal notice text.
            warning (bool, optional): Whether the notice is a warning. Defaults to False.
        """
        ...

    def return_prompt_focus(self) -> None:
        """Focus the prompt editor, but only on the base screen (never behind a modal)."""
        ...

    def progress_closed(self) -> None:
        """Return focus after an owned progress view left the stack.

        On the base screen only: focus the session list when it has visible
        rows, otherwise the prompt editor. No-op behind any other modal.
        """
        ...

    def progress_incarnation_changed(self, *, key: WorkflowSessionKeyDAO) -> None:
        """Invalidate observation generation and notice a same-key execution change.

        Runs synchronously so generation invalidation precedes any further paint.

        Args:
            key (WorkflowSessionKeyDAO): Selected key whose incarnation changed.
        """
        ...

    def child_abort_confirmed(self, *, target: ChildAbortTargetDAO) -> None:
        """Hand one explicitly confirmed exact child target to the control service.

        Args:
            target (ChildAbortTargetDAO): Identity captured when the confirmation opened.
        """
        ...
