"""AbortConfirmationScreen — confirm one captured child execution (feature 94 a.4).

A native Textual ``ModalScreen[bool]`` pushed by the app's progress sink above
the session progress view. It names the exact parent and child literally,
focuses the safe choice and returns only ``True`` (explicit Abort child) or
``False`` (Keep running, Escape or withdrawal). It never submits anything: the
sink retains the immutable target in its callback and the workflow service owns
submission, so closing this modal never withdraws an accepted request.
"""

from __future__ import annotations

from typing import ClassVar, Optional

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from src.tui.workflows.dao import ChildAbortTargetDAO

__all__ = ["ABORT_CONSEQUENCE_TEXT", "AbortConfirmationScreen"]

ABORT_CONSEQUENCE_TEXT: str = "Stops only this child; dependent chain steps may not run."
"""Fixed scope sentence: siblings and the orchestrator keep running."""


class AbortConfirmationScreen(ModalScreen[bool]):
    """Confirm one captured execution identity, defaulting to no destructive action.

    Invariants: the result is delivered at most once; ``True`` only from the
    explicit Abort child button; the screen pops itself only while it is the
    active screen, so it never closes an unrelated modal above it.
    """

    CSS_PATH = "abort_confirmation_screen.tcss"
    BINDINGS: ClassVar[list[BindingType]] = [
        Binding(key="escape", action="cancel", description="Keep running", priority=True)
    ]
    # Below 80 columns the buttons stack (see the adjacent TCSS).
    HORIZONTAL_BREAKPOINTS = [
        (0, "-confirm-narrow"),
        (80, "-confirm-wide"),
    ]

    def __init__(self, *, target: ChildAbortTargetDAO) -> None:
        """Bind the exact target supplied by the progress sink before any refresh.

        Args:
            target (ChildAbortTargetDAO): Captured key, run and execution identity.
        """
        super().__init__()
        self._target: ChildAbortTargetDAO = target
        # The choice not yet delivered; set when a choice or withdrawal is made.
        self._pending_result: Optional[bool] = None
        self._decided: bool = False

    def compose(self) -> ComposeResult:
        """Explain scope before offering the explicit destructive button."""
        with Vertical(id="confirm-box"):
            yield Static(content="Abort this sub-agent?", markup=False, classes="heading")
            yield Static(content=self._target.key.orchestrator_session_id, markup=False, id="confirm-parent")
            yield Static(content=self._target.key.session_id, markup=False, id="confirm-child")
            yield Static(content=ABORT_CONSEQUENCE_TEXT, markup=False)
            with Horizontal(classes="actions"):
                yield Button(label="Keep running", id="keep-running")
                yield Button(label="Abort child", id="confirm-abort", variant="error")

    def on_mount(self) -> None:
        """Select the safe choice when the sink pushes confirmation."""
        self.query_one(selector="#keep-running", expect_type=Button).focus()

    @on(Button.Pressed)
    def _choose(self, event: Button.Pressed) -> None:
        """Return the explicit choice once; the sink owns submission.

        Args:
            event (Button.Pressed): Confirmation button activation.
        """
        event.stop()
        self._decide(result=event.button.id == "confirm-abort")

    def action_cancel(self) -> None:
        """Close confirmation only, leaving the progress view and child alive."""
        self._decide(result=False)

    def withdraw(self) -> None:
        """Answer False because the sink no longer owns this confirmation.

        WHAT: Textual's ``dismiss`` pops whatever screen is on top, so a covered
            confirmation waits until it is active again before closing.
        WHO: The app's progress sink on minimize, membership removal, same-key
            incarnation change and disposal.
        WHEN: Before the sink retires the progress view underneath.
        """
        self._decide(result=False)

    def on_screen_resume(self) -> None:
        """Finish a decision deferred while an unrelated modal covered this screen."""
        self._close_if_on_top()

    def _decide(self, *, result: bool) -> None:
        """Record the first choice only, then close when possible.

        Args:
            result (bool): True only for the explicit destructive choice.
        """
        if self._decided:
            return
        self._decided = True
        self._pending_result = result
        self._close_if_on_top()

    def _close_if_on_top(self) -> None:
        """Deliver the recorded result once, and only while this screen is active."""
        if self._pending_result is None or not self.is_active:
            return
        result: bool = self._pending_result
        self._pending_result = None
        self.dismiss(result=result)
