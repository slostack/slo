"""PKCE and state generation for OAuth flows (02.b.3)."""

from __future__ import annotations

import base64
import hashlib
import secrets

__all__ = [
    "code_challenge_s256",
    "generate_code_verifier",
    "generate_state",
]

_VERIFIER_BYTES: int = 32
_STATE_BYTES: int = 16


def generate_code_verifier() -> str:
    """Return a URL-safe random ``code_verifier`` (RFC 7636 §4.1).

    Returns:
        str: 43-character URL-safe base64 string, no padding.
    """
    raw: bytes = secrets.token_bytes(_VERIFIER_BYTES)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def code_challenge_s256(*, verifier: str) -> str:
    """Return the S256 ``code_challenge`` derived from ``verifier``.

    Args:
        verifier (str): The verifier returned by ``generate_code_verifier``.

    Returns:
        str: URL-safe base64 SHA-256 of ``verifier``, no padding.
    """
    digest: bytes = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def generate_state() -> str:
    """Return a URL-safe random ``state`` for CSRF protection.

    Returns:
        str: 22-character URL-safe base64 string, no padding.
    """
    raw: bytes = secrets.token_bytes(_STATE_BYTES)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
