"""Persisted user preferences for model and reasoning defaults (26.a.1).

Stores and loads ``~/.slo/global/preferences.json``.  The store is the
only object permitted to read or write that file.  All writes are atomic
(temp-file + rename) to guard against mid-write crashes.

Resolution is consulted by ``TyperDispatch._build_session_config`` before
``cfg("DEFAULT_MODEL_NAME")`` so saved preferences take precedence over
environment defaults on every new session boot.
"""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict
from typing import Optional

from src.agents.reasoning_capabilities import ReasoningLevel

__all__ = [
    "UserPreferencesDAO",
    "UserPreferencesStoreCorruptError",
]


class UserPreferencesStoreCorruptError(RuntimeError):
    """Raised when ``~/.slo/global/preferences.json`` fails to parse or validate.

    Attributes:
        path (Path): The corrupt file's location on disk.
    """

    def __init__(self, *, path: Path) -> None:
        """Carry the path so callers can include it in user-facing messages.

        Args:
            path (Path): The corrupt preferences file.
        """
        super().__init__(f"Preferences file at {path} is not valid JSON or schema.")
        self.path: Path = path


class UserPreferencesDAO(BaseModel):
    """Persisted user preferences for model and reasoning defaults.

    Attributes:
        schema_version (int): Bumped on incompatible schema changes.
        default_model_name (Optional[str]): The model the operator prefers
            across sessions.  ``None`` means no preference — the env or
            cfg default applies.
        default_reasoning_level (Optional[ReasoningLevel]): The reasoning
            level the operator prefers across sessions.  ``None`` means
            no preference — the model's built-in default applies.
        default_model_pool (Optional[str]): Comma-separated, priority-ordered
            list of model names the operator prefers as a fallback pool (same
            format as ``SLO_MODEL_POOL``).  ``None`` means no preference — the
            session runs single-model unless ``SLO_MODEL_POOL`` is set.
    """

    model_config = ConfigDict()

    schema_version: int = 1
    default_model_name: Optional[str] = None
    default_reasoning_level: Optional[ReasoningLevel] = None
    default_model_pool: Optional[str] = None
