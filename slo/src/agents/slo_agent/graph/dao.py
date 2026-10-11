"""DAO types for the Slo agent LangGraph state.

``SloAgentStateDAO`` is the typed state that flows through the one-shot turn graph.
``SloAgentBuildResult`` is the NamedTuple returned by ``build_slo_agent()``.
"""

from __future__ import annotations

import asyncio
from typing import (
    Annotated,
    NamedTuple,
    Optional,
    Sequence,
)

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO
from src.agents.tools.tool_output import ToolOutputUpdateDAO

__all__ = [
    "SloAgentBuildResult",
    "SloAgentStateDAO",
]


class SloAgentBuildResult(NamedTuple):
    """Return value of ``build_slo_agent`` carrying graph, tools, llm, and flags.

    Wrapping these in a ``NamedTuple`` lets callers consume the resolved tool
    list, the bound LLM, and provider-capability metadata after construction.

    Fields:
        graph (CompiledStateGraph): Compiled LangGraph ready for
            ``.astream()`` / ``.ainvoke()``.
        tools (Sequence[BaseTool]): The resolved tool list that was bound
            to the LLM and registered in the tool node.
        llm (BaseChatModel): The tool-bound LLM (single model or ModelPool).
            Held by ``SloAgent`` so routed-model introspection works on the
            lazy build path.
        supports_explicit_caching (bool): Build-time provider caching capability
            (``True`` for Anthropic). The pool path resolves this dynamically
            per route at request time.
        snapshot (Optional[ModelCatalogSnapshotDAO]): Caller-supplied construction
            view, retained without capture, preparation, or admission semantics.
    """

    graph: CompiledStateGraph
    tools: Sequence[BaseTool]
    llm: BaseChatModel
    output_update_queue: asyncio.Queue[ToolOutputUpdateDAO] | None = None
    supports_explicit_caching: bool = False
    snapshot: Optional[ModelCatalogSnapshotDAO] = None


class SloAgentStateDAO(BaseModel):
    """Typed state flowing through the Slo one-shot turn.

    Pydantic ``BaseModel`` consumed by ``StateGraph`` as the graph's
    state schema. The ``messages`` field is annotated with
    ``add_messages`` so LangGraph's reducer appends new messages
    returned by each node rather than overwriting the list. No loop
    counter, no max-iterations cap, no pending-steering slot — those
    concerns live in ``SloAgent`` now that the loop has moved out of
    the graph.

    Fields:
        messages: The accumulated LangChain message list. Reduced by
            ``add_messages`` so node returns of
            ``{"messages": [...]}`` append rather than replace.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
