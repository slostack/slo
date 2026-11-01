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

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator

from config.cfg import cfg as _cfg
from src.agents.slo_agent.sessions.identity import validate_session_id

__all__ = [
    "HeadlessRunRequestDAO",
    "validate_session_id",
    "resolve_session_id",
]


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
