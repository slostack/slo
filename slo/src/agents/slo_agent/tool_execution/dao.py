"""DAOs for Slo tool-execution planning and scheduling."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


__all__ = [
    "ToolCallEnvelopeDAO",
    "ToolConcurrencyClass",
    "ToolExecutionMode",
    "ToolExecutionPlanDAO",
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
