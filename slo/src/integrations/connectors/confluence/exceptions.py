"""Typed exceptions for the Confluence integration client (25.a.2)."""
from __future__ import annotations

__all__ = ["ConfluenceAPIError"]


class ConfluenceAPIError(RuntimeError):
    """Raised when the Confluence REST API returns a non-2xx response.

    Attributes:
        status_code (int): HTTP status code returned by Confluence.
        message (str): Response body text included for diagnostics.
    """

    def __init__(self, *, status_code: int, message: str) -> None:
        """Carry the status code and response body.

        Args:
            status_code (int): HTTP status code returned by Confluence.
            message (str): Response body text.
        """
        super().__init__(f"Confluence API error {status_code}: {message}")
        self.status_code: int = status_code
        self.message: str = message
