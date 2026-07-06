"""Tests for ``SloAgentSession`` (sub-spec 02.a.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.agents.base import LLMBuildResult
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import SessionHistoryMetadataDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import PromptAttemptPlanDAO, SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.provider_for_model import provider_for_model


def _build_faux_session(
    *,
    workdir: Path,
    responses: list,
) -> SloAgentSession:
    """Build a session whose agent is wired to a scripted ``FauxChatModel``.

    Args:
        workdir (Path): Workdir for the agent.
        responses (list): Scripted ``AIMessage`` responses.

    Returns:
        SloAgentSession: Session ready for testing.
    """
    faux: FauxChatModel = FauxChatModel(responses=responses)
    agent: SloAgent = SloAgent(llm=faux, cwd=str(workdir))
    return SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id=str(uuid4()),
    )


async def _collect_result(
    *,
    session: SloAgentSession,
    text: str,
    history: list[dict] | None = None,
) -> tuple[str, int, bool]:
    """Drain ``session.invoke`` and summarize the terminal outcome.

    Args:
        session (SloAgentSession): Session under test.
        text (str): Prompt text.
        history (list[dict] | None): Optional legacy history.

    Returns:
        tuple[str, int, bool]: Final response, max iteration, and abort flag.
    """
    final_response: str = ""
    iterations: int = 0
    aborted: bool = False
    async for event in session.invoke(text=text, history=history):
        iterations = max(iterations, event.iteration)
        if event.kind == "run_completed":
            final_response = event.content or ""
        elif event.kind == "run_aborted":
            final_response = "<aborted>"
            aborted = True
    return final_response, iterations, aborted


class TestSloAgentSessionInvokeSummary:
    """Helpers that drain ``SloAgentSession.invoke`` to a terminal summary."""

    @pytest.mark.asyncio
    async def test_collect_result_returns_final_response(self, tmp_path: Path) -> None:
        """Faux scripted to say ``'hi'`` yields the expected terminal summary."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        response, iterations, aborted = await _collect_result(session=session, text="hello")

        assert response == "hi"
        assert iterations == 0
        assert aborted is False


class TestSloAgentSessionPromptStreaming:
    """``SloAgentSession.invoke`` — async-generator surface."""

    @pytest.mark.asyncio
    async def test_invoke_yields_each_progress_event(self, tmp_path: Path) -> None:
        """Every yielded value is an ``AgentStreamEventDAO``; the last is terminal."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        events: list[AgentStreamEventDAO] = []
        async for event in session.invoke(text="hello"):
            events.append(event)

        assert len(events) >= 1
        assert all(isinstance(e, AgentStreamEventDAO) for e in events)
        assert events[-1].kind == "run_completed"

    @pytest.mark.asyncio
    async def test_concurrent_prompt_raises_runtime_error(self, tmp_path: Path) -> None:
        """Second concurrent ``prompt`` while the first is in flight → ``RuntimeError``."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        session._is_running = True
        try:
            second_stream = session.invoke(text="second")
            with pytest.raises(RuntimeError, match="already processing"):
                await second_stream.__anext__()
        finally:
            session._is_running = False

    @pytest.mark.asyncio
    async def test_invoke_times_out_when_main_stream_goes_silent(self, tmp_path: Path) -> None:
        """A silent main stream is treated as hung instead of spinning forever."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        async def _hung_after_one_event(**_: object):
            yield AgentStreamEventDAO(kind="text_delta", delta="partial", iteration=0)
            await asyncio.Event().wait()

        yielded: list[AgentStreamEventDAO] = []
        with (
            patch.object(session.agent, "invoke", _hung_after_one_event),
            patch(
                "src.agents.slo_agent.sessions.service._stream_inactivity_timeout_seconds",
                return_value=0.01,
            ),
        ):
            with pytest.raises(TimeoutError, match="treated as hung"):
                async for event in session.invoke(text="hello"):
                    yielded.append(event)

        assert [event.kind for event in yielded] == ["text_delta"]
        assert session.is_running is False

    def test_build_initial_attempt_plan_returns_expected_defaults(self, tmp_path: Path) -> None:
        """The first attempt plan uses the declarative initial-attempt defaults."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        plan: PromptAttemptPlanDAO = session._build_initial_attempt_plan(text="hello")

        assert plan.attempt_kind == "initial"
        assert plan.text == "hello"
        assert plan.persist_user_message is True
        assert plan.excluded_turn_ids == frozenset()
        assert plan.preflight_compaction_mode == "respect_dirty_flag"
        assert plan.source_failed_turn_id is None

    @pytest.mark.asyncio
    async def test_prepare_attempt_context_allocates_turn_id_before_preflight(self, tmp_path: Path) -> None:
        """Context preparation allocates turn id before the preflight compaction check."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )
        plan: PromptAttemptPlanDAO = session._build_initial_attempt_plan(text="hello")
        order: list[str] = []
        policy: ModelRateLimitPolicyDAO = _policy(max_attempts=1)

        async def _ensure_history_session() -> None:
            order.append("ensure_history")

        async def _ensure_agent_ready() -> None:
            order.append("ensure_agent")

        async def _preflight_compaction(*, turn_id: str) -> None:
            order.append(f"preflight:{turn_id}")

        async def _load_message_history(
            *,
            excluded_turn_ids: set[str] | None = None,
        ) -> list:
            order.append(f"load_history:{sorted(excluded_turn_ids or set())}")
            return []

        with (
            patch.object(
                session,
                "_allocate_turn_id",
                side_effect=lambda: order.append("allocate_turn") or "turn-123",
            ),
            patch.object(session, "_ensure_history_session", new=AsyncMock(side_effect=_ensure_history_session)),
            patch.object(session, "_ensure_agent_ready", new=AsyncMock(side_effect=_ensure_agent_ready)),
            patch.object(session, "_preflight_compaction_if_dirty", new=AsyncMock(side_effect=_preflight_compaction)),
            patch.object(session, "_load_message_history", new=AsyncMock(side_effect=_load_message_history)),
            patch.object(session, "_resolve_attempt_policy", return_value=policy),
        ):
            prepared = await session._prepare_attempt_context(plan=plan)

        assert order == [
            "allocate_turn",
            "ensure_history",
            "ensure_agent",
            "preflight:turn-123",
            "load_history:[]",
        ]
        assert prepared.turn_id == "turn-123"
        assert prepared.plan == plan
        assert prepared.message_history == []
        assert prepared.runtime_handler is None
        assert prepared.policy is policy


class TestSloAgentSessionSubscribers:
    """Subscriber fan-out: subscribe / unsubscribe / exception isolation."""

    @pytest.mark.asyncio
    async def test_subscribe_handler_fires_for_every_event(self, tmp_path: Path) -> None:
        """Subscribed handler captures the exact event sequence the stream yielded."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )
        captured: list[AgentStreamEventDAO] = []

        async def _capture(event: AgentStreamEventDAO) -> None:
            captured.append(event)

        session.subscribe(handler=_capture)

        yielded: list[AgentStreamEventDAO] = []
        async for event in session.invoke(text="hello"):
            yielded.append(event)

        assert captured == yielded

    @pytest.mark.asyncio
    async def test_unsubscribe_handler_removes_it(self, tmp_path: Path) -> None:
        """After ``unsubscribe``, the handler is never called."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )
        captured: list[AgentStreamEventDAO] = []

        async def _capture(event: AgentStreamEventDAO) -> None:
            captured.append(event)

        session.subscribe(handler=_capture)
        session.unsubscribe(handler=_capture)

        async for _ in session.invoke(text="hello"):
            pass

        assert captured == []

    @pytest.mark.asyncio
    async def test_subscriber_exception_does_not_break_stream(self, tmp_path: Path) -> None:
        """A raising subscriber is logged and swallowed; siblings still run; ``log_error`` called."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )
        recorded: list[AgentStreamEventDAO] = []

        async def _bad(event: AgentStreamEventDAO) -> None:
            raise RuntimeError("boom")

        async def _good(event: AgentStreamEventDAO) -> None:
            recorded.append(event)

        session.subscribe(handler=_bad)
        session.subscribe(handler=_good)

        with patch("src.agents.slo_agent.sessions.service.log_error") as mock_log_error:
            yielded: list[AgentStreamEventDAO] = []
            async for event in session.invoke(text="hello"):
                yielded.append(event)

        assert recorded == yielded
        assert yielded[-1].kind == "run_completed"
        assert mock_log_error.call_count >= 1


