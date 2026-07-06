"""Tests for OAuth exception types (02.b.3)."""
from src.auth.oauth_errors import (
    OAuthStateError,
    OAuthTimeoutError,
    OAuthTokenError,
)


class TestOAuthStateError:
    """``OAuthStateError`` carries both sides of the mismatch."""

    def test_carries_expected_and_got(self) -> None:
        """Public attrs preserved for debugging."""
        exc: OAuthStateError = OAuthStateError(expected="abc", got="xyz")
        assert exc.expected == "abc"
        assert exc.got == "xyz"
        assert "abc" in str(exc) and "xyz" in str(exc)


class TestOAuthTokenError:
    """``OAuthTokenError`` carries status + truncated body."""

    def test_truncates_long_body(self) -> None:
        """Body in message is capped at 1024 chars."""
        big: str = "x" * 5000
        exc: OAuthTokenError = OAuthTokenError(status=500, body=big)
        assert "500" in str(exc)
        assert len(str(exc)) < 5000


class TestOAuthTimeoutError:
    """``OAuthTimeoutError`` has a sensible default message."""

    def test_default_message_mentions_timeout(self) -> None:
        """Default message hints at what happened."""
        exc: OAuthTimeoutError = OAuthTimeoutError()
        assert "timed out" in str(exc).lower()
