"""Tests for ``SpawnSubAgentsTool`` and ``SessionConfigDAO.extra_tools`` (sub-spec 01-sub-agents 01.e)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.tools import BaseTool

from src.agents.slo_agent.orchestrator.dao import (
    OrchestratorResultDAO,
    SubAgentResultDAO,
)
from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsTool


# ── helpers ──────────────────────────────────────────────────────────────────


def _make_pool_mock(result: OrchestratorResultDAO) -> MagicMock:
    """Build a ``SubAgentPool`` mock returning a fixed dispatch result.

    Args:
        result (OrchestratorResultDAO): Result to return from ``dispatch``.

    Returns:
        MagicMock: Configured pool mock.
    """
    pool: MagicMock = MagicMock()
    pool.dispatch = AsyncMock(return_value=result)
    return pool


# ── tests ─────────────────────────────────────────────────────────────────────


class TestSpawnSubAgentsToolBuild:
    """``SpawnSubAgentsTool.build`` returns a usable ``BaseTool``."""

    def test_returns_langchain_base_tool(self) -> None:
        """``build()`` returns an instance of ``BaseTool``."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))

        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)

        assert isinstance(tool_obj, BaseTool)

    def test_tool_name_is_spawn_sub_agents(self) -> None:
        """The built tool has ``name='spawn_sub_agents'``."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))

        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)

        assert tool_obj.name == "spawn_sub_agents"


class TestSpawnSubAgentsToolDispatch:
    """``spawn_sub_agents`` invocation paths."""

    async def test_returns_orchestrator_result_json_on_success(self) -> None:
        """Successful dispatch returns JSON-serialised ``OrchestratorResultDAO``."""
        result: OrchestratorResultDAO = OrchestratorResultDAO(
            mode="parallel",
            results=[
                SubAgentResultDAO(
                    task_id="t1",
                    session_id="s1",
                    status="completed",
                    answer="done",
                    exit_code=0,
                )
            ],
        )
        pool: MagicMock = _make_pool_mock(result=result)
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps([{"task_id": "t1", "prompt": "Do it."}])

        raw: str = await tool_obj.ainvoke(
            input={"mode": "parallel", "tasks_json": tasks_json}
        )
        parsed: dict = json.loads(raw)

        assert parsed["mode"] == "parallel"
        assert parsed["results"][0]["task_id"] == "t1"

    async def test_invalid_json_returns_error_without_dispatching(self) -> None:
        """Malformed ``tasks_json`` returns a JSON error without calling ``dispatch``."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)

        raw: str = await tool_obj.ainvoke(
            input={"mode": "single", "tasks_json": "not-json"}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed
        pool.dispatch.assert_not_called()

    async def test_oversized_batch_returns_error_without_dispatching(self) -> None:
        """A ``tasks_json`` array exceeding ``MAX_PARALLEL_TASKS`` returns an error."""
        from src.agents.slo_agent.orchestrator.pool import MAX_PARALLEL_TASKS

        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="parallel"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps(
            [{"task_id": f"t{i}", "prompt": "x"} for i in range(MAX_PARALLEL_TASKS + 1)]
        )

        raw: str = await tool_obj.ainvoke(
            input={"mode": "parallel", "tasks_json": tasks_json}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed
        pool.dispatch.assert_not_called()

    async def test_invalid_task_definition_returns_error(self) -> None:
        """A task object missing required fields returns a JSON error without raising."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        # Missing required "prompt" field
        tasks_json: str = json.dumps([{"task_id": "t1"}])

        raw: str = await tool_obj.ainvoke(
            input={"mode": "single", "tasks_json": tasks_json}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed

    async def test_unknown_model_rejected_before_dispatch(self) -> None:
        """An unknown ``model`` returns an error naming the task and supported models, no dispatch."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps(
            [{"task_id": "synthesize", "prompt": "Do it.", "model": "claude-sonnet-4-5"}]
        )

        raw: str = await tool_obj.ainvoke(
            input={"mode": "single", "tasks_json": tasks_json}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed
        assert "synthesize" in parsed["error"]
        assert "claude-sonnet-4-5" in parsed["error"]
        assert "Supported models" in parsed["error"]
        pool.dispatch.assert_not_called()

    async def test_valid_model_passes_validation_and_dispatches(self) -> None:
        """A supported ``model`` clears validation and reaches ``dispatch``."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps(
            [{"task_id": "t1", "prompt": "Do it.", "model": "claude-sonnet-4-6"}]
        )

        await tool_obj.ainvoke(input={"mode": "single", "tasks_json": tasks_json})

        pool.dispatch.assert_called_once()

    async def test_omitted_model_skips_validation_and_dispatches(self) -> None:
        """A task without a ``model`` inherits the pool default and is not rejected."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps([{"task_id": "t1", "prompt": "Do it."}])

        await tool_obj.ainvoke(input={"mode": "single", "tasks_json": tasks_json})

        pool.dispatch.assert_called_once()

    async def test_reasoning_level_field_accepted_on_task(self) -> None:
        """A task carrying ``reasoning_level`` validates and dispatches (documents the key name)."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps(
            [
                {
                    "task_id": "t1",
                    "prompt": "Do it.",
                    "model": "claude-sonnet-4-6",
                    "reasoning_level": "medium",
                }
            ]
        )

        await tool_obj.ainvoke(input={"mode": "single", "tasks_json": tasks_json})

        pool.dispatch.assert_called_once()

    async def test_reasoning_key_typo_is_rejected(self) -> None:
        """The wrong key ``reasoning`` (not ``reasoning_level``) is rejected without dispatch."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps(
            [{"task_id": "t1", "prompt": "Do it.", "reasoning": "medium"}]
        )

        raw: str = await tool_obj.ainvoke(
            input={"mode": "single", "tasks_json": tasks_json}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed
        pool.dispatch.assert_not_called()

    def test_tool_schema_documents_reasoning_level_key(self) -> None:
        """The tool schema tells the LLM the key is ``reasoning_level``, not ``reasoning``."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)

        description: str = tool_obj.args_schema.model_fields["tasks_json"].description

        assert "reasoning_level" in description
        assert 'NOT "reasoning"' in description


class TestExtraToolsInjectionInSessionConfig:
    """``SessionConfigDAO.extra_tools`` accepts and stores ``BaseTool`` instances."""

    def test_extra_tools_field_accepts_base_tool_list(self, tmp_path) -> None:
        """``SessionConfigDAO`` accepts ``extra_tools`` with a ``BaseTool`` list."""
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            extra_tools=[mock_tool],
        )

        assert config.extra_tools is not None
        assert len(config.extra_tools) == 1

    def test_extra_tools_defaults_to_none(self, tmp_path) -> None:
        """``extra_tools`` defaults to ``None`` when not supplied."""
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)

        assert config.extra_tools is None

    def test_session_with_extra_tools_uses_extended_bundle(
        self, tmp_path
    ) -> None:
        """A session built with ``extra_tools`` passes merged tools to ``SloAgent``."""
        from unittest.mock import patch

        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        mock_tool.name = "my_custom_tool"
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            enable_history=False,
            extra_tools=[mock_tool],
        )
        session: SloAgentSession = SloAgentSession.build(config=config)

        captured_tools: list = []

        def _capture_slo_agent(*args, tools=None, **kwargs):
            if tools is not None:
                captured_tools.extend(tools)
            # Raise immediately; we only need to capture the tools argument.
            raise RuntimeError("stop_after_tool_capture")

        with patch("src.agents.slo_agent.sessions.service.SloAgent", side_effect=_capture_slo_agent):
            try:
                session._build_agent()
            except RuntimeError:
                pass

        tool_names: list[str] = [t.name for t in captured_tools]
        assert "my_custom_tool" in tool_names

    def test_session_without_extra_tools_passes_none_to_agent(
        self, tmp_path
    ) -> None:
        """A session without ``extra_tools`` passes ``tools=None`` to ``SloAgent``."""
        from unittest.mock import patch

        from src.agents.slo_agent.sessions.service import SloAgentSession
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            enable_history=False,
        )
        session: SloAgentSession = SloAgentSession.build(config=config)

        captured_tools: list = []

        def _capture_slo_agent(*args, tools=None, **kwargs):
            captured_tools.append(tools)
            raise RuntimeError("stop")

        with patch("src.agents.slo_agent.sessions.service.SloAgent", side_effect=_capture_slo_agent):
            try:
                session._build_agent()
            except RuntimeError:
                pass

        assert captured_tools[0] is None


class TestOrchestratorSystemPromptAddendum:
    """``ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM`` constant (sub-spec 03.b)."""

    def test_addendum_is_non_empty_string(self) -> None:
        """The addendum constant is a non-empty string."""
        from src.agents.slo_agent.orchestrator.spawn_tool import (
            ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
        )

        assert isinstance(ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM, str)
        assert len(ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM) > 0

    def test_addendum_contains_spawn_sub_agents(self) -> None:
        """The addendum mentions the tool by name."""
        from src.agents.slo_agent.orchestrator.spawn_tool import (
            ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
        )

        assert "spawn_sub_agents" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM

    def test_addendum_contains_only_constraint(self) -> None:
        """The addendum contains the word 'only' to assert the constraint."""
        from src.agents.slo_agent.orchestrator.spawn_tool import (
            ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
        )

        assert "only" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM.lower()

    def test_addendum_contains_explicit_keyword(self) -> None:
        """The addendum contains some form of 'explicit' to make the gate clear."""
        from src.agents.slo_agent.orchestrator.spawn_tool import (
            ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM,
        )

        assert "explicit" in ORCHESTRATOR_SYSTEM_PROMPT_ADDENDUM.lower()


class TestSpawnSubAgentsSchemaDAO:
    """``SpawnSubAgentsSchemaDAO`` guards all invocation paths (regression for
    the positional-argument ``TypeError`` caused by missing ``args_schema``)."""

    def test_schema_dao_is_exported(self) -> None:
        """``SpawnSubAgentsSchemaDAO`` is importable from ``spawn_tool``."""
        from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsSchemaDAO
        assert SpawnSubAgentsSchemaDAO is not None

    def test_schema_dao_validates_valid_input(self) -> None:
        """``SpawnSubAgentsSchemaDAO`` accepts a valid mode and tasks_json."""
        from src.agents.slo_agent.orchestrator.spawn_tool import SpawnSubAgentsSchemaDAO
        dao = SpawnSubAgentsSchemaDAO(mode="parallel", tasks_json='[{"task_id":"t1","prompt":"x"}]')
        assert dao.mode == "parallel"
        assert "task_id" in dao.tasks_json

    def test_tool_carries_explicit_args_schema(self) -> None:
        """The built tool's ``args_schema`` is ``SpawnSubAgentsSchemaDAO``, not inferred."""
        from src.agents.slo_agent.orchestrator.spawn_tool import (
            SpawnSubAgentsSchemaDAO,
            SpawnSubAgentsTool,
        )
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        assert tool_obj.args_schema is SpawnSubAgentsSchemaDAO


class TestSpawnSubAgentsToolInvocationPaths:
    """All call paths that LangChain / LangGraph can use to invoke the tool.

    These tests guard against the ``TypeError: spawn_sub_agents() takes
    N positional argument(s) but M were given`` failure that occurs when
    ``args_schema`` is absent and the LLM emits args as a raw JSON string.
    """

    async def test_ainvoke_with_dict_input(self) -> None:
        """``tool.ainvoke(dict)`` — the standard executor path — succeeds."""
        result: OrchestratorResultDAO = OrchestratorResultDAO(
            mode="parallel", all_completed=True
        )
        pool: MagicMock = _make_pool_mock(result=result)
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps([{"task_id": "t1", "prompt": "Do it."}])

        raw: str = await tool_obj.ainvoke(
            input={"mode": "parallel", "tasks_json": tasks_json}
        )
        parsed: dict = json.loads(raw)

        assert parsed["mode"] == "parallel"
        assert parsed["all_completed"] is True

    async def test_ainvoke_with_tool_call_dict_input(self) -> None:
        """``tool.ainvoke(tool_call_dict)`` — the LangGraph ToolNode path — succeeds.

        LangGraph passes a ToolCall-shaped dict with ``name``, ``args``, ``id``
        and ``type`` keys. LangChain's ``BaseTool.ainvoke`` unwraps it via
        ``_prep_run_args``.
        """
        result: OrchestratorResultDAO = OrchestratorResultDAO(
            mode="single", all_completed=True
        )
        pool: MagicMock = _make_pool_mock(result=result)
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps([{"task_id": "t1", "prompt": "Do it."}])
        tool_call_input: dict = {
            "name": "spawn_sub_agents",
            "args": {"mode": "single", "tasks_json": tasks_json},
            "id": "tc-abc",
            "type": "tool_call",
        }

        msg = await tool_obj.ainvoke(input=tool_call_input)

        # LangChain returns a ToolMessage when given a tool_call dict
        assert hasattr(msg, "content")
        parsed: dict = json.loads(msg.content)
        assert parsed["mode"] == "single"

    async def test_arun_with_schema_validated_kwargs(self) -> None:
        """``tool.arun(dict)`` dispatches correctly with schema-validated kwargs."""
        result: OrchestratorResultDAO = OrchestratorResultDAO(
            mode="chain", all_completed=False, failed_task_ids=["t1"]
        )
        pool: MagicMock = _make_pool_mock(result=result)
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps([{"task_id": "t1", "prompt": "Step 1."}])

        raw: str = await tool_obj.arun(
            tool_input={"mode": "chain", "tasks_json": tasks_json}
        )
        parsed: dict = json.loads(raw)

        assert parsed["mode"] == "chain"
        assert parsed["all_completed"] is False

    async def test_pool_dispatch_receives_correct_mode_and_tasks(self) -> None:
        """The pool's ``dispatch()`` is called with the correct parsed arguments."""
        result: OrchestratorResultDAO = OrchestratorResultDAO(mode="parallel")
        pool: MagicMock = _make_pool_mock(result=result)
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        tasks_json: str = json.dumps([
            {"task_id": "t1", "prompt": "Analyse imports."},
            {"task_id": "t2", "prompt": "Run tests."},
        ])

        await tool_obj.ainvoke(
            input={"mode": "parallel", "tasks_json": tasks_json}
        )

        pool.dispatch.assert_called_once()
        call_kwargs: dict = pool.dispatch.call_args.kwargs
        assert call_kwargs["mode"] == "parallel"
        assert len(call_kwargs["tasks"]) == 2
        assert call_kwargs["tasks"][0].task_id == "t1"
        assert call_kwargs["tasks"][1].task_id == "t2"

    async def test_invalid_tasks_json_does_not_call_dispatch(self) -> None:
        """Malformed ``tasks_json`` returns an error JSON without calling ``dispatch``."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)

        raw: str = await tool_obj.ainvoke(
            input={"mode": "single", "tasks_json": "not valid json"}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed
        pool.dispatch.assert_not_called()

    async def test_oversized_batch_does_not_call_dispatch(self) -> None:
        """A batch exceeding ``MAX_PARALLEL_TASKS`` returns an error without dispatching."""
        from src.agents.slo_agent.orchestrator.pool import MAX_PARALLEL_TASKS

        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="parallel"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        oversized: str = json.dumps([
            {"task_id": f"t{i}", "prompt": "x"} for i in range(MAX_PARALLEL_TASKS + 1)
        ])

        raw: str = await tool_obj.ainvoke(
            input={"mode": "parallel", "tasks_json": oversized}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed
        pool.dispatch.assert_not_called()

    async def test_task_missing_required_fields_returns_error(self) -> None:
        """A task object missing ``prompt`` returns a JSON error without raising."""
        pool: MagicMock = _make_pool_mock(OrchestratorResultDAO(mode="single"))
        tool_obj: BaseTool = SpawnSubAgentsTool.build(pool=pool)
        # Missing required "prompt" field
        bad_tasks: str = json.dumps([{"task_id": "t1"}])

        raw: str = await tool_obj.ainvoke(
            input={"mode": "single", "tasks_json": bad_tasks}
        )
        parsed: dict = json.loads(raw)

        assert "error" in parsed
        pool.dispatch.assert_not_called()