class TestSloAgentSessionPassThroughs:
    """``steer`` / ``abort`` delegate to the underlying agent."""

    @pytest.mark.asyncio
    async def test_steer_delegates_to_agent(self, tmp_path: Path) -> None:
        """``session.steer(message=...)`` → ``agent.steer(message=...)``."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        with patch.object(session._agent, "steer") as mock_steer:
            session.steer(message="x")

        mock_steer.assert_called_once_with(message="x")

    @pytest.mark.asyncio
    async def test_abort_delegates_to_agent(self, tmp_path: Path) -> None:
        """``session.abort()`` calls through to ``agent.abort()`` once."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        with patch.object(session._agent, "abort") as mock_abort:
            session.abort()

        mock_abort.assert_called_once_with()


class TestSloAgentSessionWorkspaceFile:
    """Workspace-file threading and fallback behavior on lazy sessions."""

    def test_build_agent_threads_workspace_file_into_slo_agent(self, tmp_path: Path) -> None:
        """Lazy agent construction passes SessionConfigDAO.workspace_file through."""
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": []}', encoding="utf-8")
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            workspace_file=workspace_file,
        )
        session: SloAgentSession = SloAgentSession.build(config=config)

        with patch("src.agents.slo_agent.sessions.service.SloAgent") as MockSloAgent:
            session.agent

        MockSloAgent.assert_called_once()
        assert MockSloAgent.call_args.kwargs["workspace_file"] == workspace_file

    def test_slo_agent_falls_back_when_workspace_file_is_missing(self, tmp_path: Path) -> None:
        """A missing workspace file yields no workspace folders and no exception."""
        faux: FauxChatModel = FauxChatModel(responses=[])
        missing_workspace_file: Path = tmp_path / "missing.code-workspace"

        agent: SloAgent = SloAgent(
            llm=faux,
            cwd=str(tmp_path),
            workspace_file=missing_workspace_file,
        )

        assert agent.workspace_folders == []


    @pytest.mark.asyncio
    async def test_resume_reuses_persisted_workspace_file_from_session_metadata(self, tmp_path: Path) -> None:
        """A resumed session reuses the persisted workspace file when config omits it."""
        history_root: Path = tmp_path / "history"
        workspace_file: Path = tmp_path / "x.code-workspace"
        workspace_file.write_text('{"folders": []}', encoding="utf-8")
        original_config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            workspace_file=workspace_file,
            history_root=history_root,
        )
        original_session: SloAgentSession = SloAgentSession.build(config=original_config)

        await original_session._ensure_history_session()
        persisted_metadata: SessionHistoryMetadataDAO = await original_session.history_store.read_metadata(
            session_id=original_session.session_id,
        )
        assert persisted_metadata.workspace_file == workspace_file

        resumed_config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            session_id=original_session.session_id,
            history_root=history_root,
        )
        resumed_session: SloAgentSession = SloAgentSession.build(config=resumed_config)

        with patch("src.agents.slo_agent.sessions.service.SloAgent") as MockSloAgent:
            resumed_session.agent

        assert MockSloAgent.call_args.kwargs["workspace_file"] == workspace_file


