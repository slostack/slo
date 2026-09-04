"""Shared environment and capture-file policy for ``slo run`` children.

Sub-spec 71.a.0.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import IO, Optional

from src.agents.slo_agent.orchestrator.layout import OrchestrationLayout

__all__ = ["build_headless_child_env", "open_capture_file_append"]

_ENV_ALLOWLIST_PREFIXES: tuple[str, ...] = ("SLO_",)
_ENV_ALLOWLIST_EXACT: tuple[str, ...] = ("PATH", "HOME", "LANG", "TERM", "PYENV_ROOT", "PYENV_VERSION")
_ENV_SECRET_MARKERS: tuple[str, ...] = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def build_headless_child_env(
    *,
    workflow_id: Optional[str] = None,
    extra: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build the non-secret environment for a spawned headless child.

    WHAT: Keeps exact process basics and non-secret SLO settings, then adds
        caller-supplied workflow and per-spawn identity values.
    WHO: Called by detached workflow and sub-agent process spawn owners.
    WHEN: Immediately before a ``slo run`` child is created.

    Args:
        workflow_id (Optional[str]): Workflow identifier to inject when set.
        extra (Optional[dict[str, str]]): Additional non-empty child variables.

    Returns:
        dict[str, str]: Sanitized child environment.
    """
    child_env: dict[str, str] = _allowlisted_parent_env()
    _add_workflow_id(child_env=child_env, workflow_id=workflow_id)
    _add_nonempty_extra(child_env=child_env, extra=extra)
    return child_env


def open_capture_file_append(*, history_root: Path, session_id: str, name: str) -> IO[bytes]:
    """Open a session-level capture file for binary append.

    WHAT: Creates the owning session directory and opens its named capture file.
    WHO: Called by detached workflow launch code before spawning an orchestrator.
    WHEN: Once for each stdout or stderr capture attached to that process.

    Args:
        history_root (Path): Root containing session history directories.
        session_id (str): Session owning the capture.
        name (str): Capture file name.

    Returns:
        IO[bytes]: Open binary append file handle.
    """
    capture_path: Path = OrchestrationLayout.capture_path(
        history_root=history_root,
        session_id=session_id,
        name=name,
    )
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    return capture_path.open("ab")


def _allowlisted_parent_env() -> dict[str, str]:
    """Return allowed non-secret values from the current process environment."""
    child_env: dict[str, str] = {}
    for name, value in os.environ.items():
        if name in _ENV_ALLOWLIST_EXACT:
            child_env[name] = value
            continue
        if name.startswith(_ENV_ALLOWLIST_PREFIXES) and not _is_secret_env_name(name=name):
            child_env[name] = value
    return child_env


def _add_workflow_id(*, child_env: dict[str, str], workflow_id: Optional[str]) -> None:
    """Add the workflow identifier when the spawn is workflow-owned."""
    if workflow_id is not None:
        child_env["SLO_WORKFLOW_ID"] = workflow_id


def _add_nonempty_extra(*, child_env: dict[str, str], extra: Optional[dict[str, str]]) -> None:
    """Add only non-empty caller-supplied child environment values."""
    for name, value in (extra or {}).items():
        if value:
            child_env[name] = value


def _is_secret_env_name(*, name: str) -> bool:
    """Return whether an environment variable name contains a secret marker."""
    upper_name: str = name.upper()
    return any(marker in upper_name for marker in _ENV_SECRET_MARKERS)
