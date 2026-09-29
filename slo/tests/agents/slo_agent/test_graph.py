"""Tests for the Slo LangGraph (sub-spec 01.f §5.1).

The graph is now a one-shot turn: ``START → agent → tools → END``. One
``ainvoke`` runs exactly one assistant message + one tool batch.
Multi-turn behaviour (iteration cap, recovery across turns) lives in
``test_agent.py`` because the loop now lives in ``SloAgent``.
"""

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.graph import (
    _TRUNCATION_HINT,
    SloAgentStateDAO,
    _is_pool_bound,
    _make_agent_node,
    _make_tool_node,
    _split_system_messages,
    _uses_chatgpt_backend_responses,
    adapt_chatgpt_backend_request,
    build_slo_agent,
)
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.base import LLMBuildResult, LLMFactory
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.tool_execution import ToolExecutionMode
from src.agents.providers import FauxChatModel
from src.agents.tools.bundles import create_extended_tools
from src.agents.tools.write import write_tool
from src.auth.credential_dao import ProviderName


@tool
def stub_echo(text: str) -> str:
    """Stub used by graph tests."""
    return text


def _state(messages: list) -> SloAgentStateDAO:
    return SloAgentStateDAO(messages=messages)


def test_slo_agent_uses_default_bundle_when_tools_is_none() -> None:
    """Legacy ``tools=None`` still binds the standard extended bundle."""
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
    assert agent.tools == []

    default_agent = SloAgent(llm=FauxChatModel(responses=[]), tools=None)

    assert [tool.name for tool in default_agent.tools] == [tool.name for tool in create_extended_tools()]


def test_slo_agent_uses_only_supplied_tools_when_tools_is_nonempty() -> None:
    """Legacy callers may replace, rather than extend, the default tool bundle."""
    agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[stub_echo])

    assert [tool.name for tool in agent.tools] == ["stub_echo"]


def test_build_slo_agent_threads_reasoning_level_into_llm_factory() -> None:
    """The graph builder forwards the active reasoning level into ``LLMFactory.create``."""
    faux = FauxChatModel(responses=[])
    faux_build_result = LLMBuildResult(llm=faux, supports_explicit_caching=False)

    with patch(
        "src.agents.slo_agent.graph.service.LLMFactory.create",
        return_value=faux_build_result,
    ) as mock_create:
        build_slo_agent(
            model_name="gpt-5.4",
            reasoning_level="xhigh",
            tools=[stub_echo],
        )

    mock_create.assert_called_once_with(
        model_name="gpt-5.4",
        temperature=None,
        streaming=None,
        max_retries=3,
        max_tokens=None,
        reasoning_level="xhigh",
        session_id=None,
    )


@pytest.mark.asyncio
async def test_graph_runs_one_assistant_message_when_no_tool_calls() -> None:
    """No tool_calls on the assistant message → tools node is a no-op."""
    faux = FauxChatModel(responses=[FauxChatModel.assistant_message(content="done")])
    graph = build_slo_agent(llm=faux, tools=[stub_echo]).graph

    initial: SloAgentStateDAO = _state(
        messages=[SystemMessage(content="system"), HumanMessage(content="say hi")],
    )
    final = await graph.ainvoke(input=initial)

    assert final["messages"][-1].content == "done"
    assert not any(isinstance(m, ToolMessage) for m in final["messages"])


@pytest.mark.asyncio
async def test_graph_runs_one_tool_batch_per_invocation() -> None:
    """A single ainvoke executes one assistant message + one tool batch and ends."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_echo", args={"text": "hi"})],
            ),
        ]
    )
    graph = build_slo_agent(llm=faux, tools=[stub_echo]).graph

    final = await graph.ainvoke(
        input=_state(
            messages=[HumanMessage(content="echo")],
        )
    )

    tool_msgs = [m for m in final["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "hi"


@pytest.mark.asyncio
async def test_graph_runs_tools_in_source_order() -> None:
    """Two tool calls in one AIMessage must execute sequentially in order."""
    calls_seen: list[str] = []

    @tool
    def record_a(text: str) -> str:
        """record a."""
        calls_seen.append(f"a:{text}")
        return "a-done"

    @tool
    def record_b(text: str) -> str:
        """record b."""
        calls_seen.append(f"b:{text}")
        return "b-done"

    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[
                    FauxChatModel.tool_call_dict(name="record_a", args={"text": "1"}),
                    FauxChatModel.tool_call_dict(name="record_b", args={"text": "2"}),
                ]
            ),
        ]
    )
    graph = build_slo_agent(llm=faux, tools=[record_a, record_b]).graph
    await graph.ainvoke(input=_state(messages=[HumanMessage(content="go")]))
    assert calls_seen == ["a:1", "b:2"]


@pytest.mark.asyncio
async def test_graph_unknown_tool_surfaces_error_message() -> None:
    """Unknown tool names become error ToolMessages within the same turn."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="missing_tool", args={})],
            ),
        ]
    )
    graph = build_slo_agent(llm=faux, tools=[stub_echo]).graph
    final = await graph.ainvoke(input=_state(messages=[HumanMessage(content="x")]))

    tool_msgs = [m for m in final["messages"] if isinstance(m, ToolMessage)]
    assert any("not found" in (m.content or "") for m in tool_msgs)


