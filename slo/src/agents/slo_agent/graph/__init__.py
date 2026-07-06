"""graph submodule — LangGraph state, nodes, and builder for the Slo agent.

DAO types live in ``graph.dao``.
Service functions (public API and private helpers) live in ``graph.service``.
All symbols are importable directly from ``src.agents.slo_agent.graph``.

Graph topology
--------------

::

    START ──► [ agent ] ──► [ tools ] ──► END

Each ``graph.ainvoke()`` / ``graph.astream()`` performs **exactly one
agent turn**: the LLM produces an assistant message (possibly with
tool calls), then the tools node executes those calls sequentially. If
the assistant message has no tool calls, the tools node is a no-op.
The decision to loop for another turn is made by the caller (SloAgent)
based on whether the last assistant message had tool calls.
"""

from src.agents.slo_agent.graph.dao import (  # noqa: F401
    SloAgentBuildResult,
    SloAgentStateDAO,
)
from src.agents.slo_agent.graph.service import (  # noqa: F401
    LLMFactory,
    NodeFn,
    _CHATGPT_BACKEND_BASE_URL_PREFIX,
    _TRUNCATION_HINT,
    _append_truncation_hint,
    _is_pool_bound,
    _make_agent_node,
    _make_tool_node,
    _select_tool_executor,
    _split_system_messages,
    _uses_chatgpt_backend_responses,
    adapt_chatgpt_backend_request,
    build_slo_agent,
)

__all__ = [
    "SloAgentBuildResult",
    "SloAgentStateDAO",
    "LLMFactory",
    "NodeFn",
    "_CHATGPT_BACKEND_BASE_URL_PREFIX",
    "_TRUNCATION_HINT",
    "_append_truncation_hint",
    "_is_pool_bound",
    "_make_agent_node",
    "_make_tool_node",
    "_select_tool_executor",
    "_split_system_messages",
    "_uses_chatgpt_backend_responses",
    "adapt_chatgpt_backend_request",
    "build_slo_agent",
]
