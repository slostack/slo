"""Service layer for the Slo agent LangGraph builder.

Public API: ``build_slo_agent()`` and ``adapt_chatgpt_backend_request()``.
Private helpers: all graph-building and node-factory functions.
"""

from __future__ import annotations

import asyncio
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Optional,
    Sequence,
    cast,
)

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph

from config.cfg import cfg
from src.agents.base import LLM, LLMBuildProduct, LLMBuildResult, LLMFactory
from src.agents.model_catalog.dao import ModelCatalogSnapshotDAO

if TYPE_CHECKING:
    from src.agents.providers.model_pool import ModelPoolDAO
    from src.agents.slo_agent.plugins.dispatcher import PluginDispatcher
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.truncation import was_output_truncated
from src.agents.tools.tool_output import ToolOutputUpdateDAO
from src.agents.slo_agent.tool_execution import (
    ConcurrentToolExecutor,
    SequentialToolExecutor,
    ToolExecutionMode,
    plan_tool_batch,
)
from src.agents.reasoning_capabilities import ReasoningLevel
from src.agents.tools.bundles import create_extended_tools
from src.agents.slo_agent.graph.dao import SloAgentBuildResult, SloAgentStateDAO

__all__ = [
    "LLMFactory",
    "NodeFn",
    "_CHATGPT_BACKEND_BASE_URL_PREFIX",
    "_TRUNCATION_HINT",
    "_append_truncation_hint",
    "_is_pool_bound",
    "_make_agent_node",
    "_make_tool_node",
    "_select_tool_executor",
    "drain_tool_output_updates",
    "_split_system_messages",
    "_uses_chatgpt_backend_responses",
    "adapt_chatgpt_backend_request",
    "build_slo_agent",
]


NodeFn = Callable[["SloAgentStateDAO"], Awaitable[dict]]


_CHATGPT_BACKEND_BASE_URL_PREFIX: str = "https://chatgpt.com/backend-api/codex"
"""Requests on this base URL require top-level ``instructions``.

The public Responses API accepts a system message as a ``role=system``
input item, but the ChatGPT backend used by OpenAI OAuth (`feature 07`)
returns ``400 {'detail': 'Instructions are required'}`` unless the
system prompt is hoisted to the top-level ``instructions`` field.
"""


_CHATGPT_BACKEND_OUTPUT_TOKEN_KWARGS: frozenset[str] = frozenset(
    {"max_tokens", "max_output_tokens", "max_completion_tokens"}
)
"""Output-token kwargs the ChatGPT backend rejects.

LangChain renames ``max_tokens``/``max_completion_tokens`` to
``max_output_tokens`` on the Responses lane, so all three must be dropped for
this backend. Read by ``adapt_chatgpt_backend_request`` only.
"""


_TRUNCATION_HINT: str = (
    "\n\nNote: the response was truncated at the model's output token limit, so the "
    "tool arguments may have been cut off. Write a smaller file, or create the file "
    "in parts using the edit tool to append the remaining content."
)


def adapt_chatgpt_backend_request(
    llm: BaseChatModel,
    messages: list[BaseMessage],
    kwargs: dict[str, Any],
) -> tuple[list[BaseMessage], dict[str, Any]]:
    """Shape a request for whichever model is about to be invoked.

    For a ChatGPT-backend (OpenAI OAuth) model, hoist all ``SystemMessage`` text
    into a top-level ``instructions`` kwarg, strip system messages from the input
    list, and drop every output-token kwarg (the backend rejects them; LangChain
    would otherwise rename ``max_tokens`` to ``max_output_tokens``). For every
    other model, return the request unchanged. Used both inline by
    ``_make_agent_node`` for the single-model path, by
    ``Compacter._invoke_llm_summary`` for a direct model, and as ``ModelPool``'s
    per-member ``request_adapter`` so a mid-call lane switch re-derives the
    correct shape.

    Args:
        llm (BaseChatModel): The model about to be invoked (a concrete member or
            tool-bound member — ``_uses_chatgpt_backend_responses`` unwraps it).
        messages (list[BaseMessage]): The request messages.
        kwargs (dict[str, Any]): Invocation kwargs to augment.

    Returns:
        tuple[list[BaseMessage], dict[str, Any]]: ``(messages, kwargs)``, with
            system messages hoisted into ``kwargs["instructions"]`` for the
            ChatGPT-backend lane only.
    """
    if not _uses_chatgpt_backend_responses(llm=llm):
        return messages, kwargs
    instructions, non_system_messages = _split_system_messages(messages=messages)
    augmented: dict[str, Any] = {
        key: value for key, value in kwargs.items() if key not in _CHATGPT_BACKEND_OUTPUT_TOKEN_KWARGS
    }
    augmented["instructions"] = instructions
    return non_system_messages, augmented


