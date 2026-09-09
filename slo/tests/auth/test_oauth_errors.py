"""Tests for OAuth exception types."""

from src.auth.credential_dao import ProviderName
from src.auth.oauth_errors import (
    OAuthDeviceAuthorizationDeniedError,
    OAuthDeviceAuthorizationExpiredError,
    OAuthDeviceAuthorizationProtocolError,
    OAuthDeviceAuthorizationUnsupportedError,
    OAuthStateError,
    OAuthTimeoutError,
    OAuthTokenError,
)
import src.auth.oauth_errors as oauth_errors


class TestOAuthStateError:
    """OAuth state mismatch messages never retain secret values."""

    def test_drops_expected_and_received_values(self) -> None:
        """The error text is fixed even when a state mismatch occurs."""
        error: OAuthStateError = OAuthStateError()

        assert str(error) == "OAuth state mismatch."
        assert not hasattr(error, "expected")


class TestOAuthTokenError:
    """Token errors expose status but never response bodies."""

    def test_retains_status_and_drops_sentinel_body(self) -> None:
        """A status-only constructor cannot serialize token endpoint text."""
        error: OAuthTokenError = OAuthTokenError(status=500)

        assert error.status == 500
        assert str(error) == "OAuth token exchange failed (HTTP 500)."
        assert not hasattr(error, "body")


class TestOAuthTimeoutError:
    """OAuthTimeoutError distinguishes callback and attempt deadlines."""

    def test_messages_are_pinned_for_callback_and_attempt_kinds(self) -> None:
        """The two deadlines have distinct, safe rendering copy."""
        callback: OAuthTimeoutError = OAuthTimeoutError()
        attempt: OAuthTimeoutError = OAuthTimeoutError(kind="attempt")

        assert callback.kind == "callback"
        assert str(callback) == "OAuth sign-in timed out before the callback arrived."
        assert attempt.kind == "attempt"
        assert str(attempt) == "Sign-in was not completed in time."


class TestOAuthDeviceAuthorizationErrors:
    """Device errors retain their pinned safe copy."""

    def test_device_authorization_error_messages_are_pinned(self) -> None:
        """All device errors export exact safe messages without protocol values."""
        unsupported: OAuthDeviceAuthorizationUnsupportedError = OAuthDeviceAuthorizationUnsupportedError(
            provider=ProviderName.OPENAI
        )
        expired: OAuthDeviceAuthorizationExpiredError = OAuthDeviceAuthorizationExpiredError(
            provider=ProviderName.OPENAI
        )
        expired_after_slow_down: OAuthDeviceAuthorizationExpiredError = OAuthDeviceAuthorizationExpiredError(
            provider=ProviderName.OPENAI, after_slow_down=True
        )
        denied: OAuthDeviceAuthorizationDeniedError = OAuthDeviceAuthorizationDeniedError(
            provider=ProviderName.OPENAI
        )
        protocol: OAuthDeviceAuthorizationProtocolError = OAuthDeviceAuthorizationProtocolError(
            provider=ProviderName.OPENAI
        )

        assert str(unsupported) == "openai does not support device authorization. Use browser authorization."
        assert str(expired) == "openai device sign-in expired. Start a new attempt."
        assert "clock drift" in str(expired_after_slow_down)
        assert str(denied) == "openai denied the device sign-in request."
        assert str(protocol) == "openai returned an unexpected device authorization response."
        assert {
            "OAuthDeviceAuthorizationUnsupportedError",
            "OAuthDeviceAuthorizationExpiredError",
            "OAuthDeviceAuthorizationDeniedError",
            "OAuthDeviceAuthorizationProtocolError",
        }.issubset(set(oauth_errors.__all__))
