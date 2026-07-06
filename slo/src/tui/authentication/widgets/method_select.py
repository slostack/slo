"""Method-selection widget — OAuth or paste API key (02.b.5)."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, RadioButton, RadioSet, Static

from src.auth.credential_dao import AuthType, ProviderName


__all__ = ["MethodSelectWidget"]


class MethodSelectWidget(Vertical):
    """Pick OAuth or API key; emit ``Chosen`` when Continue is clicked."""

    class Chosen(Message):
        """Posted when the user clicks Continue with a method selected."""

        def __init__(self, *, method: AuthType) -> None:
            """Carry the chosen method.

            Args:
                method (AuthType): OAUTH or API_KEY.
            """
            self.method: AuthType = method
            super().__init__()

    class BackRequested(Message):
        """Posted when the user clicks Back."""

    class Cancelled(Message):
        """Posted when the user clicks Cancel."""

    def __init__(self, *, provider: ProviderName) -> None:
        """Capture which provider we're picking a method for.

        Args:
            provider (ProviderName): Used in the title only.
        """
        super().__init__()
        self._provider: ProviderName = provider

    def compose(self) -> ComposeResult:
        """Render the radio set, Continue, Back, Cancel."""
        yield Static(
            f"How would you like to authenticate with {self._provider.value}?",
            classes="auth-title",
        )
        with RadioSet(id="method-radio"):
            yield RadioButton(
                label=self._oauth_label(),
                value=True,
                id="method-oauth",
            )
            yield RadioButton(label="Paste an API key", id="method-api-key")
        yield Button(label="Continue", id="method-continue", variant="primary")
        yield Button(label="Back", id="method-back")
        yield Button(label="Cancel", id="method-cancel")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate clicks into the right ``Message``.

        Args:
            event (Button.Pressed): Textual button-press event.
        """
        if event.button.id == "method-cancel":
            self.post_message(self.Cancelled())
            return
        if event.button.id == "method-back":
            self.post_message(self.BackRequested())
            return
        if event.button.id == "method-continue":
            self.post_message(self.Chosen(method=self._selected_method()))

    def _oauth_label(self) -> str:
        """Return provider-specific OAuth copy for the radio button.

        Returns:
            str: User-facing sign-in label.
        """
        if self._provider is ProviderName.ANTHROPIC:
            return "Sign in with my Claude / Claude Code subscription (browser)"
        return "Sign in with my subscription (browser)"

    def _selected_method(self) -> AuthType:
        """Map the selected radio button to ``AuthType``.

        Returns:
            AuthType: User pick. Defaults to ``OAUTH``.
        """
        radio_set: RadioSet = self.query_one("#method-radio", RadioSet)
        if radio_set.pressed_index == 1:
            return AuthType.API_KEY
        return AuthType.OAUTH
