"""Typed contracts for Slo's trusted plugin extension system."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Optional, Union

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from src.agents.slo_agent.events.stream import AgentStreamEventDAO

__all__ = [
    "AfterToolResultPatchDAO",
    "BeforeAgentTurnDecisionDAO",
    "BeforeToolCallDecisionDAO",
    "PluginEventHandler",
    "PluginHealthDAO",
    "PluginRegistrationDAO",
    "PluginRendererFn",
    "PluginStatus",
    "PluginStatusSetter",
    "ToolOutputUpdateHandler",
]


class PluginStatus(str, Enum):
    """Lifecycle status reported for one plugin."""

    LOADED = "loaded"
    LOAD_FAILED = "load_failed"
    DISABLED = "disabled"


class PluginHealthDAO(BaseModel):
    """Operator-visible health record for one loaded plugin."""

    model_config = ConfigDict(extra="forbid")

    plugin_id: str
    source_path: str
    status: PluginStatus = PluginStatus.LOADED
    load_error: Optional[str] = None
    handler_failures: int = 0
    registered_tools: list[str] = Field(default_factory=list)
    registered_commands: list[str] = Field(default_factory=list)
    registered_renderers: list[str] = Field(default_factory=list)
    subscribed_events: list[str] = Field(default_factory=list)


PluginEventHandler = Callable[[AgentStreamEventDAO], Union[None, Awaitable[None]]]
"""Sync-or-async subscriber to one normalized agent stream event."""

PluginRendererFn = Callable[[str], str]
"""One-line renderer for raw terminal or partial tool output."""

PluginStatusSetter = Callable[[str, str], None]
"""Set or clear one derived live footer-status key."""


class BeforeToolCallDecisionDAO(BaseModel):
    """Typed result returned by one pre-tool plugin interceptor."""

    model_config = ConfigDict(extra="forbid")

    block: bool = False
    reason: Optional[str] = None
    mutated_input: Optional[dict[str, Any]] = None


class AfterToolResultPatchDAO(BaseModel):
    """Typed patch returned by one post-tool plugin interceptor."""

    model_config = ConfigDict(extra="forbid")

    content: Optional[str] = None
    is_error: Optional[bool] = None


class BeforeAgentTurnDecisionDAO(BaseModel):
    """Typed context contribution returned before a model turn."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    inject_messages: list[BaseMessage] = Field(default_factory=list)


ToolOutputUpdateHandler = PluginEventHandler
"""Readability alias for observers of display-only tool output updates."""


class PluginRegistrationDAO(BaseModel):
    """All declarations recorded from one plugin's registration factory."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    plugin_id: str
    source_path: str
    event_handlers: dict[str, list[PluginEventHandler]] = Field(default_factory=dict)
    tools: list[BaseTool] = Field(default_factory=list)
    commands: dict[str, Callable[..., Any]] = Field(default_factory=dict)
    renderers: dict[str, PluginRendererFn] = Field(default_factory=dict)
    statuses: dict[str, str] = Field(default_factory=dict)
    before_tool_call_handlers: list[Callable[..., Any]] = Field(default_factory=list)
    after_tool_result_handlers: list[Callable[..., Any]] = Field(default_factory=list)
    before_agent_turn_handlers: list[Callable[..., Any]] = Field(default_factory=list)
    health: PluginHealthDAO
