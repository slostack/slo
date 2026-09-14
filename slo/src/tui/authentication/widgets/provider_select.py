"""Provider-selection widget (02.b.5)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, RadioButton, RadioSet, Static

from src.auth.credential_dao import ProviderName

__all__ = ["ProviderSelectWidget"]


class ProviderSelectWidget(Vertical):
    """Pick Anthropic or OpenAI; emit ``Chosen`` when Continue is clicked."""

    class Chosen(Message):
        """Posted when the user clicks Continue with a provider selected."""

        def __init__(self, *, provider: ProviderName) -> None:
            """Carry the chosen provider.

            Args:
                provider (ProviderName): Selection from the radio set.
            """
            self.provider: ProviderName = provider
            super().__init__()

    class Cancelled(Message):
        """Posted when the user clicks Cancel."""

    def compose(self) -> ComposeResult:
        """Render the radio set, Continue, and Cancel buttons."""
        yield Static("Sign in to a model provider", classes="auth-title")
        with RadioSet(id="provider-radio"):
            yield RadioButton(label="Anthropic (Claude / Claude Code)", value=True)
            yield RadioButton(label="OpenAI (ChatGPT)")
            yield RadioButton(label="Kimi For Coding")
        with Horizontal(classes="auth-actions"):
            yield Button(label="Continue", id="provider-continue", variant="primary")
            yield Button(label="Cancel", id="provider-cancel", variant="default")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate button clicks into ``Chosen`` / ``Cancelled``.

        Args:
            event (Button.Pressed): Textual button-press event.
        """
        if event.button.id == "provider-cancel":
            self.post_message(self.Cancelled())
            return
        if event.button.id == "provider-continue":
            self.post_message(self.Chosen(provider=self._selected_provider()))

    def _selected_provider(self) -> ProviderName:
        """Single decision: which radio is currently selected.

        Returns:
            ProviderName: The user's pick. Defaults to ``ANTHROPIC`` when
                no radio has been touched (matches the default state).
        """
        radio_set: RadioSet = self.query_one("#provider-radio", RadioSet)
        if radio_set.pressed_index == 1:
            return ProviderName.OPENAI
        if radio_set.pressed_index == 2:
            return ProviderName.KIMI_FOR_CODING
        return ProviderName.ANTHROPIC
