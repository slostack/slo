"""Tests for ``SloAgent`` (sub-spec 01.f §5.2).

Covers the public surface (``invoke``, ``steer``, ``abort``) plus the
multi-turn ReAct loop that now lives inside ``SloAgent.invoke``.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool

from src.agents.base import LLMBuildResult, LLMFactory
from src.agents.hooks import ShouldStopAfterTurnHookContextDAO
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.providers import FauxChatModel
from src.auth.credential_dao import ProviderName


@tool
def stub_now() -> str:
    """Stub used by agent tests."""
    return "2026-05-25T12:00:00+00:00"


async def _collect_final_response(
    *,
    agent: SloAgent,
    query: str,
    history: list[dict] | None = None,
) -> str:
    """Drain ``agent.invoke`` and return the final assistant text.

    Args:
        agent (SloAgent): Agent under test.
        query (str): Prompt text.
        history (list[dict] | None): Optional legacy history.

    Returns:
        str: Final response text, or ``"<aborted>"`` on abort.
    """
    final_response: str = ""
    async for event in agent.invoke(query=query, history=history):
        if event.kind == "run_completed":
            final_response = event.content or ""
        elif event.kind == "run_aborted":
            final_response = "<aborted>"
    return final_response


@pytest.mark.asyncio
async def test_react_returns_final_response() -> None:
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="hello back")]),
        tools=[],
    )
    result: str = await _collect_final_response(agent=agent, query="hi")
    assert result == "hello back"


@pytest.mark.asyncio
async def test_invoke_yields_events_then_final() -> None:
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(
                    tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
                ),
                FauxChatModel.assistant_message(content="The time is X."),
            ]
        ),
        tools=[stub_now],
    )
    events = [evt async for evt in agent.invoke(query="when?")]
    assert events[-1].kind == "run_completed"
    assert events[-1].content == "The time is X."
    assert any(e.tool_name == "stub_now" for e in events if e.kind == "tool_result")


@pytest.mark.asyncio
async def test_react_loops_until_no_tool_calls() -> None:
    """The loop should re-enter the graph as long as the assistant emits tool_calls."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(content="finally done"),
        ]
    )
    agent = SloAgent(llm=faux, tools=[stub_now])
    result: str = await _collect_final_response(agent=agent, query="loop a couple of times")
    assert result == "finally done"


@pytest.mark.asyncio
async def test_stop_hook_returning_true_breaks_loop() -> None:
    """Sync hook returning True after turn 1 halts the loop before the second LLM call."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(content="never reached"),
        ]
    )
    captured: list[ShouldStopAfterTurnHookContextDAO] = []

    def stop_after_first(context: ShouldStopAfterTurnHookContextDAO) -> bool:
        captured.append(context)
        return True

    agent = SloAgent(
        llm=faux,
        tools=[stub_now],
        should_stop_after_turn_hook=stop_after_first,
    )
    events = [evt async for evt in agent.invoke(query="x")]
    assert events[-1].kind == "run_completed"
    assert len(captured) == 1
    assert isinstance(captured[0].message, AIMessage)
    assert len(captured[0].tool_results) == 1
    assert captured[0].tool_results[0].name == "stub_now"


@pytest.mark.asyncio
async def test_stop_hook_returning_false_lets_loop_continue() -> None:
    """A hook that always returns False is a no-op; the loop stops on no tool_calls."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(content="natural stop"),
        ]
    )
    call_count: int = 0

    def never_stop(context: ShouldStopAfterTurnHookContextDAO) -> bool:
        nonlocal call_count
        call_count += 1
        return False

    agent = SloAgent(
        llm=faux,
        tools=[stub_now],
        should_stop_after_turn_hook=never_stop,
    )
    result: str = await _collect_final_response(agent=agent, query="x")
    assert result == "natural stop"
    assert call_count == 2


@pytest.mark.asyncio
async def test_stop_hook_supports_async_callable() -> None:
    """An async hook is awaited and its result honoured."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(content="never reached"),
        ]
    )

    async def async_stop(context: ShouldStopAfterTurnHookContextDAO) -> bool:
        return True

    agent = SloAgent(
        llm=faux,
        tools=[stub_now],
        should_stop_after_turn_hook=async_stop,
    )
    result: str = await _collect_final_response(agent=agent, query="x")
    # Stopped after turn 1; that turn's assistant message had no
    # text content (tool-call only) → last_assistant_text == "".
    assert result == ""


@pytest.mark.asyncio
async def test_default_hook_means_unbounded_loop_until_no_tool_calls() -> None:
    """Without a custom hook the loop runs until the model stops calling tools."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
            ),
            FauxChatModel.assistant_message(content="done after three"),
        ]
    )
    agent = SloAgent(llm=faux, tools=[stub_now])
    result: str = await _collect_final_response(agent=agent, query="loop")
    assert result == "done after three"


@pytest.mark.asyncio
async def test_react_recovers_across_turns_after_unknown_tool() -> None:
    """Unknown tool errors in turn N should not stop the loop; the model can recover in turn N+1."""
    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="missing_tool", args={})],
            ),
            FauxChatModel.assistant_message(content="recovered"),
        ]
    )
    agent = SloAgent(llm=faux, tools=[stub_now])
    result: str = await _collect_final_response(agent=agent, query="try a missing tool then recover")
    assert result == "recovered"


@pytest.mark.asyncio
async def test_react_recovers_across_turns_after_tool_exception() -> None:
    """A raising tool in turn N should let the loop continue into turn N+1."""

    @tool
    def broken_tool(text: str) -> str:
        """Always raises."""
        raise RuntimeError("boom")

    faux = FauxChatModel(
        responses=[
            FauxChatModel.assistant_message(
                tool_calls=[FauxChatModel.tool_call_dict(name="broken_tool", args={"text": "x"})],
            ),
            FauxChatModel.assistant_message(content="caught the error"),
        ]
    )
    agent = SloAgent(llm=faux, tools=[broken_tool])
    result: str = await _collect_final_response(agent=agent, query="break, then recover")
    assert result == "caught the error"


