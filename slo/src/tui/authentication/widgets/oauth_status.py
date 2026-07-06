"""OAuth in-flight status widget (02.b.5)."""
from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Static

from src.auth.credential_dao import ProviderName


__all__ = ["OAuthStatusWidget"]


class OAuthStatusWidget(Vertical):
    """Show the auth URL and wait for the OAuth task to finish."""

    class BackRequested(Message):
        """Posted when the user clicks Back (after an error)."""

    class Cancelled(Message):
        """Posted when the user clicks Cancel."""

    def __init__(self, *, provider: ProviderName, auth_url: Optional[str] = None) -> None:
        """Initial state: URL pending until the flow yields it.

        Args:
            provider (ProviderName): For the title.
            auth_url (Optional[str]): Pre-rendered URL. Set later via
                ``set_auth_url`` if not known at construct time.
        """
        super().__init__()
        self._provider: ProviderName = provider
        self._initial_url: Optional[str] = auth_url

    def compose(self) -> ComposeResult:
        """Render the URL banner, status line, error region, controls."""
        yield Static(
            f"Sign in to {self._provider.value} in your browser…",
            classes="auth-title",
        )
        yield Static(self._initial_url or "(opening browser…)", id="oauth-url")
        yield Static("Waiting for callback…", id="oauth-status")
        yield Static("", id="oauth-error", classes="auth-error")
        yield Button(label="Back", id="oauth-back")
        yield Button(label="Cancel", id="oauth-cancel")

    def set_auth_url(self, *, url: str) -> None:
        """Update the URL banner after the flow renders the URL.

        Args:
            url (str): The fully assembled authorisation URL.
        """
        self.query_one("#oauth-url", Static).update(url)

    def set_error(self, *, message: str) -> None:
        """Surface an OAuth failure inline so the user can hit Back.

        Args:
            message (str): User-facing failure description.
        """
        self.query_one("#oauth-error", Static).update(message)
        self.query_one("#oauth-status", Static).update("Sign-in failed.")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate Back / Cancel into messages.

        Args:
            event (Button.Pressed): Textual button-press event.
        """
        if event.button.id == "oauth-back":
            self.post_message(self.BackRequested())
            return
        if event.button.id == "oauth-cancel":
            self.post_message(self.Cancelled())
