"""Typed optional SDK retry overrides for provider construction tests."""

from typing import TypedDict


class SDKRetryOptions(TypedDict, total=False):
    """Omit the retry count to exercise the real constructor default."""

    max_retries: int