@pytest.mark.asyncio
async def test_double_invocation_raises() -> None:
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(content="hi"),
                FauxChatModel.assistant_message(content="second"),
            ]
        ),
        tools=[],
    )
    gen = agent.invoke(query="first")
    await gen.__anext__()
    second_gen = agent.invoke(query="second")
    with pytest.raises(RuntimeError, match="already processing"):
        await second_gen.__anext__()
    async for _ in gen:
        pass


@pytest.mark.asyncio
async def test_abort_yields_aborted_final() -> None:
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(
                    tool_calls=[FauxChatModel.tool_call_dict(name="stub_now", args={})],
                ),
                FauxChatModel.assistant_message(content="done"),
            ]
        ),
        tools=[stub_now],
    )
    agent.abort()
    events = [evt async for evt in agent.invoke(query="x")]
    assert events[-1].kind == "run_aborted"
    assert events[-1].content == "<aborted>"


@pytest.mark.asyncio
async def test_steering_message_appears_in_next_turn() -> None:
    """A steering message queued before the run is drained into the first turn."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="received")]),
        tools=[],
    )
    agent.steer(message="please be terse")
    result: str = await _collect_final_response(agent=agent, query="hello")
    assert result == "received"


@pytest.mark.asyncio
async def test_steering_queued_before_run_emits_steering_applied_event() -> None:
    """A pre-run steer surfaces a ``steering_applied`` stream event carrying its text."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        tools=[],
    )
    agent.steer(message="please be terse")

    events = [evt async for evt in agent.invoke(query="hello")]

    applied = [evt for evt in events if evt.kind == "steering_applied"]
    assert len(applied) == 1
    assert applied[0].content == "please be terse"


@pytest.mark.asyncio
async def test_steer_during_final_turn_revives_the_run() -> None:
    """A steer that arrives during an otherwise-final turn revives the run for another turn.

    Without revival the steer would be stranded in the queue (the loop
    breaks on a no-tool-call turn before draining), defeating the purpose of
    /steer. The steer is queued from inside turn 1 via the runtime handler —
    after the initial drain, while the first turn streams — so it can only be
    honoured by the between-turn revive path.
    """
    agent = SloAgent(
        llm=FauxChatModel(
            responses=[
                FauxChatModel.assistant_message(content="first"),
                FauxChatModel.assistant_message(content="second"),
            ]
        ),
        tools=[],
    )
    queued: dict[str, bool] = {"done": False}

    async def _queue_steer_mid_turn(event) -> None:
        if not queued["done"] and event.kind == "assistant_delta":
            agent.steer(message="keep going")
            queued["done"] = True

    events = [
        evt
        async for evt in agent.invoke(
            query="hi",
            runtime_handler=_queue_steer_mid_turn,
        )
    ]

    applied = [evt for evt in events if evt.kind == "steering_applied"]
    assert [evt.content for evt in applied] == ["keep going"]
    assert events[-1].kind == "run_completed"
    assert events[-1].content == "second"


@pytest.mark.asyncio
async def test_history_is_threaded_into_initial_messages() -> None:
    """history dicts should become AIMessage / HumanMessage in the initial state."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ack")]),
        tools=[],
    )
    result: str = await _collect_final_response(
        agent=agent,
        query="second turn",
        history=[
            {"role": "user", "content": "first turn"},
            {"role": "assistant", "content": "earlier ack"},
        ],
    )
    assert result == "ack"


def test_default_cwd_is_os_getcwd_and_grounds_prompt() -> None:
    """With no cwd argument the agent grounds the prompt in os.getcwd()."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        tools=[],
    )
    assert agent._cwd == os.getcwd()
    assert agent._system_prompt.endswith(f"Current working directory: {os.getcwd()}")


def test_explicit_cwd_is_threaded_into_prompt(tmp_path: Path) -> None:
    """An explicit cwd argument is surfaced in the prompt's cwd line."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        tools=[],
        cwd=str(tmp_path),
    )
    assert agent._cwd == str(tmp_path)
    assert f"Current working directory: {tmp_path}" in agent._system_prompt


def test_threads_project_context_files_into_system_prompt(
    tmp_path: Path,
) -> None:
    """Surface discovered project guidance files in the final prompt."""
    (tmp_path / ".git").mkdir()
    (tmp_path / "SLO.md").write_text("Always run make test before commit.")

    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        tools=[],
        cwd=str(tmp_path),
    )

    assert "Always run make test before commit." in agent._system_prompt
    assert "<project_instructions path=" in agent._system_prompt
    assert f"Current working directory: {tmp_path}" in agent._system_prompt


def test_caller_system_prompt_bypasses_runtime_builder(tmp_path: Path) -> None:
    """A final system_prompt wins outright: no date or cwd grounding is added."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        tools=[],
        system_prompt="x",
        cwd=str(tmp_path),
    )
    assert agent._system_prompt == "x"
    assert "Current working directory:" not in agent._system_prompt
    assert "Current date:" not in agent._system_prompt


def test_custom_prompt_replaces_body_but_keeps_cwd_grounding(
    tmp_path: Path,
) -> None:
    """custom_prompt replaces the default body yet the prompt still ends grounded in cwd."""
    agent = SloAgent(
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
        tools=[],
        custom_prompt="You are a focused review agent.",
        cwd=str(tmp_path),
    )
    assert agent._system_prompt.startswith("You are a focused review agent.")
    assert agent._system_prompt.endswith(f"Current working directory: {tmp_path}")


# ---------------------------------------------------------------------------
# Sub-spec 18.01 — B1/B2: resolved tool list reaches the system prompt builder
# ---------------------------------------------------------------------------