@pytest.mark.asyncio
async def test_graph_tool_exception_surfaces_as_error_message() -> None:
    """A raising tool becomes an error ToolMessage; the turn still completes."""

    @tool
    def broken_tool(text: str) -> str:
        """Always raises."""
        raise RuntimeError("boom")

    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="broken_tool", args={"text": "x"})],
            ),
        ]
    )
    graph = build_slo_agent(llm=faux, tools=[broken_tool]).graph
    final = await graph.ainvoke(input=_state(messages=[HumanMessage(content="break it")]))

    tool_msgs = [m for m in final["messages"] if isinstance(m, ToolMessage)]
    assert any("boom" in (m.content or "") for m in tool_msgs)


def test_split_system_messages_hoists_all_system_prompts() -> None:
    """All ``SystemMessage`` items become one ``instructions`` string.

    The ChatGPT backend requires a top-level ``instructions`` field
    instead of ``role=system`` input items. Multiple system prompts are
    joined with double newlines in source order.
    """
    messages = [
        SystemMessage(content="sys a"),
        HumanMessage(content="user"),
        SystemMessage(content="sys b"),
        AIMessage(content="assistant"),
    ]

    instructions, non_system = _split_system_messages(messages=messages)

    assert instructions == "sys a\n\nsys b"
    assert [type(m).__name__ for m in non_system] == ["HumanMessage", "AIMessage"]


@pytest.mark.asyncio
async def test_agent_node_passes_instructions_for_chatgpt_backend() -> None:
    """ChatGPT-backend lane strips ``SystemMessage`` and passes ``instructions=...``.

    Regression guard for the real 400 from `~/.slo/logs/tui.log`:
    ``{'detail': 'Instructions are required'}``.
    """

    class _BackendStub:
        """Tiny stand-in for ``ChatOpenAI.bind_tools()``'s RunnableBinding shape."""

        def __init__(self) -> None:
            self.bound = ChatOpenAI(
                model="gpt-5",
                api_key="sk-test",
                openai_api_base="https://chatgpt.com/backend-api/codex",
                use_responses_api=True,
            )
            self.captured_messages = None
            self.captured_kwargs = None

        async def ainvoke(self, messages: list[BaseMessage], **kwargs: object) -> AIMessage:
            self.captured_messages = messages
            self.captured_kwargs = kwargs
            return AIMessage(content="ok")

    stub = _BackendStub()
    node = _make_agent_node(llm_with_tools=stub)  # type: ignore[arg-type]

    result = await node(
        _state(
            messages=[
                SystemMessage(content="sys prompt"),
                HumanMessage(content="hello"),
            ]
        )
    )

    assert _uses_chatgpt_backend_responses(llm=stub) is True
    assert stub.captured_kwargs == {"instructions": "sys prompt"}
    assert [type(m).__name__ for m in stub.captured_messages] == ["HumanMessage"]
    assert result["messages"][0].content == "ok"


def test_backend_detector_unwraps_runnable_binding_shape() -> None:
    """``_uses_chatgpt_backend_responses`` unwraps ``.bound`` recursively."""

    class _Wrapper:
        def __init__(self, bound: object) -> None:
            self.bound = bound

    backend = ChatOpenAI(
        model="gpt-5",
        api_key="sk-test",
        openai_api_base="https://chatgpt.com/backend-api/codex",
        use_responses_api=True,
    )
    platform = ChatOpenAI(model="gpt-5", api_key="sk-test")

    assert _uses_chatgpt_backend_responses(llm=_Wrapper(bound=backend)) is True
    assert _uses_chatgpt_backend_responses(llm=_Wrapper(bound=platform)) is False