_MAX_UNWRAP_DEPTH: int = 16
"""Maximum wrapper hops followed when unwrapping a chat model.

``_is_pool_bound`` and ``_uses_chatgpt_backend_responses`` walk ``.bound`` and
``.active_llm`` to reach the concrete model behind a ``RunnableBinding`` or a
``ModelPool``. A real chain is at most two hops. A test double that fabricates
a child for every attribute access would otherwise walk without end, so both
helpers stop at this cap. Called by both unwrap helpers only.
"""


def _is_pool_bound(*, llm: Any) -> bool:
    """Return True when ``llm`` (possibly tool-bound) wraps a ModelPool.

    Unwraps ``RunnableBinding.bound`` iteratively, then checks for the
    ``active_llm`` attribute that only ``ModelPool`` exposes. The walk stops
    after ``_MAX_UNWRAP_DEPTH`` hops so a self-referential test double cannot
    recurse without end.

    Args:
        llm (Any): The bound chat model from the graph builder.

    Returns:
        bool: True iff unwrapping ``.bound`` reaches an object exposing
            ``active_llm`` (the ModelPool router).
    """
    current: Any = llm
    for _ in range(_MAX_UNWRAP_DEPTH):
        bound: Any = getattr(current, "bound", None)
        if bound is None or bound is current:
            break
        current = bound
    return getattr(current, "active_llm", None) is not None


def _make_agent_node(llm_with_tools: BaseChatModel) -> NodeFn:
    """Build the agent node, closed over the tool-bound LLM.

    Single-model path: applies ``adapt_chatgpt_backend_request`` inline so the
    ChatGPT-backend lane gets top-level instructions. Pool path: passes raw
    messages and lets ``ModelPool``'s per-member request adapter shape the
    request for whichever member it routes to (correct across mid-call lane
    switches).

    Args:
        llm_with_tools (BaseChatModel): The tool-bound LLM (single model or pool).

    Returns:
        NodeFn: Async LangGraph node producing the assistant message.
    """
    pool_bound: bool = _is_pool_bound(llm=llm_with_tools)

    async def agent_node(state: SloAgentStateDAO) -> dict:
        request_messages: list[BaseMessage] = list(state.messages)
        if pool_bound:
            response: BaseMessage = await llm_with_tools.ainvoke(request_messages)
            return {"messages": [response]}
        shaped_messages, shaped_kwargs = adapt_chatgpt_backend_request(
            llm=llm_with_tools,
            messages=request_messages,
            kwargs={},
        )
        response = await llm_with_tools.ainvoke(shaped_messages, **shaped_kwargs)
        return {"messages": [response]}

    return agent_node


def _append_truncation_hint(*, message: ToolMessage) -> ToolMessage:
    """Return a copy of an error ``ToolMessage`` with the output-truncation hint appended.

    Invoked by ``tool_node`` for each errored tool result on a turn that hit the
    output-token ceiling, so the model learns its arguments were cut off rather than
    simply missing. The original error text is preserved ahead of the hint.

    Args:
        message (ToolMessage): An error tool result (``status == "error"``) produced
            while the turn was output-truncated.

    Returns:
        ToolMessage: The same result with ``_TRUNCATION_HINT`` appended to its
            content; ``tool_call_id``, ``name``, and ``status`` are preserved.
    """
    return ToolMessage(
        tool_call_id=message.tool_call_id,
        name=message.name,
        content=f"{message.content}{_TRUNCATION_HINT}",
        status="error",
    )