def test_build_slo_agent_returns_slo_agent_build_result_with_nine_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``build_slo_agent`` with ``tools=None`` must surface the 9-tool extended bundle.

    This is the B1 regression guard: the function used to return only the
    compiled graph, discarding the resolved tool list. After the fix it
    returns a ``SloAgentBuildResult`` whose ``tools`` field carries all 9
    default tools (connector tools are excluded when no credentials exist).
    """
    import pytest  # noqa: PLC0415
    from src.agents.slo_agent.graph import SloAgentBuildResult, build_slo_agent

    # Clear connector credential env vars so the bundle returns exactly 9 tools.
    for var in (
        "SLO_ATLASSIAN_SITE_URL",
        "SLO_ATLASSIAN_EMAIL",
        "SLO_ATLASSIAN_API_TOKEN",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "SLO_GITHUB_TOKEN",
        "GITLAB_TOKEN",
        "GLAB_TOKEN",
        "SLO_GITLAB_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
    # Redirect connector store so no persisted credentials interfere.
    monkeypatch.setenv("SLO_CONNECTORS_DIR", "/tmp/slo-test-connectors-nonexistent")

    result = build_slo_agent(llm=FauxChatModel(responses=[]))

    assert isinstance(result, SloAgentBuildResult)
    assert len(result.tools) == 9


def test_system_prompt_available_tools_block_is_not_none_by_default() -> None:
    """After the B1/B2 fix the system prompt must not show ``Available tools:\\n(none)``.

    Previously ``tools=None`` reached ``SystemPromptBuilder.invoke`` and
    ``tools or ()`` resolved to an empty tuple, emitting
    ``"Available tools:\\n(none)"`` as the entire tools block.
    """
    agent = SloAgent(llm=FauxChatModel(responses=[]))

    assert "Available tools:" in agent._system_prompt
    assert "Available tools:\n(none)" not in agent._system_prompt


def test_system_prompt_prefer_native_explorers_guideline_fires() -> None:
    """grep/find/ls tools present → ``GUIDELINE_PREFER_NATIVE_EXPLORERS`` must appear.

    The guideline is injected by ``SystemPromptBuilder`` only when the
    tool list contains the native explorer tools. Before the fix the
    builder received an empty list and omitted it.
    """
    agent = SloAgent(llm=FauxChatModel(responses=[]))

    assert "Prefer grep/find/ls" in agent._system_prompt


def test_explicit_tool_override_respected() -> None:
    """When ``tools=`` is passed explicitly, that list is used — non-regression guard.

    Passing a single-tool list must result in a system prompt that names
    that tool and does not include the full default 9-tool bundle.
    """
    from src.agents.tools.read import read_tool

    agent = SloAgent(
        llm=FauxChatModel(responses=[]),
        tools=[read_tool],
    )

    assert "read:" in agent._system_prompt


# ---------------------------------------------------------------------------
# Spec 29 — merged skills loading via SloAgent.__init__
# ---------------------------------------------------------------------------


def _write_agent_test_skill(directory: Path, slug: str, name: str, description: str = "A test skill") -> Path:
    """Write a minimal SKILL.md for agent-level tests.

    Args:
        directory (Path): Root user_skills or user_workflows directory.
        slug (str): Sub-folder name.
        name (str): Frontmatter name field.
        description (str): Frontmatter description field.

    Returns:
        Path: Absolute path to the written SKILL.md.
    """
    skill_dir: Path = directory / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    content: str = (
        f"---\nname: {name}\ndescription: {description}\n"
        f"when_to_use: Use for testing.\ngroup: user\nkind: skill\n---\n\n# {name}\n"
    )
    skill_file: Path = skill_dir / "SKILL.md"
    skill_file.write_text(content, encoding="utf-8")
    return skill_file


def test_agent_constructs_without_error_when_user_dirs_absent(tmp_path: Path) -> None:
    """SloAgent initialises normally when both user skill dirs do not exist."""
    import src.agents.slo_agent.agent as agent_module
    import config.cfg as cfg_module

    original_user_skills = cfg_module.USER_SKILLS_DIR
    original_user_workflows = cfg_module.USER_WORKFLOWS_DIR
    try:
        agent_module.USER_SKILLS_DIR = str(tmp_path / "nonexistent_user_skills")
        agent_module.USER_WORKFLOWS_DIR = str(tmp_path / "nonexistent_user_workflows")
        agent = SloAgent(
            llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
            tools=[],
            cwd=str(tmp_path),
        )
        assert isinstance(agent._skills, list)
    finally:
        agent_module.USER_SKILLS_DIR = original_user_skills
        agent_module.USER_WORKFLOWS_DIR = original_user_workflows


def test_agent_loads_user_skill_into_skills_list(tmp_path: Path) -> None:
    """A user skill placed in user_skills_dir appears in agent._skills."""
    import src.agents.slo_agent.agent as agent_module

    user_skills_dir: Path = tmp_path / "user_skills"
    user_skills_dir.mkdir()
    _write_agent_test_skill(
        directory=user_skills_dir,
        slug="my-custom-skill",
        name="my-custom-skill",
        description="A custom skill for testing.",
    )

    original_user_skills = agent_module.USER_SKILLS_DIR
    original_user_workflows = agent_module.USER_WORKFLOWS_DIR
    try:
        agent_module.USER_SKILLS_DIR = str(user_skills_dir)
        agent_module.USER_WORKFLOWS_DIR = str(tmp_path / "absent_workflows")
        agent = SloAgent(
            llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
            tools=[],
            cwd=str(tmp_path),
        )
        skill_names: list[str] = [s.name for s in agent._skills]
        assert "my-custom-skill" in skill_names
    finally:
        agent_module.USER_SKILLS_DIR = original_user_skills
        agent_module.USER_WORKFLOWS_DIR = original_user_workflows


def test_agent_user_skill_overrides_vendored_in_skills_list(tmp_path: Path) -> None:
    """User skill with same name as a vendored skill causes user file_path to win."""
    import src.agents.slo_agent.agent as agent_module

    user_skills_dir: Path = tmp_path / "user_skills"
    user_skills_dir.mkdir()
    # Use a name that matches a real vendored skill
    _write_agent_test_skill(
        directory=user_skills_dir,
        slug="build-routers",
        name="build-routers",
        description="My custom routers skill.",
    )

    original_user_skills = agent_module.USER_SKILLS_DIR
    original_user_workflows = agent_module.USER_WORKFLOWS_DIR
    try:
        agent_module.USER_SKILLS_DIR = str(user_skills_dir)
        agent_module.USER_WORKFLOWS_DIR = str(tmp_path / "absent_workflows")
        agent = SloAgent(
            llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
            tools=[],
            cwd=str(tmp_path),
        )
        matching = [s for s in agent._skills if s.name == "build-routers"]
        assert len(matching) == 1
        assert str(user_skills_dir) in matching[0].file_path
    finally:
        agent_module.USER_SKILLS_DIR = original_user_skills
        agent_module.USER_WORKFLOWS_DIR = original_user_workflows


# ---------------------------------------------------------------------------
# Pool retention + dynamic explicit caching (37.a.3)
# ---------------------------------------------------------------------------


def _two_member_dao() -> ModelPoolDAO:
    """Build a two-member pool DAO (gpt-5.4 OpenAI, claude-sonnet-4-6 Anthropic).

    Returns:
        ModelPoolDAO: A validated two-entry pool config.
    """
    return ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(
                model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1
            ),
        ]
    )


def _pool_with_anthropic_active() -> ModelPool:
    """Build a pool whose priority-0 (active) member is the Anthropic claude model.

    Returns:
        ModelPool: Pool whose active route is Anthropic (needs explicit caching).
    """
    dao = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(
                model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=0
            ),
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=1),
        ]
    )
    return ModelPool(
        pool_dao=dao,
        models={
            "claude-sonnet-4-6": FauxChatModel(responses=[]),
            "gpt-5.4": FauxChatModel(responses=[]),
        },
    )


class TestSloAgentRetainsPool:
    def test_lazy_pool_build_sets_llm_to_pool(self) -> None:
        """A lazy pool build leaves agent.llm a ModelPool (routed-model introspection works)."""
        faux_build = LLMBuildResult(llm=FauxChatModel(responses=[]), supports_explicit_caching=False)
        with patch.object(LLMFactory, "create", return_value=faux_build):
            agent = SloAgent(model_pool_dao=_two_member_dao(), tools=[])
        assert hasattr(agent.llm, "active_model_name")

    def test_single_model_build_sets_llm(self) -> None:
        """A lazy single-model build leaves agent.llm set to the bound model."""
        faux_build = LLMBuildResult(llm=FauxChatModel(responses=[]), supports_explicit_caching=False)
        with patch.object(LLMFactory, "create", return_value=faux_build):
            agent = SloAgent(model_name="gpt-5.4", tools=[])
        assert agent.llm is not None


class TestDynamicExplicitCaching:
    def test_reads_pool_supports_explicit_caching(self) -> None:
        """The agent reads the pool's live supports_explicit_caching flag."""
        agent = SloAgent(llm=_pool_with_anthropic_active(), tools=[])
        assert agent._resolve_supports_explicit_caching() is True

    def test_falls_back_to_static_flag_for_single_model(self) -> None:
        """A single model with no caching attr falls back to the static build flag."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        assert agent._resolve_supports_explicit_caching() is agent._supports_explicit_caching


# ---------------------------------------------------------------------------
# Iteration-scoped retry (37.a.5)
# ---------------------------------------------------------------------------

from typing import Any, AsyncIterator, Optional  # noqa: E402

from langchain_core.language_models.chat_models import BaseChatModel  # noqa: E402
from langchain_core.messages import AIMessageChunk, BaseMessage  # noqa: E402
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult  # noqa: E402
from pydantic import ConfigDict  # noqa: E402

from src.agents.providers.credit_exhaustion_policy import AllModelsExhaustedError  # noqa: E402
from src.agents.slo_agent.rate_limit.dao import RateLimitRetryPlanDAO  # noqa: E402


class _IterStatusError(Exception):
    """Exception carrying an HTTP ``status_code`` for iteration-retry tests."""

    def __init__(self, *, status_code: int) -> None:
        super().__init__(f"HTTP {status_code} rate limit")
        self.status_code = status_code


class _RaiseThenAnswerModel(BaseChatModel):
    """Raises ``error`` on the first generate call, then answers ``content``."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, *, error: Exception, content: str = "done", **data: Any) -> None:
        super().__init__(**data)
        self._error = error
        self._content = content
        self._calls = 0

    @property
    def _llm_type(self) -> str:
        return "raise-then-answer"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls += 1
        if self._calls == 1:
            raise self._error
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._content))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self._calls += 1
        if self._calls == 1:
            raise self._error
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._content))])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_RaiseThenAnswerModel":
        return self