def test_unwrap_helpers_terminate_when_bound_access_returns_a_fresh_wrapper() -> None:
    """A fresh wrapper chain stops at the bounded unwrapping depth."""

    class _FreshBound:
        @property
        def bound(self) -> "_FreshBound":
            """Return a distinct wrapper without model-only attributes."""
            return _FreshBound()

    endless = _FreshBound()

    assert _is_pool_bound(llm=endless) is False
    assert _uses_chatgpt_backend_responses(llm=endless) is False


def test_unwrap_helpers_ignore_absent_attributes() -> None:
    """A chat model without wrapper attributes reports no pool and no backend."""
    model = MagicMock(spec=BaseChatModel)

    assert _is_pool_bound(llm=model) is False
    assert _uses_chatgpt_backend_responses(llm=model) is False


def _truncated() -> dict:
    """Anthropic output-limit response metadata."""
    return {"stop_reason": "max_tokens"}


def _complete() -> dict:
    """A normal terminal response metadata (not truncation)."""
    return {"stop_reason": "tool_use"}


def _write_call(*, path: str, content: str | None = None, call_id: str = "call_1") -> dict:
    """Build a write tool-call dict; omit ``content`` to simulate a truncated call."""
    args: dict = {"path": path}
    if content is not None:
        args["content"] = content
    return {"name": "write", "args": args, "id": call_id, "type": "tool_call"}


def _ai(*, tool_calls: list[dict], metadata: dict) -> AIMessage:
    """Build an assistant message carrying tool calls and response metadata."""
    message = AIMessage(content="", tool_calls=tool_calls)
    message.response_metadata = metadata
    return message


def _tool_node():
    """Build the write-only tool node in sequential mode."""
    return _make_tool_node(tools=[write_tool], execution_mode=ToolExecutionMode.SEQUENTIAL)


@pytest.mark.asyncio
async def test_tool_node_appends_hint_to_errored_result_when_truncated(tmp_path) -> None:
    """A corrupt (content-less) write on a truncated turn gets the truncation hint."""
    call = _write_call(path=str(tmp_path / "f.md"))  # content dropped → schema error
    node = _tool_node()

    result = await node(_state([_ai(tool_calls=[call], metadata=_truncated())]))

    message = result["messages"][0]
    assert message.status == "error"
    assert message.tool_call_id == "call_1"
    assert message.name == "write"
    assert "Error" in message.content  # original error preserved
    assert message.content.endswith(_TRUNCATION_HINT)


@pytest.mark.asyncio
async def test_tool_node_leaves_successful_result_untouched_when_truncated(tmp_path) -> None:
    """A valid write on a truncated turn dispatches and is NOT augmented (no false positive)."""
    target = tmp_path / "f.md"
    call = _write_call(path=str(target), content="hello world")
    node = _tool_node()

    result = await node(_state([_ai(tool_calls=[call], metadata=_truncated())]))

    message = result["messages"][0]
    assert message.status != "error"
    assert _TRUNCATION_HINT not in message.content
    assert target.read_text() == "hello world"  # dispatch actually happened


@pytest.mark.asyncio
async def test_tool_node_does_not_augment_when_not_truncated(tmp_path) -> None:
    """A corrupt write on a NON-truncated turn keeps the raw error (existing behavior)."""
    call = _write_call(path=str(tmp_path / "f.md"))
    node = _tool_node()

    result = await node(_state([_ai(tool_calls=[call], metadata=_complete())]))

    message = result["messages"][0]
    assert message.status == "error"
    assert _TRUNCATION_HINT not in message.content


@pytest.mark.asyncio
async def test_tool_node_returns_empty_for_truncated_text_only_response() -> None:
    """A truncated text-only response (no tool calls) is a no-op."""
    message = AIMessage(content="partial answer")
    message.response_metadata = _truncated()
    node = _tool_node()

    result = await node(_state([message]))

    assert result["messages"] == []


