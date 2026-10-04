"""Success / sign-in-complete widget (02.b.5)."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Static

__all__ = ["SuccessWidget"]


class SuccessWidget(Vertical):
    """Confirm a credential was persisted; emit ``Closed`` on Close."""

    class Closed(Message):
        """Posted when the user clicks Close."""

    def __init__(self, *, subject: Optional[str], message: Optional[str] = None) -> None:
        """Capture the subject for the banner line.

        Args:
            subject (Optional[str]): "Signed in as <subject>." or just
                "Signed in." when ``None``.
            message: Optional fixed authentication status replacing the default banner.
        """
        super().__init__()
        self._subject: Optional[str] = subject
        self._message = message

    def compose(self) -> ComposeResult:
        """Render the banner and the Close button."""
        banner: str = f"Signed in as {self._subject}." if self._subject else "Signed in."
        yield Static(self._message or banner, classes="auth-title", markup=False)
        yield Button(label="Close", id="success-close", variant="primary")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate Close to ``Closed``.

        Args:
            event (Button.Pressed): Textual button-press event.
        """
        if event.button.id == "success-close":
            self.post_message(self.Closed())