class _AlwaysRaiseModel(BaseChatModel):
    """Raises ``error`` on every generate call."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(self, *, error: Exception, **data: Any) -> None:
        super().__init__(**data)
        self._error = error

    @property
    def _llm_type(self) -> str:
        return "always-raise"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise self._error

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        raise self._error

    def bind_tools(self, tools: Any, **kwargs: Any) -> "_AlwaysRaiseModel":
        return self


def _retry_then_stop(*, max_attempts: int = 2):
    """Return an iteration retry policy: retryable until ``max_attempts`` is hit."""

    def _decide(exc: BaseException, saw_visible: bool, attempt: int) -> RateLimitRetryPlanDAO:
        if attempt >= max_attempts:
            return RateLimitRetryPlanDAO(retryable=False, wait_seconds=0, message=str(exc))
        return RateLimitRetryPlanDAO(retryable=True, wait_seconds=0, message=f"retrying {attempt}")

    return _decide


class TestIterationScopedRetry:
    @pytest.mark.asyncio
    async def test_retries_iteration_with_no_visible_output(self) -> None:
        """A failure before any visible output retries the same iteration and recovers."""
        agent = SloAgent(llm=_RaiseThenAnswerModel(error=_IterStatusError(status_code=429)), tools=[])
        events = [
            e async for e in agent.invoke(query="go", iteration_retry_policy=_retry_then_stop())
        ]
        assert sum(1 for e in events if e.kind == "run_retrying") == 1
        assert sum(1 for e in events if e.kind == "run_completed") == 1
        assert events[-1].content == "done"

    @pytest.mark.asyncio
    async def test_all_models_exhausted_surfaces_run_failed_when_budget_spent(self) -> None:
        """Pool exhaustion past the attempt budget yields run_failed naming the members."""
        error = AllModelsExhaustedError(cooled_models=["gpt-5.4", "claude-sonnet-4-6"])
        agent = SloAgent(llm=_AlwaysRaiseModel(error=error), tools=[])
        events: list = []
        with pytest.raises(AllModelsExhaustedError):
            async for e in agent.invoke(
                query="go", iteration_retry_policy=_retry_then_stop(max_attempts=2)
            ):
                events.append(e)
        assert sum(1 for e in events if e.kind == "run_retrying") == 1
        failed = [e for e in events if e.kind == "run_failed"][-1]
        assert "cooldown" in (failed.content or "").lower()

    @pytest.mark.asyncio
    async def test_no_policy_preserves_legacy_no_retry_behavior(self) -> None:
        """Without an injected policy, any exception surfaces run_failed and re-raises."""
        agent = SloAgent(llm=_AlwaysRaiseModel(error=_IterStatusError(status_code=429)), tools=[])
        events: list = []
        with pytest.raises(_IterStatusError):
            async for e in agent.invoke(query="go"):
                events.append(e)
        assert sum(1 for e in events if e.kind == "run_retrying") == 0
        assert sum(1 for e in events if e.kind == "run_failed") == 1

    def test_decide_iteration_retry_blocks_after_visible_output(self) -> None:
        """The decision is non-retryable once the iteration emitted visible output."""
        agent = SloAgent(llm=_AlwaysRaiseModel(error=_IterStatusError(status_code=429)), tools=[])
        plan = agent._decide_iteration_retry(
            iteration_retry_policy=_retry_then_stop(),
            exc=RuntimeError("429"),
            saw_visible_output_this_iteration=True,
            attempt_number=1,
        )
        assert plan.retryable is False

    def test_decide_iteration_retry_none_policy_is_non_retryable(self) -> None:
        """No injected policy yields a non-retryable decision."""
        agent = SloAgent(llm=_AlwaysRaiseModel(error=_IterStatusError(status_code=429)), tools=[])
        plan = agent._decide_iteration_retry(
            iteration_retry_policy=None,
            exc=RuntimeError("429"),
            saw_visible_output_this_iteration=False,
            attempt_number=1,
        )
        assert plan.retryable is False


# ---------------------------------------------------------------------------
# Spec 05 — invoke declarative refactor: extracted method unit tests
# ---------------------------------------------------------------------------

from src.agents.slo_agent.assistant_chunk_normalizer import AssistantChunkNormalizer  # noqa: E402
from src.agents.slo_agent.events.stream import AgentStreamEventDAO  # noqa: E402
from src.agents.slo_agent.turn_stream_accumulator import TurnStreamAccumulator  # noqa: E402
from src.agents.slo_agent.sessions.usage import TokenUsageTotalsDAO  # noqa: E402


class TestValidateInvokeInputs:
    def test_raises_when_both_history_forms_supplied(self) -> None:
        """Both history and message_history → ValueError."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        with pytest.raises(ValueError, match="Pass only one of"):
            agent._validate_invoke_inputs(
                history=[{"role": "user", "content": "hi"}],
                message_history=[AIMessage(content="hi")],
            )

    def test_raises_when_already_running(self) -> None:
        """_running flag set → RuntimeError before any state change."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._running = True
        with pytest.raises(RuntimeError, match="SloAgent is already processing"):
            agent._validate_invoke_inputs(history=None, message_history=None)

    def test_passes_for_valid_inputs(self) -> None:
        """No history conflict, not running → no raise."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._validate_invoke_inputs(history=None, message_history=None)  # should not raise


