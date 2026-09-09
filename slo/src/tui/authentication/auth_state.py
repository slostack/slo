"""State enum for ``AuthenticationScreen`` (02.b.5)."""

from __future__ import annotations

from enum import Enum

__all__ = ["ScreenState"]


class ScreenState(str, Enum):
    """Five states the modal walks through, in order.

    ``PROVIDER`` → ``METHOD`` → (``OAUTH`` | ``API_KEY``) → ``SUCCESS``.
    """

    PROVIDER = "provider"
    METHOD = "method"
    OAUTH = "oauth"
    API_KEY = "api_key"
    SUCCESS = "success"