async def drain_tool_output_updates(
    *,
    output_update_queue: asyncio.Queue[ToolOutputUpdateDAO],
    iteration: int,
) -> AsyncIterator[AgentStreamEventDAO]:
    """Drain queued snapshots into the canonical stream event vocabulary.

    Args:
        output_update_queue (asyncio.Queue[ToolOutputUpdateDAO]): Per-agent bridge queue.
        iteration (int): Outer ReAct iteration stamped on events.

    Yields:
        AgentStreamEventDAO: Display-only snapshots routed by tool call id.
    """
    while not output_update_queue.empty():
        snapshot: ToolOutputUpdateDAO = output_update_queue.get_nowait()
        yield AgentStreamEventDAO(
            kind="tool_output_update",
            iteration=iteration,
            tool_call_id=snapshot.tool_call_id,
            tool_name=snapshot.tool_name,
            content=snapshot.content_snapshot,
            metadata={
                "truncated": snapshot.truncated,
                "full_output_path": snapshot.full_output_path,
            },
        )


def _make_tool_node(
    *,
    tools: Sequence[BaseTool],
    execution_mode: ToolExecutionMode,
    output_update_queue: asyncio.Queue[ToolOutputUpdateDAO] | None = None,
    plugin_dispatcher: "PluginDispatcher | None" = None,
) -> NodeFn:
    """Build the Slo tool node with managed execution policy.

    Args:
        tools (Sequence[BaseTool]): Registered tools for this agent.
        execution_mode (ToolExecutionMode): Batch execution policy.
        output_update_queue (asyncio.Queue[ToolOutputUpdateDAO]): Per-agent
            queue that the outer agent stream drains onto the event bus.

    Returns:
        NodeFn: Async LangGraph node executing the last assistant
            message's tool calls.
    """
    tools_by_name: dict[str, BaseTool] = {tool.name: tool for tool in tools}
    queue: asyncio.Queue[ToolOutputUpdateDAO] = output_update_queue or asyncio.Queue()

    async def tool_node(state: SloAgentStateDAO) -> dict:
        last: BaseMessage = state.messages[-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return {"messages": []}

        plan = plan_tool_batch(calls=list(last.tool_calls))  # type: ignore[arg-type]  # ToolCall is a TypedDict

        async def sink(*, snapshot: ToolOutputUpdateDAO) -> None:
            """Place a typed partial snapshot on the graph-to-agent bridge.

            Args:
                snapshot (ToolOutputUpdateDAO): Executor-stamped latest snapshot.
            """
            await queue.put(snapshot)

        executor = _select_tool_executor(
            execution_mode=execution_mode,
            tools_by_name=tools_by_name,
            run_concurrently=plan.run_concurrently,
            output_update_sink=sink,
            plugin_dispatcher=plugin_dispatcher,
        )
        tool_messages: list[ToolMessage] = await executor.execute(plan=plan)

        # On a turn that hit the output-token ceiling, a tool call may have lost a
        # trailing argument to partial-JSON parsing, surfacing as an error result
        # (e.g. WriteSchemaDAO "content — Field required"). Append a truncation-aware
        # hint so the model splits the work instead of retrying the same oversized
        # call. Successful results, and every non-truncated turn, are left untouched.
        if was_output_truncated(message=last):
            tool_messages = [
                _append_truncation_hint(message=message) if message.status == "error" else message
                for message in tool_messages
            ]
        return {"messages": tool_messages}

    return tool_node


def _uses_chatgpt_backend_responses(*, llm: Any) -> bool:
    """Return True when ``llm`` targets the ChatGPT-backend Responses lane.

    Unwraps ``RunnableBinding.bound`` (tool binding) and ``ModelPool.active_llm``
    (pool routing) recursively so the check inspects the concrete underlying
    ``ChatOpenAI`` regardless of how it was wrapped.

    Args:
        llm (Any): A raw chat model, a bound runnable, or a ModelPool.

    Returns:
        bool: ``True`` iff the underlying model is a ``ChatOpenAI`` with
            ``openai_api_base`` rooted at the ChatGPT backend.
    """
    current: Any = llm
    for _ in range(_MAX_UNWRAP_DEPTH):
        bound: Any = getattr(current, "bound", None)
        if bound is not None and bound is not current:
            current = bound
            continue
        active_llm: Any = getattr(current, "active_llm", None)
        if active_llm is not None and active_llm is not current:
            current = active_llm
            continue
        break
    if not isinstance(current, ChatOpenAI):
        return False
    base_url: Optional[str] = getattr(current, "openai_api_base", None)
    if not base_url:
        return False
    return base_url.startswith(_CHATGPT_BACKEND_BASE_URL_PREFIX)


def _split_system_messages(*, messages: list[BaseMessage]) -> tuple[str, list[BaseMessage]]:
    """Split ``messages`` into top-level instructions and non-system items.

    The ChatGPT backend requires a top-level ``instructions`` field.
    Multiple ``SystemMessage`` items are joined with double newlines in
    source order; every non-system message is preserved unchanged and in
    order.

    Args:
        messages (list[BaseMessage]): Original message list.

    Returns:
        tuple[str, list[BaseMessage]]: ``(instructions, non_system_messages)``.
    """
    instruction_parts: list[str] = []
    non_system_messages: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, SystemMessage):
            content: str = message.content if isinstance(message.content, str) else str(message.content)
            instruction_parts.append(content)
            continue
        non_system_messages.append(message)
    return "\n\n".join(instruction_parts), non_system_messages