class TestSloAgentSessionActiveModelState:
    """Runtime active-model and active-reasoning ownership on lazy sessions."""

    def test_build_seeds_active_model_name_from_config(self, tmp_path: Path) -> None:
        """`build` keeps the configured model name as active runtime state."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-sonnet-4-6",
        )

        session: SloAgentSession = SloAgentSession.build(config=config)

        assert session.active_model_name == "claude-sonnet-4-6"

    def test_build_seeds_active_reasoning_level_from_config_override(self, tmp_path: Path) -> None:
        """Configured reasoning overrides are clamped and stored at build time."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-sonnet-4-6",
            reasoning_level="xhigh",
        )

        session: SloAgentSession = SloAgentSession.build(config=config)

        assert session.active_reasoning_level == "high"

    def test_build_seeds_default_active_reasoning_level_when_no_override_exists(self, tmp_path: Path) -> None:
        """Supported reasoning models seed to the default canonical level."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
        )

        session: SloAgentSession = SloAgentSession.build(config=config)

        assert session.active_reasoning_level == "high"

    def test_switch_model_updates_active_model_and_clears_lazy_agent(self, tmp_path: Path) -> None:
        """Switching models invalidates the cached lazy-built agent."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            reasoning_level="xhigh",
        )
        faux: FauxChatModel = FauxChatModel(responses=[])

        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ):
            session: SloAgentSession = SloAgentSession.build(config=config)
            _first_agent: SloAgent = session.agent
            assert session._agent is not None

        session.switch_model(model_name="claude-sonnet-4-6")

        assert session.active_model_name == "claude-sonnet-4-6"
        assert session.active_reasoning_level == "high"
        assert session._agent is None

    def test_switch_model_marks_context_window_dirty(self, tmp_path: Path) -> None:
        """Switching models flags a pre-flight compaction check for the next turn."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
        )
        faux: FauxChatModel = FauxChatModel(responses=[])

        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ):
            session: SloAgentSession = SloAgentSession.build(config=config)

        session._context_window_dirty = False

        session.switch_model(model_name="claude-sonnet-4-6")

        assert session._context_window_dirty is True

    def test_switch_reasoning_level_updates_state_and_clears_lazy_agent(self, tmp_path: Path) -> None:
        """Switching reasoning invalidates the cached lazy-built agent."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
        )
        faux: FauxChatModel = FauxChatModel(responses=[])

        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ):
            session: SloAgentSession = SloAgentSession.build(config=config)
            _first_agent = session.agent
            assert session._agent is not None

        active_level: str = session.switch_reasoning_level(reasoning_level="off")

        assert active_level == "off"
        assert session.active_reasoning_level == "off"
        assert session._agent is None

    def test_switch_model_on_prebuilt_agent_session_raises(self, tmp_path: Path) -> None:
        """Pre-built-agent sessions reject runtime model switching."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[],
        )

        with pytest.raises(RuntimeError, match="Cannot switch models"):
            session.switch_model(model_name="claude-sonnet-4-6")

    def test_switch_reasoning_level_on_prebuilt_agent_session_raises(self, tmp_path: Path) -> None:
        """Pre-built-agent sessions reject runtime reasoning switching."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[],
        )

        with pytest.raises(RuntimeError, match="Cannot switch reasoning"):
            session.switch_reasoning_level(reasoning_level="high")


