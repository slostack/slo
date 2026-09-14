"""Tests for PKCE helpers (02.b.3)."""

import base64
import hashlib

from src.auth.pkce import (
    code_challenge_s256,
    generate_code_verifier,
    generate_state,
)


class TestGenerateCodeVerifier:
    """``generate_code_verifier`` shape contracts."""

    def test_returns_43_char_url_safe_string(self) -> None:
        """RFC 7636 §4.1: ≥43 chars, URL-safe base64, no padding."""
        verifier: str = generate_code_verifier()
        assert len(verifier) == 43
        assert "=" not in verifier

    def test_two_calls_return_different_values(self) -> None:
        """Verifier must be unpredictable across calls."""
        assert generate_code_verifier() != generate_code_verifier()


class TestCodeChallengeS256:
    """``code_challenge_s256`` is the SHA-256 of the verifier."""

    def test_matches_manual_sha256(self) -> None:
        """Hand-computed S256 matches the helper's output."""
        verifier: str = "fixed-test-verifier"
        expected: str = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        )

        assert code_challenge_s256(verifier=verifier) == expected


class TestGenerateState:
    """``generate_state`` returns a 22-char URL-safe string."""

    def test_returns_22_char_url_safe_string(self) -> None:
        """16 random bytes → 22 base64 chars without padding."""
        state: str = generate_state()
        assert len(state) == 22
        assert "=" not in state