def _select_tool_executor(
    *,
    execution_mode: ToolExecutionMode,
    tools_by_name: dict[str, BaseTool],
    run_concurrently: bool,
    output_update_sink: Callable[..., Awaitable[None]] | None = None,
    plugin_dispatcher: "PluginDispatcher | None" = None,
) -> SequentialToolExecutor | ConcurrentToolExecutor:
    """Select the concrete executor for one planned tool batch.

    Args:
        execution_mode (ToolExecutionMode): Configured graph-wide policy.
        tools_by_name (dict[str, BaseTool]): Registered tools keyed by name.
        run_concurrently (bool): True iff the planner marked this batch
            safe for concurrent execution.

    Returns:
        SequentialToolExecutor | ConcurrentToolExecutor: The executor to
            use for this batch.
    """
    if execution_mode is ToolExecutionMode.SEQUENTIAL:
        return SequentialToolExecutor(
            tools_by_name=tools_by_name,
            output_update_sink=output_update_sink,
            plugin_dispatcher=plugin_dispatcher,
        )
    if execution_mode is ToolExecutionMode.CONCURRENT_READS and run_concurrently:
        return ConcurrentToolExecutor(
            tools_by_name=tools_by_name,
            output_update_sink=output_update_sink,
            plugin_dispatcher=plugin_dispatcher,
        )
    return SequentialToolExecutor(
        tools_by_name=tools_by_name,
        output_update_sink=output_update_sink,
        plugin_dispatcher=plugin_dispatcher,
    )