@pytest.mark.asyncio
async def test_tool_node_augments_only_errored_of_mixed_results(tmp_path) -> None:
    """Truncated turn with one valid + one corrupt call: only the error gets the hint; order kept."""
    good = _write_call(path=str(tmp_path / "good.md"), content="ok", call_id="call_good")
    bad = _write_call(path=str(tmp_path / "bad.md"), call_id="call_bad")  # no content
    node = _tool_node()

    result = await node(_state([_ai(tool_calls=[good, bad], metadata=_truncated())]))

    by_id = {m.tool_call_id: m for m in result["messages"]}
    assert [m.tool_call_id for m in result["messages"]] == ["call_good", "call_bad"]
    assert _TRUNCATION_HINT not in by_id["call_good"].content
    assert by_id["call_good"].status != "error"
    assert by_id["call_bad"].content.endswith(_TRUNCATION_HINT)
    assert by_id["call_bad"].status == "error"


@pytest.mark.asyncio
async def test_tool_node_always_dispatches() -> None:
    """Dispatch is never skipped — the executor runs even on a truncated turn."""
    fake_executor = AsyncMock()
    fake_executor.execute = AsyncMock(return_value=[])
    call = _write_call(path="/tmp/never-written.md", call_id="c1")
    node = _tool_node()

    with patch("src.agents.slo_agent.graph.service._select_tool_executor", return_value=fake_executor):
        await node(_state([_ai(tool_calls=[call], metadata=_truncated())]))

    fake_executor.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_tool_node_augmentation_preserves_executor_order_and_is_mode_agnostic() -> None:
    """Augmentation maps positionally over the executor's results — no reordering.

    Uses a mocked executor so the result order is fixed regardless of execution
    mode (the concurrent executor reorders internally; augmentation must not add
    its own reordering on top). Only the errored result gets the hint.
    """
    returned = [
        ToolMessage(tool_call_id="c1", name="write", content="ok", status="success"),
        ToolMessage(tool_call_id="c2", name="write", content="Error: bad", status="error"),
        ToolMessage(tool_call_id="c3", name="write", content="ok2", status="success"),
    ]
    fake_executor = AsyncMock()
    fake_executor.execute = AsyncMock(return_value=returned)
    calls = [_write_call(path="/x", call_id=cid) for cid in ("c1", "c2", "c3")]
    node = _tool_node()

    with patch("src.agents.slo_agent.graph.service._select_tool_executor", return_value=fake_executor):
        result = await node(_state([_ai(tool_calls=calls, metadata=_truncated())]))

    assert [m.tool_call_id for m in result["messages"]] == ["c1", "c2", "c3"]
    assert not result["messages"][0].content.endswith(_TRUNCATION_HINT)
    assert result["messages"][1].content.endswith(_TRUNCATION_HINT)
    assert not result["messages"][2].content.endswith(_TRUNCATION_HINT)


# ---------------------------------------------------------------------------
# Pool-aware builder + request adapter (37.a.3)
# ---------------------------------------------------------------------------


def _chatgpt_backed_openai() -> ChatOpenAI:
    """Build a ChatOpenAI rooted at the ChatGPT backend base URL.

    Returns:
        ChatOpenAI: A model the backend detector classifies as ChatGPT-backend.
    """
    return ChatOpenAI(
        model="gpt-5.4",
        api_key="sk-test",  # type: ignore[arg-type]
        openai_api_base="https://chatgpt.com/backend-api/codex",  # type: ignore[call-arg]
        use_responses_api=True,
    )


def _platform_openai() -> ChatOpenAI:
    """Build a stock (Platform API) ChatOpenAI.

    Returns:
        ChatOpenAI: A model the backend detector classifies as non-ChatGPT.
    """
    return ChatOpenAI(model="gpt-5.4", api_key="sk-test")  # type: ignore[arg-type]


def _two_member_dao() -> ModelPoolDAO:
    """Build a two-member pool DAO (gpt-5.4 OpenAI, claude-sonnet-4-6 Anthropic).

    Returns:
        ModelPoolDAO: A validated two-entry pool config.
    """
    return ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1),
        ]
    )


def _pool_with_primary(primary: BaseChatModel) -> ModelPool:
    """Build a two-member pool whose priority-0 member is ``primary``.

    Args:
        primary (BaseChatModel): The priority-0 member instance.

    Returns:
        ModelPool: Pool with ``primary`` active and a faux secondary.
    """
    return ModelPool(
        pool_dao=_two_member_dao(),
        models={"gpt-5.4": primary, "claude-sonnet-4-6": FauxChatModel(responses=[])},
    )