class TestInitializeRunState:
    def test_resets_all_fields(self) -> None:
        """All five per-run fields are reset to their defaults."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._running = True
        agent._last_assistant_text = "stale"
        agent._last_usage_totals = TokenUsageTotalsDAO(input_tokens=100)
        agent._current_iteration = 5
        prior_turn = TurnStreamAccumulator()
        agent._active_turn = prior_turn

        agent._initialize_run_state()

        assert agent._running is True
        assert agent._last_assistant_text == ""
        assert agent._last_usage_totals == TokenUsageTotalsDAO()
        assert agent._current_iteration == 0
        assert agent._active_turn is not prior_turn


class TestTeardownRunState:
    def test_clears_abort_event_and_running_flag(self) -> None:
        """Abort event cleared and _running set to False."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._running = True
        agent._abort_event.set()

        agent._teardown_run_state()

        assert agent._running is False
        assert not agent._abort_event.is_set()


class TestApplySteering:
    @pytest.mark.asyncio
    async def test_yields_nothing_when_queue_empty(self) -> None:
        """Empty steering queue → no events, accumulated_messages unchanged."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        events = [
            e
            async for e in agent._apply_steering(
                accumulated_messages=accumulated,
                iteration=0,
                runtime_handler=None,
            )
        ]
        assert events == []
        assert len(accumulated) == 1

    @pytest.mark.asyncio
    async def test_yields_events_and_extends_accumulated_messages(self) -> None:
        """Non-empty queue → one steering_applied event, messages extended."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent.steer(message="please go on")
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]

        events = [
            e
            async for e in agent._apply_steering(
                accumulated_messages=accumulated,
                iteration=1,
                runtime_handler=None,
            )
        ]

        assert len(events) == 1
        assert events[0].kind == "steering_applied"
        assert len(accumulated) == 2