def build_slo_agent(
    *,
    model_name: Optional[str] = None,
    model_pool_dao: Optional["ModelPoolDAO"] = None,
    tools: Optional[Sequence[BaseTool]] = None,
    llm: Optional[LLM] = None,
    temperature: Optional[float] = None,
    streaming: Optional[bool] = None,
    max_tokens: Optional[int] = None,
    max_retries: int = 3,
    reasoning_level: ReasoningLevel = "off",
    session_id: Optional[str] = None,
    tool_execution_mode: ToolExecutionMode = ToolExecutionMode.CONCURRENT_READS,
    plugin_dispatcher: "PluginDispatcher | None" = None,
    snapshot: Optional[ModelCatalogSnapshotDAO] = None,
) -> SloAgentBuildResult:
    """Build a compiled Slo one-shot-turn graph (single model or pool).

    The returned graph performs **one assistant turn + one tool batch** per
    invocation. The multi-turn ReAct loop is driven by
    ``SloAgent.invoke``.

    When ``model_pool_dao`` is supplied (and ``llm`` is not injected), the LLM is
    a ``ModelPool`` built via ``LLMFactory.create_pool``; otherwise a single
    model via ``LLMFactory.create``. Both paths flow through the same ``.llm`` /
    ``.supports_explicit_caching`` build-product slots and the same tool binding.

    Args:
        model_name (Optional[str]): Single-model identifier passed to
            ``LLMFactory.create``. Falls back to ``cfg("DEFAULT_MODEL_NAME")``.
            Ignored when ``model_pool_dao`` or ``llm`` is supplied.
        model_pool_dao (Optional[ModelPoolDAO]): Pool config. When set (and
            ``llm`` is None), the build uses ``LLMFactory.create_pool``.
        tools (Optional[Sequence[BaseTool]]): Tools the agent may call.
            Defaults to ``create_extended_tools()`` (the full pi-parity
            bundle plus ``read_pdf`` and ``now``).
        llm (Optional[LLM]): Pre-built chat model — use this to inject a
            ``FauxChatModel`` or a ``ModelPool`` for tests. When provided,
            both ``model_name`` and ``model_pool_dao`` are ignored.
        temperature (Optional[float]): Forwarded to the factory when ``llm``
            is not supplied.
        streaming (Optional[bool]): Forwarded to the factory when ``llm``
            is not supplied.
        max_tokens (Optional[int]): Forwarded to the factory when ``llm``
            is not supplied.
        max_retries (int): Forwarded to the factory when ``llm`` is not supplied.
        reasoning_level (ReasoningLevel): Canonical active reasoning level
            forwarded into the factory.
        session_id (Optional[str]): Active session id for ChatGPT-backend headers.
        tool_execution_mode (ToolExecutionMode): Batch execution policy
            for the custom Slo tool node.
        snapshot (Optional[ModelCatalogSnapshotDAO]): Caller-supplied immutable
            construction view. None preserves existing global reads; no capture
            or runtime admission happens here.

    Returns:
        SloAgentBuildResult: Named tuple with the compiled ``graph``, resolved
            ``tools``, the tool-bound ``llm``, and the build-time caching flag.
    """
    if tools is None:
        tools = create_extended_tools()

    explicit_caching: bool = False
    if llm is None:
        build_product: LLMBuildProduct
        if model_pool_dao is not None:
            build_product = LLMFactory.create_pool(
                pool_dao=model_pool_dao,
                temperature=temperature,
                streaming=streaming,
                max_retries=max_retries,
                max_tokens=max_tokens,
                session_id=session_id,
                reasoning_level=reasoning_level,
                snapshot=snapshot,
            )
        else:
            resolved_model: str = model_name or (cfg(key="DEFAULT_MODEL_NAME") or "gpt-5.4")
            build_product = LLMFactory.create(
                model_name=resolved_model,
                temperature=temperature,
                streaming=streaming,
                max_retries=max_retries,
                max_tokens=max_tokens,
                reasoning_level=reasoning_level,
                session_id=session_id,
                snapshot=snapshot,
            )
        llm = build_product.llm
        explicit_caching = build_product.supports_explicit_caching

    llm_with_tools: BaseChatModel = cast(BaseChatModel, llm.bind_tools(tools=list(tools))) if tools else llm

    agent_node: NodeFn = _make_agent_node(llm_with_tools=llm_with_tools)
    output_update_queue: asyncio.Queue[ToolOutputUpdateDAO] = asyncio.Queue()
    tool_node: NodeFn = _make_tool_node(
        tools=tools,
        execution_mode=tool_execution_mode,
        output_update_queue=output_update_queue,
        plugin_dispatcher=plugin_dispatcher,
    )

    # Linear, one-shot turn:
    #
    #   START ──► agent ──► tools ──► END
    #
    # No conditional edges, no routing function. Looping is the caller's
    # responsibility — see ``SloAgent.invoke``.
    graph: StateGraph = StateGraph(SloAgentStateDAO)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", "tools")
    graph.add_edge("tools", END)

    return SloAgentBuildResult(
        graph=graph.compile(),
        tools=tools,
        llm=llm_with_tools,
        output_update_queue=output_update_queue,
        supports_explicit_caching=explicit_caching,
        snapshot=snapshot,
    )
