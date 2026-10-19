"""Context DAOs for orchestrator and sub-agent capture files.

These data models are written to disk as JSON artefacts at spawn time and
on the first user-message of an orchestrator session, allowing the
workflow visualizer to surface full invocation context for debugging.

File destinations:
- ``orchestrator_context.json``: written to
  ``~/.slo/sessions/history/<parent_session_id>/orchestrator_context.json``
- ``spawn_context.json``: written to
  ``~/.slo/sessions/history/<parent_session_id>/children/<child_session_id>/spawn_context.json``
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.agents.slo_agent.orchestrator.dao import canonical_uuid

__all__ = [
    "OrchestratorContextDAO",
    "SpawnContextDAO",
    "dump_json_bytes",
]


class OrchestratorContextDAO(BaseModel):
    """Invocation context for the parent orchestrator session.

    Written once at session start (on the first user message) to
    ``orchestrator_context.json`` in the parent session history directory.

    Attributes:
        system_prompt (str): Assembled system prompt for the orchestrator.
        user_prompt (str): Content of the first user message that triggered
            the workflow. Empty string when written before the first message.
        model (Optional[str]): Active model name at recording time.
        recorded_at (str): ISO 8601 datetime string with UTC timezone.
    """

    model_config = ConfigDict(extra="forbid")

    system_prompt: str
    user_prompt: str
    model: Optional[str] = None
    recorded_at: str

    @classmethod
    def build(
        cls,
        *,
        system_prompt: str,
        user_prompt: str,
        model: Optional[str],
    ) -> "OrchestratorContextDAO":
        """Build an ``OrchestratorContextDAO`` with the current UTC timestamp.

        Args:
            system_prompt (str): Assembled system prompt.
            user_prompt (str): Triggering user message content.
            model (Optional[str]): Active model name.

        Returns:
            OrchestratorContextDAO: Populated DAO with ISO timestamp.
        """
        return cls(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=model,
            recorded_at=datetime.now(tz=timezone.utc).isoformat(),
        )


class SpawnContextDAO(BaseModel):
    """Invocation context for a spawned sub-agent process.

    Written once per child by ``SubAgentProcess._write_spawn_context`` at
    the start of ``run()``, before stdout pumping begins.

    Attributes:
        task_id (str): Caller-assigned stable task identifier.
        prompt (str): Natural-language task for the child agent.
        model (Optional[str]): Effective model for the child; ``None`` when
            inherited from the orchestrator.
        reasoning_level (Optional[str]): Per-task reasoning budget override;
            ``None`` when inherited.
        cwd (Optional[str]): Working directory for the child; ``None`` when
            inherited from the orchestrator.
        inactivity_timeout_seconds (float): Effective inactivity timeout at
            spawn time (snapshot of the module-level constant).
        system_prompt (str): Assembled system prompt for the child agent.
        recorded_at (str): ISO 8601 datetime string with UTC timezone.
        execution_id (str): Runtime incarnation that owns this context. Excluded
            from serialization so released readers keep decoding the file; the
            ``execution.v1.json`` sibling binds the bytes to the incarnation.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    prompt: str
    model: Optional[str] = None
    reasoning_level: Optional[str] = None
    cwd: Optional[str] = None
    inactivity_timeout_seconds: float
    system_prompt: str
    recorded_at: str
    execution_id: str = Field(default="", exclude=True)

    @field_validator("execution_id")
    @classmethod
    def _validate_execution_id(cls, value: str) -> str:
        """Accept an empty reader-side identity or a canonical incarnation UUID."""
        return value if value == "" else canonical_uuid(value=value)

    @classmethod
    def build(
        cls,
        *,
        task_id: str,
        prompt: str,
        system_prompt: str,
        inactivity_timeout_seconds: float,
        model: Optional[str],
        reasoning_level: Optional[str],
        cwd: Optional[str],
        execution_id: str = "",
    ) -> "SpawnContextDAO":
        """Build a ``SpawnContextDAO`` with the current UTC timestamp.

        Args:
            task_id (str): Stable task identifier.
            prompt (str): Task prompt for the child.
            system_prompt (str): Assembled child system prompt.
            inactivity_timeout_seconds (float): Effective inactivity timeout.
            model (Optional[str]): Effective model name.
            reasoning_level (Optional[str]): Reasoning level override.
            cwd (Optional[str]): Working directory override.
            execution_id (str): Registry-captured incarnation UUID. Defaults to an
                empty identity for reader-side fixtures that do not own an execution.

        Returns:
            SpawnContextDAO: Populated DAO with ISO timestamp.
        """
        return cls(
            execution_id=execution_id,
            task_id=task_id,
            prompt=prompt,
            model=model,
            reasoning_level=reasoning_level,
            cwd=cwd,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
            system_prompt=system_prompt,
            recorded_at=datetime.now(tz=timezone.utc).isoformat(),
        )


def dump_json_bytes(model: BaseModel) -> bytes:
    """Serialize a context DAO to compact UTF-8 encoded JSON bytes.

    Uses ``exclude_none=True`` so optional fields absent in the source
    do not appear in the serialized output, keeping capture files lean.

    Args:
        model (BaseModel): A Pydantic model instance to serialize.

    Returns:
        bytes: UTF-8 encoded compact JSON (no indentation).
    """
    return model.model_dump_json(indent=None, exclude_none=True).encode("utf-8")
