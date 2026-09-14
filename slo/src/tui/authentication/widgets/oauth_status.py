"""OAuth authorization instruction and status widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Input, Static

from src.auth.credential_dao import ProviderName
from src.auth.oauth_flow import AuthorizationPresentationDAO
from src.auth.oauth_provider import DeviceAuthorizationPresentationDAO, OAuthLoginMethod
from src.tui.authentication.widgets.authorization_link import AuthorizationLink

__all__ = ["AuthorizationResponseSubmitted", "OAuthStatusWidget"]


class AuthorizationResponseSubmitted(Message):
    """Carry one opaque pasted browser authorization response to the screen.

    WHAT: Delivers user text without parsing or logging it.
    WHO: OAuthStatusWidget posts it; AuthenticationScreen owns validation below.
    WHEN: Only while a browser authorization flow is waiting.
    """

    def __init__(self, *, authorization_response: str) -> None:
        """Store an opaque response only long enough for message delivery.

        Args:
            authorization_response (str): Untouched user-submitted browser response.
        """
        self.authorization_response: str = authorization_response
        super().__init__()


class OAuthStatusWidget(Vertical):
    """Render typed browser/device instructions and emit user intent only."""

    class BackRequested(Message):
        """Posted when the user clicks Back."""

    class Cancelled(Message):
        """Posted when the user clicks Cancel."""

    def __init__(self, *, provider: ProviderName, login_method: OAuthLoginMethod) -> None:
        """Initialize one selected authorization interaction.

        Args:
            provider (ProviderName): Provider named in the title.
            login_method (OAuthLoginMethod): Determines browser input availability.
        """
        super().__init__()
        self._provider: ProviderName = provider
        self._login_method: OAuthLoginMethod = login_method

    def compose(self) -> ComposeResult:
        """Render neutral placeholders, error region, and persistent controls."""
        yield Static(
            f"Sign in to {self._provider.value}",
            classes="auth-title",
        )
        yield Static("Preparing sign-in instructions…", id="oauth-instruction", classes="auth-instruction")
        yield AuthorizationLink("", url="", id="oauth-url", classes="auth-url")
        yield Static("", id="oauth-url-warning", classes="auth-instruction")
        yield Static("", id="oauth-redirect-instruction", classes="auth-instruction")
        yield Static("", id="oauth-redirect", classes="auth-redirect", markup=False)
        yield Static("", id="oauth-response-instruction", classes="auth-instruction")
        with Horizontal(id="oauth-response-row"):
            yield Input(placeholder="Paste authorization response", id="oauth-response-input")
            yield Button(
                label="Submit response",
                id="oauth-submit-response",
                variant="primary",
                disabled=self._login_method is OAuthLoginMethod.DEVICE_AUTHORIZATION,
            )
        yield Static("", id="oauth-status", classes="auth-instruction")
        yield Static("", id="oauth-error", classes="auth-error")
        with Horizontal(classes="auth-actions"):
            yield Button(label="Back", id="oauth-back")
            yield Button(label="Cancel", id="oauth-cancel")

    def on_mount(self) -> None:
        """Configure browser response controls for the selected interaction."""
        if self._login_method is OAuthLoginMethod.DEVICE_AUTHORIZATION:
            self._set_browser_response_visibility(display=False)

    def set_browser_presentation(self, presentation: AuthorizationPresentationDAO) -> None:
        """Render browser URL, exact redirect URI, and opaque-response instructions.

        Args:
            presentation (AuthorizationPresentationDAO): Typed browser instructions from OAuthFlow.
        """
        self.query_one("#oauth-instruction", Static).update("Open this URL in any browser")
        self.query_one("#oauth-url", AuthorizationLink).show(url=presentation.authorize_url)
        self.query_one("#oauth-url-warning", Static).update(
            "This link signs in to your account — treat it like a password."
        )
        self.query_one("#oauth-redirect-instruction", Static).update("Slo expects this redirect URI")
        self.query_one("#oauth-redirect", Static).update(presentation.redirect_uri)
        self.query_one("#oauth-response-instruction", Static).update(
            "After approval, paste what the provider gives you here — the code it displays, "
            "or the full redirect URL"
        )
        self.query_one("#oauth-status", Static).update("Waiting for approval…")
        self._set_browser_response_visibility(display=True)

    def set_device_presentation(self, presentation: DeviceAuthorizationPresentationDAO) -> None:
        """Render a device verification URL, selectable user code, and passive status.

        Args:
            presentation (DeviceAuthorizationPresentationDAO): Safe device instructions.
        """
        self.query_one("#oauth-instruction", Static).update("Open this verification URL in any browser")
        self.query_one("#oauth-url", AuthorizationLink).show(url=presentation.verification_uri)
        self.query_one("#oauth-url-warning", Static).update("")
        self.query_one("#oauth-redirect-instruction", Static).update("Enter this code")
        code: Static = self.query_one("#oauth-redirect", Static)
        code.update(presentation.user_code)
        code.remove_class("auth-redirect")
        code.add_class("auth-device-code")
        self.query_one("#oauth-response-instruction", Static).update(
            f"Code expires in {presentation.expires_in_seconds} seconds."
        )
        self.query_one("#oauth-status", Static).update("Waiting for approval…")
        self._set_browser_response_visibility(display=False)

    def set_waiting_for_approval(self) -> None:
        """Update passive device or browser progress copy without changing controls."""
        self.query_one("#oauth-status", Static).update("Waiting for approval…")

    def set_callback_unavailable(self) -> None:
        """Downgrade a browser callback timeout while preserving manual input."""
        self.query_one("#oauth-status", Static).update(
            "Local browser did not respond. Paste your authorization response below."
        )

    def set_response_already_submitted(self) -> None:
        """Tell the user a one-attempt response queue already contains a value."""
        self.query_one("#oauth-status", Static).update("Response already submitted; waiting for provider")

    def set_error(self, *, message: str) -> None:
        """Surface a static OAuth failure inline and scroll it, with Back/Cancel, into view.

        WHAT: The browser-authorization layout is taller than the modal body at 80×24, so the
            error line and the recovery buttons would otherwise stay below the fold.
        WHO: AuthenticationScreen._render_oauth_error calls this for flow and start failures.
        WHEN: Once per failed attempt.

        Args:
            message (str): User-facing safe failure description.
        """
        self.query_one("#oauth-error", Static).update(message)
        self.query_one("#oauth-status", Static).update("Sign-in failed.")
        self.query_one(".auth-actions", Horizontal).scroll_visible(animate=False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Translate controls into typed messages or a response submission.

        Args:
            event (Button.Pressed): Textual button-press event.
        """
        if event.button.id == "oauth-back":
            self.post_message(self.BackRequested())
            return
        if event.button.id == "oauth-cancel":
            self.post_message(self.Cancelled())
            return
        if event.button.id == "oauth-submit-response":
            self._submit_authorization_response()

    def _submit_authorization_response(self) -> None:
        """Post then immediately clear one opaque pasted response."""
        response_input: Input = self.query_one("#oauth-response-input", Input)
        authorization_response: str = response_input.value
        response_input.value = ""
        self.post_message(AuthorizationResponseSubmitted(authorization_response=authorization_response))

    def _set_browser_response_visibility(self, *, display: bool) -> None:
        """Show or hide only controls irrelevant to device authorization."""
        self.query_one("#oauth-response-instruction").display = display
        self.query_one("#oauth-response-row").display = display
        for widget_id in ("#oauth-response-input", "#oauth-submit-response"):
            self.query_one(widget_id).display = display
        self.query_one("#oauth-submit-response", Button).disabled = not display
