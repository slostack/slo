"""Shared session identity validation, independent of CLI and environment."""

from __future__ import annotations

import re
from typing import Optional
from uuid import UUID

# Pattern for the "slug" form: only safe identifier characters, no path tokens.
_SESSION_ID_SLUG_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_session_id(*, value: str) -> str:
    """Validate a raw session-id string and return it normalised.

    Accepted forms:
    - A UUID string accepted by uuid.UUID (any version; canonical lower-case output).
    - A non-empty slug matching ``[A-Za-z0-9._-]+``.

    Rejected:
    - Strings containing ``/``, ``\\``, or ``..`` — path injection guards.
    - Empty strings.
    - Anything else that doesn't match the UUID or slug pattern.

    Args:
        value (str): Raw session-id string from the CLI or env.

    Returns:
        str: Whitespace-trimmed session-id (UUID canonicalized; slug otherwise unchanged).

    Raises:
        ValueError: If the value is empty, contains path separators, or does
            not match either accepted pattern.
    """
    stripped: str = value.strip()
    if not stripped:
        raise ValueError("session_id must not be empty")
    _reject_path_components(value=stripped)
    return _normalise_to_slug_or_uuid(value=stripped)


def _reject_path_components(*, value: str) -> None:
    """Raise ValueError if *value* contains path-traversal or separator tokens.

    Args:
        value (str): Stripped session-id string.

    Raises:
        ValueError: If the value contains ``/``, ``\\``, or ``..``.
    """
    if "/" in value or "\\" in value:
        raise ValueError(f"session_id must not contain path separators ('/' or '\\\\'): {value!r}")
    if ".." in value:
        raise ValueError(f"session_id must not contain traversal component ('..'): {value!r}")


def _normalise_to_slug_or_uuid(*, value: str) -> str:
    """Normalise *value* to a lower-cased UUID or validate it as a slug.

    Args:
        value (str): Path-component-clean session-id string.

    Returns:
        str: Lower-cased UUID string, or the original slug string.

    Raises:
        ValueError: If *value* is neither a parseable UUID nor a valid slug.
    """
    normalised_uuid: Optional[str] = _try_parse_uuid(value=value)
    if normalised_uuid is not None:
        return normalised_uuid
    if _SESSION_ID_SLUG_RE.fullmatch(value):
        return value
    raise ValueError(f"session_id must be a UUID4 or match [A-Za-z0-9._-]+, got {value!r}")


def _try_parse_uuid(*, value: str) -> Optional[str]:
    """Attempt to parse *value* as a UUID, returning its lower-cased string form.

    Args:
        value (str): Candidate UUID string.

    Returns:
        Optional[str]: Lower-cased UUID string on success, ``None`` otherwise.
    """
    try:
        return str(UUID(value)).lower()
    except ValueError:
        return None


def is_canonical_uuid_session_id(*, value: str) -> bool:
    """Check Herdr-only opaque identity without changing ordinary slug resume.

    Args:
        value (str): Supplied identity, never normalized for this stricter gate.

    Returns:
        bool: True only for the exact canonical UUID spelling.
    """
    return _try_parse_uuid(value=value) == value
