"""Shared helpers for reading timeout and count values from environment variables.

Invalid or non-positive env-var values are logged and the default (or ``None``
for the optional helper) is returned rather than raising.  This prevents a
malformed operator override from crashing the process at import time — Spec
53.a.4 requires invalid inputs to fall back gracefully.
"""

from __future__ import annotations

import os
from typing import Optional

__all__ = [
    "positive_float_env",
    "optional_positive_float_env",
    "positive_int_env",
]


def positive_float_env(
    *,
    primary_name: str,
    alias_name: Optional[str] = None,
    default: float,
) -> float:
    """Read a positive float from an environment variable, falling back gracefully.

    Checks the primary variable first; then the alias when provided; then the
    default.  When a variable is present but contains an invalid or
    non-positive value, a warning is logged and the *default* is returned so
    the process starts cleanly rather than crashing at import time.

    Args:
        primary_name (str): Canonical environment-variable name to check first.
        alias_name (str, optional): Legacy or alternative name to try when the
            primary is absent.  Defaults to ``None``.
        default (float): Value returned when no variable is set, or when the
            resolved value is invalid.

    Returns:
        float: Resolved positive float, or *default* on any parse failure.
    """
    raw: Optional[str] = _resolve_raw(
        primary_name=primary_name,
        alias_name=alias_name,
    )
    if raw is None:
        return default
    parsed: Optional[float] = _try_parse_positive_float(
        raw=raw,
        source=primary_name,
        fallback=default,
    )
    return parsed if parsed is not None else default


def optional_positive_float_env(
    *,
    primary_name: str,
    alias_name: Optional[str] = None,
) -> Optional[float]:
    """Read an optional positive float from an environment variable.

    Returns ``None`` when the variable (and optional alias) are absent or empty.
    When a value is present but invalid or non-positive, a warning is logged
    and ``None`` is returned (the "feature disabled" state) rather than
    raising.

    Args:
        primary_name (str): Canonical environment-variable name to check first.
        alias_name (str, optional): Legacy or alternative name to try when the
            primary is absent.  Defaults to ``None``.

    Returns:
        Optional[float]: Parsed positive float, or ``None`` if no variable is
            set or the value is invalid.
    """
    raw: Optional[str] = _resolve_raw(
        primary_name=primary_name,
        alias_name=alias_name,
    )
    if raw is None:
        return None
    return _try_parse_positive_float(
        raw=raw,
        source=primary_name,
        fallback=None,
    )


def positive_int_env(
    *,
    primary_name: str,
    alias_name: Optional[str] = None,
    default: int,
) -> int:
    """Read a positive integer from an environment variable, falling back gracefully.

    Checks the primary variable first; then the alias when provided; then the
    default.  When a variable is present but contains an invalid or
    non-positive value, a warning is logged and the *default* is returned so
    the process starts cleanly rather than crashing at import time.

    Args:
        primary_name (str): Canonical environment-variable name to check first.
        alias_name (str, optional): Legacy or alternative name to try when the
            primary is absent.  Defaults to ``None``.
        default (int): Value returned when no variable is set, or when the
            resolved value is invalid.

    Returns:
        int: Resolved positive integer, or *default* on any parse failure.
    """
    raw: Optional[str] = _resolve_raw(
        primary_name=primary_name,
        alias_name=alias_name,
    )
    if raw is None:
        return default
    parsed: Optional[int] = _try_parse_positive_int(
        raw=raw,
        source=primary_name,
        fallback=default,
    )
    return parsed if parsed is not None else default


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_raw(
    *,
    primary_name: str,
    alias_name: Optional[str],
) -> Optional[str]:
    """Return the first non-empty value from primary then alias env vars.

    Args:
        primary_name (str): Primary environment variable name.
        alias_name (Optional[str]): Fallback environment variable name, or ``None``.

    Returns:
        Optional[str]: Stripped string value, or ``None`` if neither variable is set.
    """
    primary_value: str = os.environ.get(primary_name, "").strip()
    if primary_value:
        return primary_value

    if alias_name is None:
        return None

    alias_value: str = os.environ.get(alias_name, "").strip()
    return alias_value if alias_value else None


def _try_parse_positive_float(
    *,
    raw: str,
    source: str,
    fallback: Optional[float],
) -> Optional[float]:
    """Attempt to parse *raw* as a positive float, returning *fallback* on failure.

    Logs a warning (not an exception) on parse failure or non-positive value so
    operators see a clear message without an unhandled exception.

    Args:
        raw (str): String to parse.
        source (str): Environment variable name used in log messages.
        fallback (Optional[float]): Value to return when parsing fails.

    Returns:
        Optional[float]: Parsed positive float, or *fallback*.
    """
    try:
        value: float = float(raw)
    except ValueError:
        from config.logger import log_info  # noqa: PLC0415
        log_info(
            msg="timeout_env_invalid_value",
            env_var=source,
            raw_value=raw,
            reason="not a valid float — using default",
        )
        return fallback
    if value <= 0:
        from config.logger import log_info  # noqa: PLC0415
        log_info(
            msg="timeout_env_non_positive",
            env_var=source,
            raw_value=raw,
            reason="value must be strictly positive — using default",
        )
        return fallback
    return value


def _try_parse_positive_int(
    *,
    raw: str,
    source: str,
    fallback: Optional[int],
) -> Optional[int]:
    """Attempt to parse *raw* as a positive integer, returning *fallback* on failure.

    Logs a warning (not an exception) on parse failure or non-positive value so
    operators see a clear message without an unhandled exception.

    Args:
        raw (str): String to parse.
        source (str): Environment variable name used in log messages.
        fallback (Optional[int]): Value to return when parsing fails.

    Returns:
        Optional[int]: Parsed positive integer, or *fallback*.
    """
    try:
        value: int = int(raw)
    except ValueError:
        from config.logger import log_info  # noqa: PLC0415
        log_info(
            msg="timeout_env_invalid_value",
            env_var=source,
            raw_value=raw,
            reason="not a valid integer — using default",
        )
        return fallback
    if value <= 0:
        from config.logger import log_info  # noqa: PLC0415
        log_info(
            msg="timeout_env_non_positive",
            env_var=source,
            raw_value=raw,
            reason="value must be strictly positive — using default",
        )
        return fallback
    return value