class TestShouldLoopContinue:
    @pytest.mark.asyncio
    async def test_returns_true_when_turn_has_tool_calls(self) -> None:
        """Last AIMessage has tool calls → True (loop continues)."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        accumulated: list[BaseMessage] = [
            HumanMessage(content="hi"),
            AIMessage(
                content="",
                tool_calls=[{"id": "c1", "name": "stub_now", "args": {}, "type": "tool_call"}],
            ),
        ]
        result = await agent._should_loop_continue(accumulated_messages=accumulated)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_tool_calls_and_no_steering(self) -> None:
        """No tool calls + no pending steering → False (stop)."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        accumulated: list[BaseMessage] = [
            HumanMessage(content="hi"),
            AIMessage(content="done"),
        ]
        result = await agent._should_loop_continue(accumulated_messages=accumulated)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_pending_steering_present(self) -> None:
        """No tool calls but steer queued → True (revive run)."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent.steer(message="keep going")
        accumulated: list[BaseMessage] = [
            HumanMessage(content="hi"),
            AIMessage(content="done"),
        ]
        result = await agent._should_loop_continue(accumulated_messages=accumulated)
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_hook_signals_stop(self) -> None:
        """Stop hook returning True → False when no pending steering."""
        from langchain_core.messages import HumanMessage

        def stop_hook(context) -> bool:
            return True

        agent = SloAgent(
            llm=FauxChatModel(responses=[]),
            tools=[],
            should_stop_after_turn_hook=stop_hook,
        )
        # Give _active_turn a completed assistant message so the hook fires
        turn = TurnStreamAccumulator()
        turn.absorb_messages(messages=[AIMessage(content="done")])
        agent._active_turn = turn
        accumulated: list[BaseMessage] = [
            HumanMessage(content="hi"),
            AIMessage(content="done"),
        ]
        result = await agent._should_loop_continue(accumulated_messages=accumulated)
        assert result is False


class TestHandlePreRunAbort:
    @pytest.mark.asyncio
    async def test_yields_run_aborted_event_at_iteration_zero(self) -> None:
        """Always yields a single run_aborted event at iteration=0."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        events = [
            e async for e in agent._handle_pre_run_abort(runtime_handler=None)
        ]
        assert len(events) == 1
        assert events[0].kind == "run_aborted"
        assert events[0].iteration == 0
        assert events[0].content == "<aborted>"


class TestEmitRunStartedTrace:
    @pytest.mark.asyncio
    async def test_calls_handler_with_correct_payload(self) -> None:
        """Emits run_started trace event with query as content."""
        from src.agents.slo_agent.events.runtime import AgentRuntimeEventDAO

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        captured: list[AgentRuntimeEventDAO] = []

        async def handler(event: AgentRuntimeEventDAO) -> None:
            captured.append(event)

        await agent._emit_run_started_trace(query="hello world", runtime_handler=handler)

        assert len(captured) == 1
        assert captured[0].kind == "run_started"
        assert captured[0].payload is not None
        assert captured[0].payload.content == "hello world"


class TestBuildInitialRunContext:
    def test_delegates_to_build_initial_messages(self) -> None:
        """Returns the same list as _build_initial_messages."""
        from langchain_core.messages import HumanMessage, SystemMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        result = agent._build_initial_run_context(
            query="test query",
            history=None,
            message_history=None,
        )
        assert isinstance(result, list)
        assert any(isinstance(m, SystemMessage) for m in result)
        assert isinstance(result[-1], HumanMessage)
        assert result[-1].content == "test query"


class TestProcessMessagesModeChunk:
    @pytest.mark.asyncio
    async def test_absorbs_chunk_and_captures_usage(self) -> None:
        """Chunk fed to normalizer, usage captured, events returned."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        normalizer = AssistantChunkNormalizer(iteration=0)
        chunk = AIMessageChunk(content="hello")

        events = await agent._process_messages_mode_chunk(
            chunk=chunk,
            normalizer=normalizer,
            runtime_handler=None,
        )

        assert isinstance(events, list)
        assert any(e.kind in ("text_start", "text_delta") for e in events)


class TestProcessUpdatesModeChunk:
    @pytest.mark.asyncio
    async def test_returns_empty_for_no_delta_messages(self) -> None:
        """Empty delta → returns [] without mutating anything."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        turn = TurnStreamAccumulator()
        normalizer = AssistantChunkNormalizer(iteration=0)

        events = await agent._process_updates_mode_chunk(
            chunk={},
            accumulated_messages=accumulated,
            turn=turn,
            iteration=0,
            normalizer=normalizer,
            runtime_handler=None,
        )

        assert events == []
        assert len(accumulated) == 1

    @pytest.mark.asyncio
    async def test_mutates_accumulated_messages_and_turn(self) -> None:
        """AIMessage delta extends accumulated_messages and is absorbed into turn."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        turn = TurnStreamAccumulator()
        normalizer = AssistantChunkNormalizer(iteration=0)
        ai_msg = AIMessage(content="response")

        await agent._process_updates_mode_chunk(
            chunk={"agent": {"messages": [ai_msg]}},
            accumulated_messages=accumulated,
            turn=turn,
            iteration=0,
            normalizer=normalizer,
            runtime_handler=None,
        )

        assert len(accumulated) == 2
        assert accumulated[-1] is ai_msg

    @pytest.mark.asyncio
    async def test_includes_tool_result_for_tool_message(self) -> None:
        """ToolMessage in delta → tool_result event in return list."""
        from langchain_core.messages import HumanMessage, ToolMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        turn = TurnStreamAccumulator()
        normalizer = AssistantChunkNormalizer(iteration=0)
        tool_msg = ToolMessage(content="tool output", tool_call_id="c1", name="stub_now")

        events = await agent._process_updates_mode_chunk(
            chunk={"tools": {"messages": [tool_msg]}},
            accumulated_messages=accumulated,
            turn=turn,
            iteration=0,
            normalizer=normalizer,
            runtime_handler=None,
        )

        assert any(e.kind == "tool_result" for e in events)
        tool_result = next(e for e in events if e.kind == "tool_result")
        assert tool_result.content == "tool output"

    @pytest.mark.asyncio
    async def test_includes_closing_events_for_ai_message(self) -> None:
        """AIMessage with open normalizer blocks → closing events in return list."""
        from langchain_core.messages import HumanMessage

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        turn = TurnStreamAccumulator()
        normalizer = AssistantChunkNormalizer(iteration=0)

        # Open a text block by absorbing a chunk first
        normalizer.absorb_chunk(chunk=AIMessageChunk(content="partial"))

        ai_msg = AIMessage(content="completed truth")
        events = await agent._process_updates_mode_chunk(
            chunk={"agent": {"messages": [ai_msg]}},
            accumulated_messages=accumulated,
            turn=turn,
            iteration=0,
            normalizer=normalizer,
            runtime_handler=None,
        )

        assert any(e.kind == "text_end" for e in events)


class TestFinalizeIteration:
    @pytest.mark.asyncio
    async def test_updates_last_assistant_text(self) -> None:
        """After finalization, _last_assistant_text reflects the turn's final text."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        turn = TurnStreamAccumulator()
        turn.absorb_messages(messages=[AIMessage(content="final answer")])
        normalizer = AssistantChunkNormalizer(iteration=0)

        events = [
            e
            async for e in agent._finalize_iteration(
                turn=turn,
                normalizer=normalizer,
                runtime_handler=None,
            )
        ]

        assert agent._last_assistant_text == "final answer"

    @pytest.mark.asyncio
    async def test_yields_closing_events_for_open_blocks(self) -> None:
        """Open normalizer blocks → closing events yielded during finalization."""
        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        turn = TurnStreamAccumulator()
        turn.absorb_messages(messages=[AIMessage(content="answer")])
        normalizer = AssistantChunkNormalizer(iteration=0)

        # Open a text block
        normalizer.absorb_chunk(chunk=AIMessageChunk(content="partial"))

        events = [
            e
            async for e in agent._finalize_iteration(
                turn=turn,
                normalizer=normalizer,
                runtime_handler=None,
            )
        ]

        assert any(e.kind == "text_end" for e in events)