class TestSloAgentSessionNaming:
    """Session-name persistence on history-enabled sessions."""

    @pytest.mark.asyncio
    async def test_rename_session_persists_name_and_updates_property(self, tmp_path: Path) -> None:
        """Renaming a history-enabled session persists immediately."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            history_root=tmp_path / "history",
        )
        session: SloAgentSession = SloAgentSession.build(config=config)

        metadata: SessionHistoryMetadataDAO = await session.rename_session(
            session_name="Customer Import Regression",
        )

        assert metadata.session_name == "Customer Import Regression"
        assert metadata.session_name_key == "customer import regression"
        assert session.session_name == "Customer Import Regression"

    @pytest.mark.asyncio
    async def test_rename_session_without_history_raises(self, tmp_path: Path) -> None:
        """Sessions with disabled history reject rename requests."""
        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[],
        )

        with pytest.raises(RuntimeError, match="history is disabled"):
            await session.rename_session(session_name="Nope")


class TestSloAgentSessionBuild:
    """``SloAgentSession.build`` end-to-end construction."""

    def test_build_assembles_agent_and_session(self, tmp_path: Path) -> None:
        """``build`` returns a session whose agent and ids match the supplied config."""
        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)

        # ``SloAgent`` falls through to ``LLMFactory.create`` when no
        # ``llm`` is supplied; tests run without provider credentials, so
        # patch the factory to return a deterministic Faux instead.
        faux: FauxChatModel = FauxChatModel(responses=[])
        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ):
            session: SloAgentSession = SloAgentSession.build(config=config)

            # Lazy build path: ``build`` stashes the config but doesn't
            # construct the agent until ``session.agent`` is read.
            assert isinstance(session.agent, SloAgent)

        assert session.workdir == tmp_path
        assert UUID(session.session_id).version == 4
        assert session.agent._cwd == str(tmp_path)


class TestSloAgentSessionLazyBuild:
    """Lazy ``SloAgent`` construction in ``SloAgentSession``."""

    def test_init_without_config_or_agent_raises(self, tmp_path: Path) -> None:
        """``__init__`` with neither ``config`` nor ``agent`` raises ``ValueError``."""
        with pytest.raises(ValueError, match="requires either"):
            SloAgentSession(
                workdir=tmp_path,
                session_id=str(uuid4()),
            )

    def test_build_does_not_construct_agent_eagerly(self, tmp_path: Path) -> None:
        """``build`` stashes config without invoking the ``SloAgent`` constructor."""
        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)

        with patch("src.agents.slo_agent.sessions.service.SloAgent") as mock_agent_cls:
            session: SloAgentSession = SloAgentSession.build(config=config)

            assert session._agent is None
            assert mock_agent_cls.call_count == 0

    def test_agent_property_builds_once_and_caches(self, tmp_path: Path) -> None:
        """First read of ``session.agent`` builds; subsequent reads reuse the instance."""
        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)
        faux: FauxChatModel = FauxChatModel(responses=[])

        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ) as mock_factory:
            session: SloAgentSession = SloAgentSession.build(config=config)

            first: SloAgent = session.agent
            second: SloAgent = session.agent

        assert first is second
        # ``LLMFactory.create`` is called exactly once across both reads.
        assert mock_factory.call_count == 1

    def test_abort_is_noop_before_lazy_build(self, tmp_path: Path) -> None:
        """``abort`` before the agent is built does not trigger lazy construction."""
        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)

        with patch("src.agents.slo_agent.sessions.service.SloAgent") as mock_agent_cls:
            session: SloAgentSession = SloAgentSession.build(config=config)
            session.abort()

            assert session._agent is None
            assert mock_agent_cls.call_count == 0

    @pytest.mark.asyncio
    async def test_invoke_propagates_factory_value_error(self, tmp_path: Path) -> None:
        """A missing-credential ``ValueError`` from the factory surfaces at prompt time."""
        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)

        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            side_effect=ValueError("SLO_OPENAI_API_KEY is not set."),
        ):
            session: SloAgentSession = SloAgentSession.build(config=config)

            with pytest.raises(ValueError, match="SLO_OPENAI_API_KEY"):
                async for _ in session.invoke(text="hello"):
                    pass

        # The failed lazy build does not leave ``is_running`` stuck.
        assert session.is_running is False

    @pytest.mark.asyncio
    async def test_invoke_refreshes_stale_openai_oauth_before_lazy_build(
        self, tmp_path: Path
    ) -> None:
        """The proactive OAuth refresh runs at the async session seam, not in LLMFactory.

        This is the regression guard for the ``asyncio.run() cannot be
        called from a running event loop`` bug: refresh happens inside
        ``invoke`` (already async) before the session builds
        the lazy agent.
        """
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5",
            enable_history=False,
        )
        stale_cred = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token="header.eyJodHRwczovL2FwaS5vcGVuYWkuY29tL2F1dGgiOnsiY2hhdGdwdF9hY2NvdW50X2lkIjoiYWNjdCJ9fQ.sig",
            refresh_token="rt-1",
        )
        faux: FauxChatModel = FauxChatModel(
            responses=[FauxChatModel.assistant_message(content="hi")],
        )

        with (
            patch(
                "src.agents.slo_agent.sessions.service.CredentialResolver.require",
                return_value=stale_cred,
            ),
            patch(
                "src.agents.slo_agent.sessions.service.refresh_if_stale",
                return_value=stale_cred,
            ) as mock_refresh,
            patch(
                "src.agents.slo_agent.graph.LLMFactory.create",
                return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
            ),
        ):
            session: SloAgentSession = SloAgentSession.build(config=config)
            response, _iterations, _aborted = await _collect_result(session=session, text="hello")

        mock_refresh.assert_awaited_once()
        assert response == "hi"


def _build_pool_mock():
    """Build a ``SubAgentPool``-like mock with a ``cancel_all`` async method.

    Returns:
        MagicMock: Mock with ``cancel_all`` as an ``AsyncMock``.
    """
    from unittest.mock import AsyncMock, MagicMock

    pool = MagicMock()
    pool.cancel_all = AsyncMock()
    return pool


def _build_faux_agent(tmp_path: Path) -> SloAgent:
    """Build a minimal ``SloAgent`` backed by ``FauxChatModel``.

    Args:
        tmp_path (Path): Pytest temporary path for the agent cwd.

    Returns:
        SloAgent: Lightweight agent for unit-level session tests.
    """
    return SloAgent(
        llm=FauxChatModel(
            responses=[FauxChatModel.assistant_message(content="ok")]
        ),
        cwd=str(tmp_path),
        tools=[],
    )


class TestSloAgentSessionEventRelay:
    """``event_relay`` property — contract and regression tests (sub-spec 03.a)."""

    def test_event_relay_returns_callable(self, tmp_path: Path) -> None:
        """``event_relay`` is a callable usable as an ``AgentEventSubscriber``."""
        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path,
            session_id="s1",
            agent=_build_faux_agent(tmp_path),
            enable_history=False,
        )

        relay = session.event_relay

        assert callable(relay)

    async def test_event_relay_accepts_positional_call(
        self, tmp_path: Path
    ) -> None:
        """``event_relay`` called with a POSITIONAL argument dispatches correctly.

        Regression: returning ``self._dispatch_event`` directly failed because
        ``_dispatch_event`` declares ``event`` as keyword-only (``*, event``).
        The pool calls ``await relay(event)`` positionally, which raised:
        ``TypeError: _dispatch_event() takes 1 positional argument but 2 were given``.
        """
        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path,
            session_id="s1",
            agent=_build_faux_agent(tmp_path),
            enable_history=False,
        )
        received: list[AgentStreamEventDAO] = []

        async def _collector(event: AgentStreamEventDAO) -> None:
            received.append(event)

        session.subscribe(handler=_collector)
        event: AgentStreamEventDAO = AgentStreamEventDAO(kind="text_delta", delta="hi")

        # Positional call — exactly how SubAgentPool/_emit_lifecycle calls the relay.
        await session.event_relay(event)

        assert len(received) == 1
        assert received[0].kind == "text_delta"

    async def test_event_relay_sub_agent_event_roundtrip(
        self, tmp_path: Path
    ) -> None:
        """A sub-agent lifecycle event dispatched via ``event_relay`` reaches subscribers.

        Verifies the full path: pool emits ``sub_agent_spawned`` via relay →
        session subscribers receive it with identity fields intact.
        """
        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path,
            session_id="s1",
            agent=_build_faux_agent(tmp_path),
            enable_history=False,
        )
        received: list[AgentStreamEventDAO] = []

        async def _collector(event: AgentStreamEventDAO) -> None:
            received.append(event)

        session.subscribe(handler=_collector)
        sub_agent_event: AgentStreamEventDAO = AgentStreamEventDAO(
            kind="sub_agent_spawned",
            sub_agent_id="child-uuid",
            task_id="t1",
        )

        # Positional — the pool's calling convention.
        await session.event_relay(sub_agent_event)

        assert len(received) == 1
        assert received[0].sub_agent_id == "child-uuid"
        assert received[0].task_id == "t1"


class TestSloAgentSessionAttachSubAgentPool:
    """``attach_sub_agent_pool()`` promotion seam (sub-spec 03.a)."""

    def test_attach_pool_merges_spawn_tool_into_extra_tools(
        self, tmp_path: Path
    ) -> None:
        """After attach, ``_config.extra_tools`` contains the spawn tool."""
        from unittest.mock import MagicMock
        from langchain_core.tools import BaseTool

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )
        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        mock_tool.name = "spawn_sub_agents"
        pool = _build_pool_mock()

        session.attach_sub_agent_pool(pool=pool, spawn_tool=mock_tool)

        assert session._config.extra_tools is not None
        tool_names: list[str] = [t.name for t in session._config.extra_tools]
        assert "spawn_sub_agents" in tool_names

    def test_attach_pool_sets_append_system_prompt(self, tmp_path: Path) -> None:
        """After attach, ``_config.append_system_prompt`` is non-empty."""
        from unittest.mock import MagicMock
        from langchain_core.tools import BaseTool

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )
        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        mock_tool.name = "spawn_sub_agents"

        session.attach_sub_agent_pool(pool=_build_pool_mock(), spawn_tool=mock_tool)

        assert session._config.append_system_prompt is not None
        assert "spawn_sub_agents" in session._config.append_system_prompt

    def test_attach_pool_stores_pool_reference(self, tmp_path: Path) -> None:
        """After attach, ``_sub_agent_pool`` is the supplied pool."""
        from unittest.mock import MagicMock
        from langchain_core.tools import BaseTool

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )
        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        mock_tool.name = "spawn_sub_agents"
        pool = _build_pool_mock()

        session.attach_sub_agent_pool(pool=pool, spawn_tool=mock_tool)

        assert session._sub_agent_pool is pool

    def test_attach_pool_raises_when_agent_already_built(
        self, tmp_path: Path
    ) -> None:
        """``attach_sub_agent_pool`` raises ``RuntimeError`` when called after first prompt."""
        from unittest.mock import MagicMock
        from langchain_core.tools import BaseTool

        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path,
            session_id="s1",
            agent=_build_faux_agent(tmp_path),
            enable_history=False,
        )
        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        mock_tool.name = "spawn_sub_agents"

        with pytest.raises(RuntimeError, match="already been built"):
            session.attach_sub_agent_pool(
                pool=_build_pool_mock(),
                spawn_tool=mock_tool,
            )

    async def test_abort_calls_pool_cancel_all_when_pool_attached(
        self, tmp_path: Path
    ) -> None:
        """``abort()`` calls ``pool.cancel_all()`` when a pool is attached."""
        import asyncio
        from unittest.mock import MagicMock
        from langchain_core.tools import BaseTool

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )
        pool = _build_pool_mock()
        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        mock_tool.name = "spawn_sub_agents"
        session.attach_sub_agent_pool(pool=pool, spawn_tool=mock_tool)

        session.abort()
        await asyncio.sleep(0)

        pool.cancel_all.assert_called_once()

    def test_abort_without_pool_does_not_raise(self, tmp_path: Path) -> None:
        """``abort()`` on a session without a pool does not raise."""
        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path,
            session_id="s1",
            agent=_build_faux_agent(tmp_path),
            enable_history=False,
        )

        session.abort()  # must not raise


# ---------------------------------------------------------------------------
# Helpers for pool-aware session tests
# ---------------------------------------------------------------------------


def _build_pool_session(
    *,
    llm,
    workdir: Path,
    model_name: str = "faux",
) -> SloAgentSession:
    """Build a session whose agent is injected with ``llm`` (supports duck-typed pool).

    Args:
        llm: Any ``BaseChatModel`` subclass, including ``ModelPool``.
        workdir (Path): Temporary working directory.
        model_name (str): Fallback model-name stored on the session.

    Returns:
        SloAgentSession: Session ready for ``_resolve_active_model_name`` testing.
    """
    agent: SloAgent = SloAgent(llm=llm, cwd=str(workdir))
    session: SloAgentSession = SloAgentSession(
        agent=agent,
        workdir=workdir,
        session_id=str(uuid4()),
    )
    session._active_model_name = model_name
    return session


class TestSloAgentSessionResolveActiveModelName:
    """``_resolve_active_model_name`` — pool duck-type dispatch (spec 28.a.7)."""

    def test_plain_llm_returns_session_active_model_name(self, tmp_path: Path) -> None:
        """A plain ``FauxChatModel`` has no ``active_model_name``; fallback used."""
        from src.agents.providers.faux import FauxChatModel

        faux: FauxChatModel = FauxChatModel(responses=[])
        session: SloAgentSession = _build_pool_session(
            llm=faux,
            workdir=tmp_path,
            model_name="gpt-5.4",
        )

        result: str = session._resolve_active_model_name()
        assert result == "gpt-5.4"

    def test_pool_llm_returns_pool_active_model_name(self, tmp_path: Path) -> None:
        """When the injected llm has ``active_model_name``, it is used over the fallback."""
        from langchain_core.messages import AIMessage
        from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
        from src.agents.providers.faux import FauxChatModel

        pool_dao: ModelPoolDAO = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(
                    model_name="kimi-for-coding",
                    provider=ProviderName.KIMI_FOR_CODING,
                    priority=0,
                ),
                ModelPoolEntryDAO(
                    model_name="claude-sonnet-4-6",
                    provider=ProviderName.ANTHROPIC,
                    priority=1,
                ),
            ]
        )
        pool: ModelPool = ModelPool(
            pool_dao=pool_dao,
            models={
                "kimi-for-coding": FauxChatModel(responses=[AIMessage(content="ok")]),
                "claude-sonnet-4-6": FauxChatModel(responses=[AIMessage(content="ok2")]),
            },
        )
        session: SloAgentSession = _build_pool_session(
            llm=pool,
            workdir=tmp_path,
            model_name="fallback-name",
        )

        result: str = session._resolve_active_model_name()
        assert result == "kimi-for-coding"

    def test_no_agent_returns_empty_string(self, tmp_path: Path) -> None:
        """When ``_agent`` is None (lazy session), an empty string is returned."""
        from src.agents.slo_agent.sessions.dao import SessionConfigDAO

        config: SessionConfigDAO = SessionConfigDAO(workdir=tmp_path)
        session: SloAgentSession = SloAgentSession.build(config=config)
        session._active_model_name = None

        result: str = session._resolve_active_model_name()
        assert result == ""

    def test_agent_with_no_llm_falls_back_to_active_model_name(self, tmp_path: Path) -> None:
        """An agent built from ``model_name`` (not ``llm``) uses the session fallback."""
        from src.agents.providers.faux import FauxChatModel
        from src.agents.base import LLMBuildResult

        faux: FauxChatModel = FauxChatModel(responses=[])
        with patch(
            "src.agents.slo_agent.graph.LLMFactory.create",
            return_value=LLMBuildResult(llm=faux, supports_explicit_caching=False),
        ):
            from src.agents.slo_agent.sessions.dao import SessionConfigDAO

            config: SessionConfigDAO = SessionConfigDAO(
                workdir=tmp_path,
                model_name="claude-opus-4-7",
            )
            session: SloAgentSession = SloAgentSession.build(config=config)
            _agent = session.agent  # trigger lazy build

        result: str = session._resolve_active_model_name()
        assert result == "claude-opus-4-7"


# ---------------------------------------------------------------------------
# Session pool config, multi-provider refresh, routed identity (37.a.4)
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402

from src.auth.credential_resolver import CredentialResolver  # noqa: E402


def _two_member_dao() -> ModelPoolDAO:
    """Build a two-member pool DAO (gpt-5.4 OpenAI, claude-sonnet-4-6 Anthropic)."""
    return ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(
                model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1
            ),
        ]
    )


def _openai_anthropic_kfc_dao() -> ModelPoolDAO:
    """Build a three-provider pool DAO."""
    return ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(
                model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1
            ),
            ModelPoolEntryDAO(
                model_name="kimi-for-coding", provider=ProviderName.KIMI_FOR_CODING, priority=2
            ),
        ]
    )


def _session_with_pool(dao: ModelPoolDAO, *, workdir: Path) -> SloAgentSession:
    """Build a lazy-config session carrying ``dao`` with history disabled."""
    config = SessionConfigDAO(
        workdir=workdir,
        model_name=dao.entries[0].model_name,
        model_pool_dao=dao,
        enable_history=False,
    )
    return SloAgentSession.build(config=config)


def _single_model_session(model_name: str, *, workdir: Path) -> SloAgentSession:
    """Build a lazy-config single-model session with history disabled."""
    config = SessionConfigDAO(
        workdir=workdir,
        model_name=model_name,
        enable_history=False,
    )
    return SloAgentSession.build(config=config)


def _injected_pool_agent(*, active: str, workdir: Path) -> SloAgent:
    """Build a pre-built agent whose injected ModelPool routes to ``active`` first."""
    dao = ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(
                model_name=active, provider=provider_for_model(model_name=active), priority=0
            ),
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=1),
        ]
    )
    pool = ModelPool(
        pool_dao=dao,
        models={active: FauxChatModel(responses=[]), "gpt-5.4": FauxChatModel(responses=[])},
    )
    return SloAgent(llm=pool, cwd=str(workdir), tools=[])


def _capturing_agent(captured: dict):
    """Return a fake SloAgent class that records its construction kwargs."""

    class _FakeAgent:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self.llm = None

    return _FakeAgent


def _record_refresh(refreshed: list):
    """Return an async refresh_if_stale stand-in that records each cred's provider."""

    async def _refresh(*, cred, store) -> None:
        refreshed.append(cred.provider)

    return _refresh


