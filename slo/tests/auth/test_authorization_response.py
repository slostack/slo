"""Tests for safe manual browser authorization response parsing."""

import pytest

from src.auth.oauth_errors import OAuthStateError
from src.auth.oauth_flow import AuthorizationResponseParser


class TestAuthorizationResponseParser:
    """The parser accepts every first-class remote-browser response form."""

    @pytest.mark.parametrize(
        "response",
        [
            "https://provider.example/callback?code=code-value&state=expected-state",
            "code-value#expected-state",
            "code=code-value&state=expected-state",
            "code-value",
        ],
    )
    def test_parse_returns_code_for_each_documented_form(self, response: str) -> None:
        """State is optional to users and code remains the only returned field."""
        parsed = AuthorizationResponseParser.parse(
            authorization_response=response,
            expected_state="expected-state",
        )

        assert parsed.code == "code-value"

    def test_parse_raises_when_supplied_state_mismatches(self) -> None:
        """An explicitly supplied state must still match the in-memory attempt."""
        with pytest.raises(OAuthStateError):
            AuthorizationResponseParser.parse(
                authorization_response="code-value#other-state",
                expected_state="expected-state",
            )

    def test_parse_raises_fixed_error_when_code_is_missing(self) -> None:
        """Malformed input never echoes its opaque pasted value in exception text."""
        with pytest.raises(ValueError, match="Authorization response is invalid."):
            AuthorizationResponseParser.parse(
                authorization_response="https://provider.example/callback?state=expected-state",
                expected_state="expected-state",
            )