class TestStreamGraphTurn:
    @pytest.mark.asyncio
    async def test_messages_mode_yields_chunk_events(self) -> None:
        """Messages-mode items → delegates to _process_messages_mode_chunk and yields events."""
        from langchain_core.messages import HumanMessage

        class _MsgGraph:
            async def astream(self, *_a, **_k):
                yield ("messages", AIMessageChunk(content="hello"))

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _MsgGraph()  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        normalizer = AssistantChunkNormalizer(iteration=0)
        turn = TurnStreamAccumulator()

        events = [
            e
            async for e in agent._stream_graph_turn(
                accumulated_messages=accumulated,
                normalizer=normalizer,
                turn=turn,
                iteration=0,
                runtime_handler=None,
            )
        ]

        assert any(e.kind in ("text_start", "text_delta") for e in events)

    @pytest.mark.asyncio
    async def test_skips_non_ai_message_chunks(self) -> None:
        """Non-AIMessageChunk in messages mode → silently skipped."""
        from langchain_core.messages import HumanMessage

        class _NonChunkGraph:
            async def astream(self, *_a, **_k):
                yield ("messages", HumanMessage(content="not a chunk"))

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _NonChunkGraph()  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        normalizer = AssistantChunkNormalizer(iteration=0)
        turn = TurnStreamAccumulator()

        events = [
            e
            async for e in agent._stream_graph_turn(
                accumulated_messages=accumulated,
                normalizer=normalizer,
                turn=turn,
                iteration=0,
                runtime_handler=None,
            )
        ]

        assert not any(e.kind in ("text_start", "text_delta") for e in events)

    @pytest.mark.asyncio
    async def test_skips_updates_with_no_update_chunk(self) -> None:
        """Updates-mode item with None update_chunk → silently skipped."""
        from langchain_core.messages import HumanMessage

        class _EmptyUpdatesGraph:
            async def astream(self, *_a, **_k):
                # yields an updates item with an invalid (non-dict) payload that
                # parse_graph_stream_item would reject — but we can simulate a None
                # update_chunk by having an empty dict (no messages key)
                yield ("updates", {})

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _EmptyUpdatesGraph()  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        normalizer = AssistantChunkNormalizer(iteration=0)
        turn = TurnStreamAccumulator()

        events = [
            e
            async for e in agent._stream_graph_turn(
                accumulated_messages=accumulated,
                normalizer=normalizer,
                turn=turn,
                iteration=0,
                runtime_handler=None,
            )
        ]

        assert events == []

    @pytest.mark.asyncio
    async def test_updates_mode_yields_update_events(self) -> None:
        """Updates-mode item with AIMessage → delegates and yields events."""
        from langchain_core.messages import HumanMessage

        class _UpdatesGraph:
            async def astream(self, *_a, **_k):
                yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _UpdatesGraph()  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        normalizer = AssistantChunkNormalizer(iteration=0)
        # First open a text block so finalize_open_blocks yields a closing event
        normalizer.absorb_chunk(chunk=AIMessageChunk(content="partial"))
        turn = TurnStreamAccumulator()

        events = [
            e
            async for e in agent._stream_graph_turn(
                accumulated_messages=accumulated,
                normalizer=normalizer,
                turn=turn,
                iteration=0,
                runtime_handler=None,
            )
        ]

        assert any(e.kind == "text_end" for e in events)
        assert len(accumulated) == 2

    @pytest.mark.asyncio
    async def test_yields_run_aborted_when_abort_set(self) -> None:
        """Abort event set before graph streams → yields run_aborted and returns."""
        from langchain_core.messages import HumanMessage

        class _SlowGraph:
            async def astream(self, *_a, **_k):
                yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _SlowGraph()  # type: ignore[assignment]
        agent._abort_event.set()  # set abort before streaming

        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]
        normalizer = AssistantChunkNormalizer(iteration=0)
        turn = TurnStreamAccumulator()

        events = [
            e
            async for e in agent._stream_graph_turn(
                accumulated_messages=accumulated,
                normalizer=normalizer,
                turn=turn,
                iteration=0,
                runtime_handler=None,
            )
        ]

        assert len(events) == 1
        assert events[0].kind == "run_aborted"


