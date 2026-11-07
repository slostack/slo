"""DAOs for Slo tool-execution planning and scheduling."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal, Optional, Protocol, runtime_checkable
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool


@runtime_checkable
class ToolCancellationPort(Protocol):
    """Trusted cancellation promise; acknowledgement includes joined owned leaves."""

    async def cancel_and_join(self, *, invocation: "ToolInvocationDAO") -> ToolMessage:
        """Join invocation and leaves before returning an exact error acknowledgement."""
        ...


__all__ = [
    "ToolCallEnvelopeDAO",
    "ToolConcurrencyClass",
    "ToolExecutionMode",
    "ToolExecutionPlanDAO",
    "ToolGroupMetadataDAO",
    "ToolResultDAO",
]


class ToolConcurrencyClass(str, Enum):
    """Coarse-grained scheduler safety classes for Slo tools."""

    READ_ONLY = "read_only"
    MUTATING = "mutating"


class ToolExecutionMode(str, Enum):
    """Supported tool execution policies for Slo."""

    SEQUENTIAL = "sequential"
    CONCURRENT_READS = "concurrent_reads"
    UNSAFE_FULL_CONCURRENCY = "unsafe_full_concurrency"


class ToolCallEnvelopeDAO(BaseModel):
    """One source-ordered tool call plus scheduler metadata."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_index: int
    call: dict[str, Any]
    concurrency_class: ToolConcurrencyClass


class ToolResultDAO(BaseModel):
    """Structured live tool content plus optional durable image metadata.

    WHAT: Separates multimodal content sent to the current LLM turn from an
        image reference persisted by the history trace.
    WHO: Returned by ``ReadTool`` for images and split by ``ToolExecutor``
        when it constructs the success-path ``ToolMessage``.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    content: str | list[dict[str, Any]]
    image_reference: Optional[str] = None


class ToolExecutionPlanDAO(BaseModel):
    """Planned execution of one assistant-emitted tool batch."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_concurrently: bool
    calls: list[ToolCallEnvelopeDAO]


_TOOL_GROUP_SCHEMA_VERSION: Literal[1] = 1
_TOOL_CALL_ID_MAX_LENGTH: int = 512


def _require_canonical_uuid(*, value: str, field_name: str) -> None:
    """Reject a UUID that is not already in canonical lowercase string form."""
    try:
        parsed: UUID = UUID(value)
    except (AttributeError, ValueError) as error:
        raise ValueError(f"tool_group_metadata_invalid_{field_name}") from error
    if str(parsed) != value:
        raise ValueError(f"tool_group_metadata_invalid_{field_name}")