class TestBuildSloAgentPoolBranch:
    def test_pool_dao_builds_pool_bound_graph(self) -> None:
        """A model_pool_dao produces a graph whose bound LLM is a ModelPool."""
        faux_build = LLMBuildResult(llm=FauxChatModel(responses=[]), supports_explicit_caching=False)
        with patch.object(LLMFactory, "create", return_value=faux_build):
            result = build_slo_agent(model_pool_dao=_two_member_dao(), tools=[stub_echo])
        assert hasattr(result.llm, "active_llm") or hasattr(getattr(result.llm, "bound", None), "active_llm")

    def test_result_carries_bound_llm(self) -> None:
        """The single-model build result carries the bound LLM."""
        faux_build = LLMBuildResult(llm=FauxChatModel(responses=[]), supports_explicit_caching=False)
        with patch.object(LLMFactory, "create", return_value=faux_build):
            result = build_slo_agent(model_name="gpt-5.4", tools=[stub_echo])
        assert result.llm is not None


class TestUsesChatGptBackendPoolAware:
    def test_unwraps_pool_active_llm(self) -> None:
        """A pool whose active member is a ChatGPT-backend model is detected."""
        pool = _pool_with_primary(_chatgpt_backed_openai())
        assert _uses_chatgpt_backend_responses(llm=pool) is True

    def test_returns_false_for_pool_with_non_chatgpt_active(self) -> None:
        """A pool whose active member is a Platform-API model is not detected."""
        pool = _pool_with_primary(_platform_openai())
        assert _uses_chatgpt_backend_responses(llm=pool) is False

    def test_is_pool_bound_true_for_pool(self) -> None:
        """_is_pool_bound recognises a raw ModelPool."""
        pool = _pool_with_primary(_platform_openai())
        assert _is_pool_bound(llm=pool) is True

    def test_is_pool_bound_false_for_single_model(self) -> None:
        """_is_pool_bound is False for a plain chat model."""
        assert _is_pool_bound(llm=FauxChatModel(responses=[])) is False


class TestAdaptChatGptBackendRequest:
    def test_hoists_instructions_for_chatgpt_member(self) -> None:
        """System text is hoisted into instructions; output-token kwargs are stripped."""
        msgs, kwargs = adapt_chatgpt_backend_request(
            llm=_chatgpt_backed_openai(),
            messages=[SystemMessage(content="S"), HumanMessage(content="H")],
            kwargs={
                "max_tokens": 4096,
                "max_output_tokens": 4096,
                "max_completion_tokens": 4096,
                "temperature": 0.1,
            },
        )
        assert kwargs["instructions"] == "S"
        assert "max_tokens" not in kwargs
        assert "max_output_tokens" not in kwargs
        assert "max_completion_tokens" not in kwargs
        assert kwargs["temperature"] == 0.1
        assert all(not isinstance(m, SystemMessage) for m in msgs)

    def test_passthrough_for_non_chatgpt_member(self) -> None:
        """A non-ChatGPT member's request is returned unchanged, cap included."""
        original = [SystemMessage(content="S"), HumanMessage(content="H")]
        original_kwargs = {"max_tokens": 4096}
        msgs, kwargs = adapt_chatgpt_backend_request(
            llm=FauxChatModel(responses=[]),
            messages=original,
            kwargs=original_kwargs,
        )
        assert msgs == original
        assert kwargs == original_kwargs
        assert "instructions" not in kwargs


class TestPostConstructionToolBinding:
    """Feature 83.b.1: generic tool binding happens after factory construction."""

    def test_factory_constructed_model_receives_bind_tools_after_construction(self) -> None:
        """``build_slo_agent`` binds tools to the factory product, with no model branch."""
        bound_models: list[str] = []

        class _BindingProbe:
            """Records the post-construction ``bind_tools`` call."""

            def bind_tools(self, *, tools: list) -> "_BindingProbe":
                bound_models.append("bound")
                return self

            def __getattr__(self, name: str) -> None:
                raise AttributeError(name)

        result = build_slo_agent(
            llm=_BindingProbe(),  # type: ignore[arg-type]
            tools=[write_tool],
        )

        assert bound_models == ["bound"]
        assert result.llm is not None
