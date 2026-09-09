"""Typed exceptions for the Jira integration client (25.a.3)."""

from __future__ import annotations

__all__ = ["JiraAPIError"]


class JiraAPIError(RuntimeError):
    """Raised when the Jira REST API returns a non-2xx response.

    Attributes:
        status_code (int): HTTP status code returned by Jira.
        message (str): Response body text included for diagnostics.
    """

    def __init__(self, *, status_code: int, message: str) -> None:
        """Carry the HTTP status code and response body.

        Args:
            status_code (int): HTTP status code.
            message (str): Response body text.
        """
        super().__init__(f"Jira API error {status_code}: {message}")
        self.status_code: int = status_code
        self.message: str = message
