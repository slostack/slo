"""Capability-driven authentication-method selection widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, RadioButton, RadioSet, Static

from src.auth.credential_dao import AuthType, ProviderName
from src.auth.oauth_provider import OAuthLoginMethod

__all__ = ["MethodSelectWidget"]


class MethodSelectWidget(Vertical):
    """Render supported OAuth interactions and the API-key fallback."""

    class Chosen(Message):
        """Posted when the user clicks Continue with a method selected."""

        def __init__(self, *, method: AuthType | OAuthLoginMethod) -> None:
            """Carry the selected persisted or interactive method.

            Args:
                method (AuthType | OAuthLoginMethod): API-key provenance or selected OAuth capability.
            """
            self.method: AuthType | OAuthLoginMethod = method
            super().__init__()

    class BackRequested(Message):
        """Posted when the user clicks Back."""

    class Cancelled(Message):
        """Posted when the user clicks Cancel."""

    def __init__(
        self,
        *,
        provider: ProviderName,
        login_methods: frozenset[OAuthLoginMethod],
    ) -> None:
        """Render one choice per supported capability.

        Args:
            provider (ProviderName): Used in the title only.
            login_methods (frozenset[OAuthLoginMethod]): The capabilities the
                screen resolved once from the factory/provider. The widget maps
                each entry to a label; it never inspects the provider to decide
                which OAuth interactions exist, and it never contains a
                provider-name ``if`` for labels.
        """
        super().__init__()
        self._provider: ProviderName = provider
        self._login_methods: frozenset[OAuthLoginMethod] = login_methods

    def compose(self) -> ComposeResult:
        """Render one radio per injected OAuth capability and the API-key choice."""
        yield Static(
            f"How would you like to authenticate with {self._provider.value}?",
            classes="auth-title",
        )
        with RadioSet(id="method-radio"):
            for login_method in self._ordered_login_methods():
                yield RadioButton(
                    label=self._label_for(login_method=login_method),
                    value=login_method is self._default_login_method(),
                    id=f"method-{login_method.value}",
                )
            yield RadioButton(label="Paste an API key", id="method-api-key")
        with Horizontal(classes="auth-actions"):
            yield Button(label="Back", id="method-back")
            yield Button(label="Continue", id="method-continue", variant="primary")
            yield Button(label="Cancel", id="method-cancel")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate clicks into one typed screen message.

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

    def _ordered_login_methods(self) -> tuple[OAuthLoginMethod, ...]:
        """Return capabilities in a stable user-facing order."""
        order: tuple[OAuthLoginMethod, ...] = (
            OAuthLoginMethod.BROWSER_AUTHORIZATION,
            OAuthLoginMethod.DEVICE_AUTHORIZATION,
        )
        return tuple(login_method for login_method in order if login_method in self._login_methods)

    def _default_login_method(self) -> OAuthLoginMethod | None:
        """Return browser authorization when available, otherwise the first capability."""
        if OAuthLoginMethod.BROWSER_AUTHORIZATION in self._login_methods:
            return OAuthLoginMethod.BROWSER_AUTHORIZATION
        return next(iter(self._login_methods), None)

    @staticmethod
    def _label_for(*, login_method: OAuthLoginMethod) -> str:
        """Map one declared interaction to its provider-independent UI label."""
        labels: dict[OAuthLoginMethod, str] = {
            OAuthLoginMethod.BROWSER_AUTHORIZATION: "Browser authorization",
            OAuthLoginMethod.DEVICE_AUTHORIZATION: "Device authorization (headless)",
        }
        return labels[login_method]

    def _selected_method(self) -> AuthType | OAuthLoginMethod:
        """Map the selected radio button to its typed interaction.

        Returns:
            AuthType | OAuthLoginMethod: The user-selected capability or API-key route.
        """
        radio_set: RadioSet = self.query_one("#method-radio", RadioSet)
        selected_index: int = radio_set.pressed_index or 0
        login_methods: tuple[OAuthLoginMethod, ...] = self._ordered_login_methods()
        if selected_index >= len(login_methods):
            return AuthType.API_KEY
        return login_methods[selected_index]