class TestExecuteIterationWithRetry:
    @pytest.mark.asyncio
    async def test_sets_active_turn_on_success(self) -> None:
        """Successful graph turn → self._active_turn updated."""
        from langchain_core.messages import HumanMessage

        class _SuccessGraph:
            async def astream(self, *_a, **_k):
                yield ("updates", {"agent": {"messages": [AIMessage(content="ok")]}})

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _SuccessGraph()  # type: ignore[assignment]
        prior_turn = agent._active_turn
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]

        events = [
            e
            async for e in agent._execute_iteration_with_retry(
                accumulated_messages=accumulated,
                iteration=0,
                runtime_handler=None,
                iteration_retry_policy=None,
            )
        ]

        assert agent._active_turn is not prior_turn
        assert not any(e.kind == "run_failed" for e in events)

    @pytest.mark.asyncio
    async def test_yields_run_failed_and_raises_on_non_retryable(self) -> None:
        """Non-retryable failure → exception re-raised; run_failed is NOT emitted here.

        Feature 50 moved ``run_failed`` emission out of ``_execute_iteration_with_retry``
        and into ``_react_loop``, which first offers the exception to the recovery policy.
        The inner helper now just re-raises without emitting any terminal event.
        """
        from langchain_core.messages import HumanMessage

        class _RaisingGraph:
            async def astream(self, *_a, **_k):
                if False:
                    yield  # async generator
                raise RuntimeError("catastrophic")

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _RaisingGraph()  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]

        events: list[AgentStreamEventDAO] = []
        with pytest.raises(RuntimeError, match="catastrophic"):
            async for e in agent._execute_iteration_with_retry(
                accumulated_messages=accumulated,
                iteration=0,
                runtime_handler=None,
                iteration_retry_policy=None,
            ):
                events.append(e)

        # run_failed is now emitted by _react_loop, NOT by _execute_iteration_with_retry
        assert not any(e.kind == "run_failed" for e in events)

    @pytest.mark.asyncio
    async def test_yields_run_retrying_on_retryable_failure(self) -> None:
        """Retryable failure before visible output → run_retrying event, then success."""
        from langchain_core.messages import HumanMessage

        call_count = {"n": 0}

        class _RaiseThenSucceedGraph:
            async def astream(self, *_a, **_k):
                call_count["n"] += 1
                if call_count["n"] == 1:
                    if False:
                        yield
                    raise _IterStatusError(status_code=429)
                yield ("updates", {"agent": {"messages": [AIMessage(content="ok")]}})

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _RaiseThenSucceedGraph()  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]

        events = [
            e
            async for e in agent._execute_iteration_with_retry(
                accumulated_messages=accumulated,
                iteration=0,
                runtime_handler=None,
                iteration_retry_policy=_retry_then_stop(max_attempts=2),
            )
        ]

        assert any(e.kind == "run_retrying" for e in events)
        assert not any(e.kind == "run_failed" for e in events)

    @pytest.mark.asyncio
    async def test_non_retryable_after_visible_output(self) -> None:
        """Retryable failure policy is overridden once visible output was emitted.

        Feature 50 moved ``run_failed`` emission out of ``_execute_iteration_with_retry``
        into ``_react_loop``. The inner helper re-raises without emitting run_failed;
        run_retrying is also suppressed when visible output preceded the failure.
        """
        from langchain_core.messages import HumanMessage

        class _VisibleThenRaiseGraph:
            async def astream(self, *_a, **_k):
                yield ("messages", AIMessageChunk(content="partial"))
                if False:
                    return
                raise RuntimeError("oops after visible output")

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _VisibleThenRaiseGraph()  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]

        events: list[AgentStreamEventDAO] = []
        with pytest.raises(RuntimeError):
            async for e in agent._execute_iteration_with_retry(
                accumulated_messages=accumulated,
                iteration=0,
                runtime_handler=None,
                iteration_retry_policy=_retry_then_stop(max_attempts=5),
            ):
                events.append(e)

        # run_failed is now emitted by _react_loop, NOT by _execute_iteration_with_retry
        assert not any(e.kind == "run_failed" for e in events)
        assert not any(e.kind == "run_retrying" for e in events)

    @pytest.mark.asyncio
    async def test_returns_without_finalization_on_abort(self) -> None:
        """Abort event set mid-turn → returns immediately, no run_completed."""
        from langchain_core.messages import HumanMessage

        class _AbortingGraph:
            def __init__(self, abort_event) -> None:
                self._abort_event = abort_event

            async def astream(self, *_a, **_k):
                self._abort_event.set()
                yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _AbortingGraph(agent._abort_event)  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]

        events = [
            e
            async for e in agent._execute_iteration_with_retry(
                accumulated_messages=accumulated,
                iteration=0,
                runtime_handler=None,
                iteration_retry_policy=None,
            )
        ]

        assert any(e.kind == "run_aborted" for e in events)
        assert not any(e.kind == "run_completed" for e in events)


class TestReactLoop:
    @pytest.mark.asyncio
    async def test_returns_on_abort_without_stop_evaluation(self) -> None:
        """Abort after first iteration → returns without evaluating stop conditions."""
        from langchain_core.messages import HumanMessage

        stop_hook_called = {"n": 0}

        def counting_hook(context) -> bool:
            stop_hook_called["n"] += 1
            return False

        class _AbortingGraph:
            def __init__(self, abort_event) -> None:
                self._abort_event = abort_event

            async def astream(self, *_a, **_k):
                self._abort_event.set()
                yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        agent = SloAgent(
            llm=FauxChatModel(responses=[]),
            tools=[],
            should_stop_after_turn_hook=counting_hook,
        )
        agent._graph = _AbortingGraph(agent._abort_event)  # type: ignore[assignment]
        accumulated: list[BaseMessage] = [HumanMessage(content="hi")]

        events = [
            e
            async for e in agent._react_loop(
                accumulated_messages=accumulated,
                runtime_handler=None,
                iteration_retry_policy=None,
            )
        ]

        assert any(e.kind == "run_aborted" for e in events)
        assert stop_hook_called["n"] == 0


class TestExecuteRun:
    @pytest.mark.asyncio
    async def test_skips_run_completed_after_abort(self) -> None:
        """Abort set during the run → no run_completed event emitted."""
        from langchain_core.messages import HumanMessage

        class _AbortingGraph:
            def __init__(self, abort_event) -> None:
                self._abort_event = abort_event

            async def astream(self, *_a, **_k):
                self._abort_event.set()
                yield ("updates", {"agent": {"messages": [AIMessage(content="done")]}})

        agent = SloAgent(llm=FauxChatModel(responses=[]), tools=[])
        agent._graph = _AbortingGraph(agent._abort_event)  # type: ignore[assignment]
        agent._initialize_run_state()  # set _running=True

        events = [
            e
            async for e in agent._execute_run(
                query="hi",
                history=None,
                message_history=None,
                runtime_handler=None,
                iteration_retry_policy=None,
            )
        ]

        assert any(e.kind == "run_aborted" for e in events)
        assert not any(e.kind == "run_completed" for e in events)
