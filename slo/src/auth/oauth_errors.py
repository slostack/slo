"""OAuth-flow exception types (02.b.3).

All three are caught at the modal layer (02.b.5) and translated to
inline error text.
"""

from __future__ import annotations

from src.auth.credential_dao import ProviderName

__all__ = [
    "OAuthCallbackPortInUseError",
    "OAuthDeviceAuthorizationDeniedError",
    "OAuthDeviceAuthorizationExpiredError",
    "OAuthDeviceAuthorizationProtocolError",
    "OAuthDeviceAuthorizationUnsupportedError",
    "OAuthStateError",
    "OAuthTimeoutError",
    "OAuthTokenError",
]


class OAuthTimeoutError(RuntimeError):
    """Raised when a sign-in deadline elapses before completion.

    ``kind`` distinguishes the short loopback-callback deadline from the
    whole browser/manual attempt deadline so the UI can render the correct
    copy; it is the only difference between the two deadline outcomes.
    """

    def __init__(self, *, kind: str = "callback") -> None:
        """Create the safe message for one sign-in deadline kind.

        WHO: OAuth browser and manual flows raise this at their deadlines.
        WHEN: A callback or whole sign-in attempt ends before a credential exists.

        Args:
            kind (str, optional): ``"callback"`` or ``"attempt"`` deadline meaning.
                Defaults to ``"callback"``.
        """
        self.kind: str = kind
        if kind == "attempt":
            super().__init__("Sign-in was not completed in time.")
        else:
            super().__init__("OAuth sign-in timed out before the callback arrived.")


class OAuthDeviceAuthorizationUnsupportedError(RuntimeError):
    """The selected provider does not implement device authorization."""

    def __init__(self, *, provider: ProviderName) -> None:
        """Create a safe unsupported-method error.

        WHO: OAuth providers raise this when device authorization is absent.
        WHEN: A caller selects device authorization for a browser-only provider.
        """
        super().__init__(
            f"{provider.value} does not support device authorization. Use browser authorization."
        )
        self.provider: ProviderName = provider


class OAuthDeviceAuthorizationExpiredError(RuntimeError):
    """The device authorization attempt reached its deadline."""

    def __init__(self, *, provider: ProviderName, after_slow_down: bool = False) -> None:
        """Create a safe expiry error for one device attempt.

        WHO: DeviceAuthorizationFlow raises this after its bounded polling deadline.
        WHEN: The provider has not completed device authorization before expiry.
        """
        message: str = f"{provider.value} device sign-in expired. Start a new attempt."
        if after_slow_down:
            message = (
                f"{provider.value} device sign-in expired after slow-down responses. "
                "This is often caused by clock drift in WSL or VM environments — "
                "sync or restart the VM clock, then start a new attempt."
            )
        super().__init__(message)
        self.provider: ProviderName = provider
        self.after_slow_down: bool = after_slow_down


class OAuthDeviceAuthorizationDeniedError(RuntimeError):
    """The provider denied the device sign-in request."""

    def __init__(self, *, provider: ProviderName) -> None:
        """Create a safe provider-denial error.

        WHO: A device-authorization provider raises this after user denial.
        WHEN: Its terminal poll response rejects the current sign-in request.
        """
        super().__init__(f"{provider.value} denied the device sign-in request.")
        self.provider: ProviderName = provider


class OAuthDeviceAuthorizationProtocolError(RuntimeError):
    """The provider returned an uninterpretable device response."""

    def __init__(self, *, provider: ProviderName) -> None:
        """Create a safe malformed-device-response error.

        WHO: Device providers and the generic flow raise this for invalid payloads.
        WHEN: A response cannot be safely interpreted as a supported device outcome.
        """
        super().__init__(f"{provider.value} returned an unexpected device authorization response.")
        self.provider: ProviderName = provider


class OAuthStateError(RuntimeError):
    """Raised when a supplied OAuth state does not match the active attempt."""

    def __init__(self) -> None:
        """Create a fixed mismatch message without retaining either secret value."""
        super().__init__("OAuth state mismatch.")


class OAuthTokenError(RuntimeError):
    """Raised when the token endpoint returns a non-2xx response.

    The response body is deliberately dropped: provider error bodies can echo
    request secrets, and no log, UI, snapshot, or string conversion may carry them.
    """

    def __init__(self, *, status: int) -> None:
        """Record only the HTTP status for a rejected token request."""
        super().__init__(f"OAuth token exchange failed (HTTP {status}).")
        self.status: int = status


class OAuthCallbackPortInUseError(RuntimeError):
    """Raised when a provider-required fixed callback port is already bound.

    Fired only on the fixed-bind path — when a provider declares a
    ``CallbackBind`` and the local socket bind fails with ``EADDRINUSE``.
    Ephemeral binds (``port=0``) cannot collide and never raise this.
    There is no fallback port: the OAuth app's registered redirect URI
    is exact-match validated server-side, so the user must free the
    port (``lsof -i :<port>`` then kill the holder) and retry.

    Attributes:
        port (int): The fixed port that could not be bound.
    """

    def __init__(self, *, port: int) -> None:
        """Carry the contested port for renderers.

        Args:
            port (int): The fixed port the provider required.
        """
        super().__init__(
            f"OAuth callback port {port} is already in use. "
            f"Free it (e.g. `lsof -i :{port}`) and retry sign-in.",
        )
        self.port: int = port
