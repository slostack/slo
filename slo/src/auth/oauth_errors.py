"""OAuth-flow exception types (02.b.3).

All three are caught at the modal layer (02.b.5) and translated to
inline error text.
"""

from __future__ import annotations

__all__ = [
    "OAuthCallbackPortInUseError",
    "OAuthStateError",
    "OAuthTimeoutError",
    "OAuthTokenError",
]


class OAuthTimeoutError(RuntimeError):
    """Raised when the user did not complete sign-in before the timeout."""

    def __init__(self) -> None:
        """Carry a user-facing message."""
        super().__init__("OAuth sign-in timed out before the callback arrived.")


class OAuthStateError(RuntimeError):
    """Raised when the callback's ``state`` query param does not match."""

    def __init__(self, *, expected: str, got: str) -> None:
        """Carry both sides of the mismatch for debugging.

        Args:
            expected (str): The state value we sent.
            got (str): The state value we received.
        """
        super().__init__(f"OAuth state mismatch (expected={expected!r}, got={got!r}).")
        self.expected: str = expected
        self.got: str = got


class OAuthTokenError(RuntimeError):
    """Raised when the token endpoint returns a non-2xx response."""

    def __init__(self, *, status: int, body: str) -> None:
        """Carry status and truncated body for debugging.

        Args:
            status (int): HTTP status code.
            body (str): First 1024 chars of the response body.
        """
        super().__init__(f"OAuth token exchange failed (HTTP {status}): {body[:1024]}")
        self.status: int = status
        self.body: str = body


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