def _require_stub(*, provider: ProviderName):
    """Stand-in for CredentialResolver.require returning a provider-tagged cred."""
    return SimpleNamespace(provider=provider)


class TestSessionPoolBuild:
    def test_build_agent_passes_pool_dao(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_build_agent threads config.model_pool_dao into the SloAgent constructor."""
        captured: dict = {}
        monkeypatch.setattr(
            "src.agents.slo_agent.sessions.service.SloAgent", _capturing_agent(captured)
        )
        session = _session_with_pool(_two_member_dao(), workdir=tmp_path)
        _ = session.agent
        assert captured["model_pool_dao"] is not None
        assert [e.model_name for e in captured["model_pool_dao"].entries] == [
            "gpt-5.4",
            "claude-sonnet-4-6",
        ]

    def test_build_agent_single_model_passes_none_pool(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A single-model session passes model_pool_dao=None."""
        captured: dict = {}
        monkeypatch.setattr(
            "src.agents.slo_agent.sessions.service.SloAgent", _capturing_agent(captured)
        )
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        _ = session.agent
        assert captured["model_pool_dao"] is None


class TestSessionMultiProviderRefresh:
    @pytest.mark.asyncio
    async def test_refreshes_every_pool_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pooled session warms every distinct pool provider's credential."""
        refreshed: list = []
        monkeypatch.setattr(CredentialResolver, "require", _require_stub)
        monkeypatch.setattr(
            "src.agents.slo_agent.sessions.service.refresh_if_stale", _record_refresh(refreshed)
        )
        session = _session_with_pool(_openai_anthropic_kfc_dao(), workdir=tmp_path)
        await session._refresh_oauth_credential_if_needed()
        assert set(refreshed) == {
            ProviderName.OPENAI,
            ProviderName.ANTHROPIC,
            ProviderName.KIMI_FOR_CODING,
        }

    @pytest.mark.asyncio
    async def test_single_model_refreshes_one_provider(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A single-model session warms exactly its one provider."""
        refreshed: list = []
        monkeypatch.setattr(CredentialResolver, "require", _require_stub)
        monkeypatch.setattr(
            "src.agents.slo_agent.sessions.service.refresh_if_stale", _record_refresh(refreshed)
        )
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        await session._refresh_oauth_credential_if_needed()
        assert refreshed == [ProviderName.OPENAI]


class TestRoutedModelIdentity:
    def test_usage_snapshot_uses_routed_model(self, tmp_path: Path) -> None:
        """The usage snapshot reports the routed pool member, not the configured name."""
        agent = _injected_pool_agent(active="claude-sonnet-4-6", workdir=tmp_path)
        session = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
            enable_history=False,
        )
        snap = session.refresh_usage_snapshot()
        assert snap.active_model_name == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_persist_routed_model_updates_metadata_on_change(self, tmp_path: Path) -> None:
        """Persisting the routed model rewrites session.json when it differs."""
        agent = _injected_pool_agent(active="claude-sonnet-4-6", workdir=tmp_path)
        store = FilesystemSessionHistoryStore(root=tmp_path)
        session = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=store,
            enable_history=True,
        )
        await session._ensure_history_session()  # writes configured name (gpt-5.4)
        await session._persist_routed_model_if_changed()
        meta = await store.read_metadata(session_id=session.session_id)
        assert meta.model_name == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_persist_routed_model_noop_when_unchanged(self, tmp_path: Path) -> None:
        """When routed == persisted, no metadata rewrite occurs."""
        faux = FauxChatModel(responses=[])
        agent = SloAgent(llm=faux, cwd=str(tmp_path), tools=[])
        store = FilesystemSessionHistoryStore(root=tmp_path)
        session = SloAgentSession(
            agent=agent,
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=store,
            enable_history=True,
        )
        await session._ensure_history_session()  # writes configured name
        before = await store.read_metadata(session_id=session.session_id)
        await session._persist_routed_model_if_changed()  # routed == configured → noop
        after = await store.read_metadata(session_id=session.session_id)
        assert after.model_name == before.model_name
        assert after.updated_at == before.updated_at


# ---------------------------------------------------------------------------
# History-aware preflight + iteration retry policy (37.a.5)
# ---------------------------------------------------------------------------

import time  # noqa: E402

from langchain_core.messages import AIMessage as _AIMessage, HumanMessage as _HumanMessage  # noqa: E402

from src.agents.providers.credit_exhaustion_policy import (  # noqa: E402
    AllModelsExhaustedError as _AllModelsExhaustedError,
)
from src.agents.slo_agent.rate_limit.dao import ModelRateLimitPolicyDAO  # noqa: E402
from src.agents.slo_agent.rate_limit.service import policy_for_model  # noqa: E402


def _policy(*, max_attempts: int) -> ModelRateLimitPolicyDAO:
    """Build a rate policy whose attempt budget equals ``max_attempts``."""
    return ModelRateLimitPolicyDAO(
        model_name="gpt-5.4",
        requests_per_minute=None,
        tokens_per_minute=None,
        automatic_retry_attempts=max_attempts - 1,
        local_retry_wait_cap_seconds=30,
    )


class TestHistoryAwarePreflight:
    def test_large_history_triggers_preflight_wait(self, tmp_path: Path) -> None:
        """A large replayed history injects a preflight wait the prompt-only estimate would not."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        policy = policy_for_model(model_name="gpt-5.4")
        assert policy.tokens_per_minute is not None
        now = time.monotonic()
        # Leave ~9000 tokens of headroom: the prompt-only estimate (~8.2k) fits,
        # the history-aware estimate (~10.2k) does not.
        session._recent_request_token_estimates.append((now, policy.tokens_per_minute - 9000))
        big_history = [_HumanMessage(content="x" * 4000), _AIMessage(content="y" * 4000)]

        wait_without = session._preflight_wait_duration(
            text="hi", message_history=[], policy=policy
        )
        wait_with = session._preflight_wait_duration(
            text="hi", message_history=big_history, policy=policy
        )

        assert wait_without == 0
        assert wait_with > 0


class TestIterationRetryPolicy:
    def test_all_models_exhausted_is_retryable_until_budget(self, tmp_path: Path) -> None:
        """AllModelsExhaustedError is retryable while attempts remain."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        decide = session._build_iteration_retry_policy(policy=_policy(max_attempts=3))
        plan = decide(_AllModelsExhaustedError(cooled_models=["a", "b"]), False, 1)
        assert plan.retryable is True

    def test_budget_spent_is_non_retryable(self, tmp_path: Path) -> None:
        """AllModelsExhaustedError is non-retryable once the budget is spent."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        decide = session._build_iteration_retry_policy(policy=_policy(max_attempts=2))
        plan = decide(_AllModelsExhaustedError(cooled_models=["a", "b"]), False, 2)
        assert plan.retryable is False

    def test_non_rate_limit_error_is_non_retryable(self, tmp_path: Path) -> None:
        """A non-rate-limit error is never retried by the iteration policy."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        decide = session._build_iteration_retry_policy(policy=_policy(max_attempts=3))
        plan = decide(ValueError("bad request"), False, 1)
        assert plan.retryable is False

    def test_rate_limit_error_is_retryable(self, tmp_path: Path) -> None:
        """A rate-limit error is retryable while attempts remain."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        decide = session._build_iteration_retry_policy(policy=_policy(max_attempts=3))
        plan = decide(RuntimeError("429 rate limit reached"), False, 1)
        assert plan.retryable is True


# ---------------------------------------------------------------------------
# Review fixes: pooled /model, routed_model_name, dynamic retry naming
# ---------------------------------------------------------------------------


class TestSwitchModelClearsPool:
    def test_switch_model_on_pooled_session_clears_pool(self, tmp_path: Path) -> None:
        """/model on a pooled session drops to single-model mode with the chosen model."""
        session = _session_with_pool(_two_member_dao(), workdir=tmp_path)
        assert session.model_pool_dao is not None
        session.switch_model(model_name="claude-sonnet-4-6")
        assert session.model_pool_dao is None
        assert session.active_model_name == "claude-sonnet-4-6"
        assert session._agent is None

    def test_switch_model_single_session_stays_single(self, tmp_path: Path) -> None:
        """/model on a single-model session keeps it single-model."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        session.switch_model(model_name="claude-sonnet-4-6")
        assert session.model_pool_dao is None
        assert session.active_model_name == "claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_switch_model_new_name_persists_via_next_turn_mechanism(
        self, tmp_path: Path
    ) -> None:
        """Contract: /model persists the new model on the next turn, not immediately.

        ``switch_model`` is synchronous, so ``session.json`` is updated by the next
        turn's ``_persist_routed_model_if_changed`` (asserted here), per the
        documented contract.
        """
        config = SessionConfigDAO(
            workdir=tmp_path,
            model_name="gpt-5.4",
            enable_history=True,
            history_root=tmp_path,
        )
        session = SloAgentSession.build(config=config)
        await session._ensure_history_session()  # persists configured "gpt-5.4"
        session.switch_model(model_name="claude-sonnet-4-6")
        await session._persist_routed_model_if_changed()  # what the next turn invokes
        store = session.history_store
        assert store is not None
        meta = await store.read_metadata(session_id=session.session_id)
        assert meta.model_name == "claude-sonnet-4-6"


class TestRoutedModelNameProperty:
    def test_routed_model_name_follows_pool(self, tmp_path: Path) -> None:
        """The public routed_model_name reflects the active pool member."""
        agent = _injected_pool_agent(active="claude-sonnet-4-6", workdir=tmp_path)
        session = SloAgentSession(
            agent=agent, workdir=tmp_path, session_id=str(uuid4()), enable_history=False
        )
        assert session.routed_model_name == "claude-sonnet-4-6"

    def test_routed_model_name_single_model_is_configured(self, tmp_path: Path) -> None:
        """For a single-model session it equals the configured name."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        assert session.routed_model_name == "gpt-5.4"


class TestIterationRetryPolicyDynamicName:
    def test_resolves_routed_name_at_decision_time(self, tmp_path: Path) -> None:
        """The same policy callable names whichever member is routed when it fires."""
        dao = ModelPoolDAO(
            entries=[
                ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
                ModelPoolEntryDAO(
                    model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1
                ),
            ]
        )
        pool = ModelPool(
            pool_dao=dao,
            models={"gpt-5.4": FauxChatModel(responses=[]), "claude-sonnet-4-6": FauxChatModel(responses=[])},
        )
        agent = SloAgent(llm=pool, cwd=str(tmp_path), tools=[])
        session = SloAgentSession(
            agent=agent, workdir=tmp_path, session_id=str(uuid4()), enable_history=False
        )
        decide = session._build_iteration_retry_policy(policy=_policy(max_attempts=3))

        plan_primary = decide(RuntimeError("429 rate limit reached"), False, 1)
        assert "gpt-5.4" in plan_primary.message

        # Cool the primary → the routed member becomes the secondary; the SAME
        # policy callable must now name claude (resolved at decision time).
        pool._cooldowns["gpt-5.4"] = time.monotonic() + 60
        plan_secondary = decide(RuntimeError("429 rate limit reached"), False, 1)
        assert "claude-sonnet-4-6" in plan_secondary.message