class ToolGroupMetadataDAO(BaseModel):
    """Canonical ``tool_group_v1`` metadata for marked tool opening and result traces.

    WHAT: Correlates one assistant tool batch with its source-ordered calls,
        the session attempt that emitted it and the actual core result status
        when a matching tool result exists.
    WHO: Session history writers attach it under ``payload.metadata``; raw
        validators and replay projectors read it back.
    WHEN: Only trusted marked ``tool_call``/``tool_result`` traces; plugins and
        subscribers can never supply proof.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = Field(
        default=_TOOL_GROUP_SCHEMA_VERSION,
        description="Tool-group metadata schema version; unknown versions fail closed.",
    )
    group_id: str = Field(
        description="Canonical UUID5 of the attempt turn and iteration: tool-group:<iteration>.",
    )
    attempt_turn_id: str = Field(
        description="Canonical session attempt turn UUID, not the logical message-run UUID.",
    )
    iteration: int = Field(
        ge=0,
        description="Outer ReAct iteration within this session attempt.",
    )
    tool_result_status: Optional[Literal["success", "error"]] = Field(
        default=None,
        description="Actual core tool-result status; omitted on openings and no-start dispositions.",
    )
    tool_call_ids: tuple[str, ...] = Field(
        description="Nonempty distinct bounded printable call IDs in source order.",
    )
    opened_at: datetime = Field(
        description="Aware UTC timestamp created once on the first complete opening.",
    )
    disposition: Literal["opening", "not_started"] = Field(
        default="opening",
        description="Opening/result metadata or affirmative no-start after a joined yield.",
    )

    @field_validator("group_id")
    @classmethod
    def _validate_group_id(cls, value: str) -> str:
        """Require the canonical UUID string form before derivation is checked."""
        _require_canonical_uuid(value=value, field_name="group_id")
        return value

    @field_validator("attempt_turn_id")
    @classmethod
    def _validate_attempt_turn_id(cls, value: str) -> str:
        """Require a canonical session attempt UUID string."""
        _require_canonical_uuid(value=value, field_name="attempt_turn_id")
        return value

    @field_validator("tool_call_ids")
    @classmethod
    def _validate_tool_call_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """Require an ordered, nonempty, distinct and bounded printable call list."""
        if not value:
            raise ValueError("tool_group_metadata_invalid_tool_call_ids")
        if len(set(value)) != len(value):
            raise ValueError("tool_group_metadata_invalid_tool_call_ids")
        for call_id in value:
            if not call_id.strip() or not call_id.isprintable():
                raise ValueError("tool_group_metadata_invalid_tool_call_ids")
            if len(call_id) > _TOOL_CALL_ID_MAX_LENGTH:
                raise ValueError("tool_group_metadata_invalid_tool_call_ids")
        return value

    @field_validator("opened_at")
    @classmethod
    def _validate_opened_at(cls, value: datetime) -> datetime:
        """Require an aware UTC opening timestamp rather than a naive local time."""
        offset: Optional[timedelta] = value.utcoffset()
        if value.tzinfo is None or offset is None or offset != timedelta(0):
            raise ValueError("tool_group_metadata_invalid_opened_at")
        return value

    @model_validator(mode="after")
    def _validate_group_correlation(self) -> "ToolGroupMetadataDAO":
        """Bind the group ID to its attempt/iteration and forbid no-start results."""
        expected_group_id: str = str(
            uuid5(
                namespace=UUID(self.attempt_turn_id),
                name="tool-group:" + str(self.iteration),
            )
        )
        if self.group_id != expected_group_id:
            raise ValueError("tool_group_metadata_invalid_group_id")
        if self.disposition == "not_started" and self.tool_result_status is not None:
            raise ValueError("tool_group_metadata_invalid_tool_result_status")
        return self


ToolYieldMode = Literal["defer", "cancel_confirmed"]


class ToolInvocationDAO(BaseModel):
    """Exact original tool and invocation-message task owned by one executor."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, arbitrary_types_allowed=True)

    tool: BaseTool = Field(exclude=True, repr=False, description="Original registered concrete tool.")
    tool_call_id: str = Field(
        min_length=1, max_length=512, description="Exact bounded printable call identity."
    )
    task: asyncio.Task[ToolMessage] = Field(
        exclude=True, repr=False, description="Exact message invocation task."
    )

    @field_validator("tool_call_id")
    @classmethod
    def validate_call_id(cls, value: str) -> str:
        """Reject blank or nonprintable invocation identity."""
        if not value.strip() or not value.isprintable():
            raise ValueError("tool_yield_capability_invalid")
        return value


class ToolCancellationRegistrationDAO(BaseModel):
    """Explicit trusted identity registration; never inferred from names or metadata."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, arbitrary_types_allowed=True)

    tool: BaseTool = Field(exclude=True, repr=False, description="Strongly retained original tool identity.")
    port: ToolCancellationPort = Field(
        exclude=True, repr=False, description="Trusted cancel_and_join implementation."
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: ToolCancellationPort) -> ToolCancellationPort:
        """Require the explicit cancellation protocol method at construction."""
        if not callable(getattr(value, "cancel_and_join", None)):
            raise ValueError("tool_yield_capability_invalid")
        return value


class ToolYieldOutcomeDAO(BaseModel):
    """Validated terminal provenance or a nonterminal deferred observation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    tool_call_id: str = Field(min_length=1, max_length=512, description="Exact invocation identity.")
    disposition: Literal["completed", "cancelled", "not_started", "deferred"] = Field(
        description="Truthful terminal provenance; cancellation does not imply rollback."
    )
    result: Optional[ToolMessage] = Field(
        default=None, description="Actual result or validated error acknowledgement."
    )

    @model_validator(mode="after")
    def validate_result(self) -> "ToolYieldOutcomeDAO":
        """Forbid invented success, mismatched IDs or deferred terminal messages."""
        if not self.tool_call_id.strip() or not self.tool_call_id.isprintable():
            raise ValueError("tool_yield_outcome_invalid")
        if self.disposition == "deferred":
            if self.result is not None:
                raise ValueError("tool_yield_outcome_invalid")
            return self
        if self.result is None or self.result.tool_call_id != self.tool_call_id:
            raise ValueError("tool_yield_outcome_invalid")
        if self.disposition in ("cancelled", "not_started") and self.result.status != "error":
            raise ValueError("tool_yield_outcome_invalid")
        return self
