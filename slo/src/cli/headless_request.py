"""DAO and identity-resolution helpers for headless ``slo run`` requests.

Name mapping (operator → env var → Typer flag → DAO field):

  --session-id <str>          → SESSION_ID (not env-driven)       → session_id
  --resume <ref>              → SLO_RESUME_SESSION (not exported)  → resume_session_reference
  SLO_SESSION_ID env var      → SLO_SESSION_ID                     → (fallback only)
  --workspace <path>          → SLO_WORKSPACE_FILE (not exported)  → workspace_file
  --system-prompt-file <path> → (not env-driven)                   → system_prompt_file
  --append-system-prompt-file → (not env-driven)                   → append_system_prompt_file
  --orchestrator              → (not env-driven)                   → orchestrator_mode

Session-id resolution order (earliest wins):
  1. ``--resume`` reference (resolved to canonical session id by the history store)
  2. ``--session-id`` explicit literal
  3. ``SLO_SESSION_ID`` env var
  4. Fresh ``uuid4()``

The validator rejects values that contain path separators (``/``, ``\\``) or
traversal components (``..``), and permits only characters in
``[A-Za-z0-9._-]`` for non-UUID values.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, field_validator

from config.cfg import cfg as _cfg

__all__ = [
    "HeadlessRunRequestDAO",
    "validate_session_id",
    "resolve_session_id",
]

# Pattern for the "slug" form: only safe identifier characters, no path tokens.
_SESSION_ID_SLUG_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9._-]+$")


def validate_session_id(*, value: str) -> str:
    """Validate a raw session-id string and return it normalised.

    Accepted forms:
    - A valid UUID4 string (any case; stored lower-cased).
    - A non-empty slug matching ``[A-Za-z0-9._-]+``.

    Rejected:
    - Strings containing ``/``, ``\\``, or ``..`` — path injection guards.
    - Empty strings.
    - Anything else that doesn't match the UUID or slug pattern.

    Args:
        value (str): Raw session-id string from the CLI or env.

    Returns:
        str: Normalised session-id (UUID lower-cased; slug returned as-is).

    Raises:
        ValueError: If the value is empty, contains path separators, or does
            not match either accepted pattern.
    """
    stripped: str = value.strip()
    if not stripped:
        raise ValueError("session_id must not be empty")
    _reject_path_components(value=stripped)
    return _normalise_to_slug_or_uuid(value=stripped)


def resolve_session_id(
    *,
    resume_session_id: Optional[str],
    explicit_session_id: Optional[str],
) -> Optional[str]:
    """Resolve the canonical session id to use for a headless run.

    Resolution order (earliest non-None wins):
    1. *resume_session_id* — already resolved by the history store to a UUID.
    2. *explicit_session_id* — from ``--session-id`` CLI flag (pre-validated).
    3. ``SLO_SESSION_ID`` environment variable (validated on read).
    4. Returns ``None`` so callers can generate a fresh ``uuid4()``.

    Args:
        resume_session_id (Optional[str]): Session id previously resolved from
            a ``--resume`` reference via the history store.  ``None`` if
            ``--resume`` was not passed.
        explicit_session_id (Optional[str]): Pre-validated session id from the
            ``--session-id`` flag.  ``None`` if not provided.

    Returns:
        Optional[str]: Resolved session id, or ``None`` if none could be
            determined (caller should use a fresh ``uuid4()``).

    Raises:
        ValueError: If the ``SLO_SESSION_ID`` environment variable is set but
            fails validation.
    """
    if resume_session_id is not None:
        return resume_session_id
    if explicit_session_id is not None:
        return explicit_session_id
    return _session_id_from_env()


class HeadlessRunRequestDAO(BaseModel):
    """Validated parameter bag for a headless ``slo run`` invocation.

    All fields are optional; callers supply only what was provided on the CLI
    and leave the rest as ``None`` for resolution downstream.
    """

    model_config = ConfigDict(frozen=True)

    prompt: str
    as_json: bool = True
    model: Optional[str] = None
    reasoning: Optional[str] = None
    cwd: Optional[str] = None
    enable_history: bool = False
    resume_session_reference: Optional[str] = None
    session_id: Optional[str] = None
    workspace_file: Optional[Path] = None
    system_prompt_file: Optional[Path] = None
    append_system_prompt_file: Optional[Path] = None
    orchestrator_mode: bool = False

    @field_validator("session_id", mode="before")
    @classmethod
    def _validate_session_id_field(cls, value: object) -> Optional[str]:
        """Validate session_id when provided.

        Args:
            value (object): Raw field value from Pydantic.

        Returns:
            Optional[str]: Validated session id or ``None``.

        Raises:
            ValueError: If the value is set but fails validation.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError(f"session_id must be a string, got {type(value).__name__!r}")
        return validate_session_id(value=value)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


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
        ValueError: If *value* is neither a valid UUID4 nor a valid slug.
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


def _session_id_from_env() -> Optional[str]:
    """Read and validate the ``SLO_SESSION_ID`` environment variable.

    Args: none.

    Returns:
        Optional[str]: Validated session id from the env, or ``None`` if the
            variable is absent or empty.

    Raises:
        ValueError: If ``SLO_SESSION_ID`` is set but fails validation.
    """
    raw: str = (_cfg("SLO_SESSION_ID") or "").strip()
    if not raw:
        return None
    return validate_session_id(value=raw)
