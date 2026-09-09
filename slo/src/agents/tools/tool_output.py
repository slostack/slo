"""Typed display-only snapshots from streaming-capable core tools."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

__all__ = ["ToolOutputUpdateDAO"]


class ToolOutputUpdateDAO(BaseModel):
    """One accumulated partial-output snapshot for an in-flight tool call.

    WHAT: Carries a renderable latest output state, not a raw output delta.
    WHO: Produced by core tools, published by the executor, and consumed by the
        TUI and trusted plugin observers.
    WHEN: While a streaming tool runs; it never becomes model context.
    """

    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    tool_name: str
    content_snapshot: str
    truncated: bool = False
    full_output_path: Optional[str] = None
