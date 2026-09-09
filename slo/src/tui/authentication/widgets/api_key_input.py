"""Paste-an-API-key widget (02.b.5)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Input, Static

from src.auth.credential_dao import ProviderName

__all__ = ["ApiKeyInputWidget"]


class ApiKeyInputWidget(Vertical):
    """Capture a pasted API key; emit ``Submitted`` on Save."""

    class Submitted(Message):
        """Posted when the user clicks Save with a non-empty key."""

        def __init__(self, *, api_key: str) -> None:
            """Carry the captured key.

            Args:
                api_key (str): Raw string the user pasted.
            """
            self.api_key: str = api_key
            super().__init__()

    class BackRequested(Message):
        """Posted when the user clicks Back."""

    class Cancelled(Message):
        """Posted when the user clicks Cancel."""

    def __init__(self, *, provider: ProviderName) -> None:
        """Stash the provider for the title and validation hint.

        Args:
            provider (ProviderName): Used in the title only.
        """
        super().__init__()
        self._provider: ProviderName = provider

    def compose(self) -> ComposeResult:
        """Render the password input, error label, Save / Back / Cancel."""
        yield Static(
            f"Paste your {self._provider.value} API key",
            classes="auth-title",
        )
        yield Input(password=True, placeholder="sk-...", id="api-key-input")
        yield Static("", id="api-key-error", classes="auth-error")
        with Horizontal(classes="auth-actions"):
            yield Button(label="Back", id="api-key-back")
            yield Button(label="Save", id="api-key-save", variant="primary")
            yield Button(label="Cancel", id="api-key-cancel")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Route Save / Back / Cancel.

        Args:
            event (Button.Pressed): Textual button-press event.
        """
        if event.button.id == "api-key-cancel":
            self.post_message(self.Cancelled())
            return
        if event.button.id == "api-key-back":
            self.post_message(self.BackRequested())
            return
        if event.button.id == "api-key-save":
            await self._handle_save()

    async def _handle_save(self) -> None:
        """Validate the key is non-empty; emit ``Submitted`` or update error."""
        raw: str = self.query_one("#api-key-input", Input).value.strip()
        if not raw:
            self.query_one("#api-key-error", Static).update("API key is required.")
            return
        self.post_message(self.Submitted(api_key=raw))
