"""Tests for ``SloAgentSession`` (sub-spec 02.a.1)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Callable
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from src.agents.base import LLMBuildResult
from src.agents.providers.model_pool import ModelPool, ModelPoolDAO, ModelPoolEntryDAO
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import SessionHistoryMetadataDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.orchestrator.dao import ChildAbortRequestDAO
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.sessions.service import PromptAttemptPlanDAO, SloAgentSession
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.providers.faux import FauxChatModel
from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName
from src.auth.provider_for_model import provider_for_model


def _uses_responses_api(*, llm: object) -> bool | None:
    """Return the optional Responses API flag from an OpenAI-compatible test model.

    Args:
        llm (object): Built model observed by the Astra request-policy contract.

    Returns:
        bool | None: The model's explicit flag when exposed, otherwise None.
    """
    use_responses_api: object = getattr(llm, "use_responses_api", None)
    return use_responses_api if isinstance(use_responses_api, bool) else None


def _omits_astra_sampling_parameters(*, llm: object) -> bool:
    """Check that Astra's built model omits unsupported sampling parameters.

    Args:
        llm (object): Built model observed by the Astra request-policy contract.

    Returns:
        bool: Whether the model exposes mapping-shaped kwargs without sampling keys.
    """
    model_kwargs: object = getattr(llm, "model_kwargs", None)
    if not isinstance(model_kwargs, dict):
        return False
    return all(key not in model_kwargs for key in ("temperature", "top_p", "top_logprobs", "logprobs"))


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


class TestStreamInactivityTimeoutConfig:
    """Configuration helpers for the main stream inactivity timeout."""

    def test_stream_inactivity_timeout_uses_shipped_default_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Absent env var falls back to the shipped 10800-second default."""
        import importlib
        import config.cfg as cfg_module
        import src.agents.slo_agent.sessions.service as session_service_module

        original_session_class = session_service_module.SloAgentSession
        monkeypatch.delenv("SLO_STREAM_INACTIVITY_TIMEOUT_SECONDS", raising=False)
        # Reload configuration only: reloading its consumers replaces class identities
        # still held by headless/TUI imports and invalidates later fixture patches.
        importlib.reload(cfg_module)

        assert session_service_module._stream_inactivity_timeout_seconds() == 10800.0
        assert session_service_module.SloAgentSession is original_session_class

        importlib.reload(cfg_module)


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
    async def test_invoke_yields_reconnect_event_and_retries_once_before_completion(
        self, tmp_path: Path
    ) -> None:
        """A pre-commit typed failure yields one reconnect event and one fresh completion.

        This is a public session-path regression test. Before the fix the reconnect
        audit reached subscribers only, leaving consumers of ``session.invoke``
        unable to observe the retry boundary.
        """
        from src.agents.providers.stream_recovery.dao import (
            ProviderStreamFailure,
            StreamRecoveryAction,
            StreamRecoveryDecisionDAO,
        )

        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="unused")],
        )
        invocation_count: int = 0

        async def _scripted_invoke(**_: object):
            nonlocal invocation_count
            invocation_count += 1
            if invocation_count == 1:
                decision: StreamRecoveryDecisionDAO = StreamRecoveryDecisionDAO(
                    action=StreamRecoveryAction.RETRY_FRESH_CONNECTION,
                    reason_code="provider_stream_disconnected",
                    retry_delay_seconds=0.0,
                    exception_family="httpx.RemoteProtocolError",
                )
                raise ProviderStreamFailure(
                    decision=decision,
                    partial_output_committed=False,
                    attempt_number=1,
                )
            yield AgentStreamEventDAO(kind="run_completed", content="recovered")

        events: list[AgentStreamEventDAO] = []
        with patch.object(session.agent, "invoke", _scripted_invoke):
            async for event in session.invoke(text="recover"):
                events.append(event)

        assert invocation_count == 2
        assert [event.kind for event in events] == ["stream_reconnecting", "run_completed"]

    @pytest.mark.asyncio
    async def test_invoke_continues_after_committed_stream_interruption(self, tmp_path: Path) -> None:
        """A committed stream interruption starts a safe continuation attempt."""
        from src.agents.providers.stream_recovery.dao import (
            ProviderStreamFailure,
            StreamRecoveryAction,
            StreamRecoveryDecisionDAO,
        )

        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="unused")],
        )
        invocation_texts: list[str] = []

        async def _scripted_invoke(*, query: str, **_: object):
            invocation_texts.append(query)
            if len(invocation_texts) == 1:
                decision: StreamRecoveryDecisionDAO = StreamRecoveryDecisionDAO(
                    action=StreamRecoveryAction.DO_NOT_REPLAY,
                    reason_code="provider_stream_interrupted",
                    exception_family="httpx.ReadTimeout",
                )
                raise ProviderStreamFailure(
                    decision=decision,
                    partial_output_committed=True,
                    attempt_number=1,
                )
            yield AgentStreamEventDAO(kind="run_completed", content="recovered")

        events: list[AgentStreamEventDAO] = []
        with patch.object(session.agent, "invoke", _scripted_invoke):
            async for event in session.invoke(text="finish the task"):
                events.append(event)

        assert [event.kind for event in events] == ["run_retrying", "run_completed"]
        assert invocation_texts[0] == "finish the task"
        assert "Continuation attempt 2/5." in invocation_texts[1]
        assert "finish the task" in invocation_texts[1]
        assert "httpx.ReadTimeout" not in invocation_texts[1]

    @pytest.mark.asyncio
    async def test_invoke_stops_after_five_committed_stream_interruptions(self, tmp_path: Path) -> None:
        """A stream continuation cannot start a sixth submission attempt."""
        from src.agents.providers.stream_recovery.dao import (
            ProviderStreamFailure,
            StreamRecoveryAction,
            StreamRecoveryDecisionDAO,
        )

        session: SloAgentSession = _build_faux_session(
            workdir=tmp_path,
            responses=[FauxChatModel.assistant_message(content="unused")],
        )
        invocation_count: int = 0

        async def _always_interrupt(*, query: str, **_: object):
            nonlocal invocation_count
            invocation_count += 1
            decision: StreamRecoveryDecisionDAO = StreamRecoveryDecisionDAO(
                action=StreamRecoveryAction.DO_NOT_REPLAY,
                reason_code="provider_stream_interrupted",
                exception_family="httpx.ReadTimeout",
            )
            raise ProviderStreamFailure(
                decision=decision,
                partial_output_committed=True,
                attempt_number=1,
            )
            yield AgentStreamEventDAO(kind="run_completed", content=query)

        events: list[AgentStreamEventDAO] = []
        with patch.object(session.agent, "invoke", _always_interrupt):
            with pytest.raises(ProviderStreamFailure):
                async for event in session.invoke(text="finish the task"):
                    events.append(event)

        assert invocation_count == 5
        assert [event.kind for event in events] == [
            "run_retrying",
            "run_retrying",
            "run_retrying",
            "run_retrying",
        ]

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

        def _allocate_turn_id() -> str:
            """Record turn allocation before returning the deterministic test id."""
            order.append("allocate_turn")
            return "turn-123"

        with (
            patch.object(
                session,
                "_allocate_turn_id",
                side_effect=_allocate_turn_id,
            ),
            patch.object(
                session, "_ensure_history_session", new=AsyncMock(side_effect=_ensure_history_session)
            ),
            patch.object(session, "_ensure_agent_ready", new=AsyncMock(side_effect=_ensure_agent_ready)),
            patch.object(
                session, "_preflight_compaction_if_dirty", new=AsyncMock(side_effect=_preflight_compaction)
            ),
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
        original_history_store = original_session.history_store
        assert original_history_store is not None
        persisted_metadata: SessionHistoryMetadataDAO = await original_history_store.read_metadata(
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

    def test_build_seeds_k3_profile_default_when_no_override_exists(self, tmp_path: Path) -> None:
        """K3's lazy session state defaults to xhigh without constructing a provider model."""
        config: SessionConfigDAO = SessionConfigDAO(
            workdir=tmp_path,
            model_name="kimi-k3",
        )

        with patch("src.agents.slo_agent.sessions.service.SloAgent") as mock_agent_cls:
            session: SloAgentSession = SloAgentSession.build(config=config)

        assert session.active_reasoning_level == "xhigh"
        assert session._agent is None
        mock_agent_cls.assert_not_called()

    def test_switch_model_updates_active_model_and_clears_lazy_agent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Switching models invalidates the cached lazy-built agent."""
        # cfg resolves the short key dynamically; the ambient SLO_DEFAULT_MODEL_NAME
        # is captured at config.cfg import, before this test's patch.
        monkeypatch.setenv("DEFAULT_MODEL_NAME", "gpt-5.4")
        monkeypatch.setattr(
            "src.agents.slo_agent.sessions.service.CredentialResolver.require",
            lambda *, provider: CredentialDAO(
                provider=provider, auth_type=AuthType.API_KEY, access_token="fixture"
            ),
        )
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

    def test_switch_model_marks_context_window_dirty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Switching models flags a pre-flight compaction check for the next turn."""
        # cfg resolves the short key dynamically; the ambient SLO_DEFAULT_MODEL_NAME
        # is captured at config.cfg import, before this test's patch.
        monkeypatch.setenv("DEFAULT_MODEL_NAME", "gpt-5.4")
        monkeypatch.setattr(
            "src.agents.slo_agent.sessions.service.CredentialResolver.require",
            lambda *, provider: CredentialDAO(
                provider=provider, auth_type=AuthType.API_KEY, access_token="fixture"
            ),
        )
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
    async def test_invoke_refreshes_stale_openai_oauth_before_lazy_build(self, tmp_path: Path) -> None:
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
        llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="ok")]),
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

    async def test_event_relay_accepts_positional_call(self, tmp_path: Path) -> None:
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

    async def test_event_relay_sub_agent_event_roundtrip(self, tmp_path: Path) -> None:
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


class TestSloAgentSessionAttachedDispatchSnapshot:
    """``attached_dispatch_snapshot`` observation facade (feature 94 a.2)."""

    def test_session_without_pool_returns_explicit_empty_value(self, tmp_path: Path) -> None:
        """No attached pool means no dispatch, never a lookup of private fields."""
        from src.agents.slo_agent.orchestrator.dao import AttachedDispatchSnapshotDAO

        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path, session_id="s1", agent=_build_faux_agent(tmp_path), enable_history=False
        )

        assert session.attached_dispatch_snapshot() == AttachedDispatchSnapshotDAO.empty()

    async def test_attached_pool_latest_batch_is_returned_through_the_session(self, tmp_path: Path) -> None:
        """A real pool dispatched through the session relay exposes only its latest batch."""
        from langchain_core.tools import BaseTool

        from src.agents.slo_agent.orchestrator.dao import SubAgentResultDAO, SubAgentTaskDAO
        from src.agents.slo_agent.orchestrator.pool import SubAgentPool
        from src.agents.slo_agent.orchestrator.process import SubAgentProcess

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
        )
        pool = SubAgentPool(
            orchestrator_session_id="orch-1",
            default_model=None,
            relay=session.event_relay,
            owner_session_id="orch-1",
            run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
            history_root=tmp_path / "history",
        )
        tool: MagicMock = MagicMock(spec=BaseTool)
        tool.name = "spawn_sub_agents"
        session.attach_sub_agent_pool(pool=pool, spawn_tool=tool)
        received: list[AgentStreamEventDAO] = []

        async def collect(event: AgentStreamEventDAO) -> None:
            received.append(event)

        session.subscribe(handler=collect)

        async def finish(process: SubAgentProcess) -> SubAgentResultDAO:
            return process._publish_terminal(
                candidate=SubAgentResultDAO(
                    task_id=process.task.task_id,
                    session_id=process.session_id,
                    status="completed",
                    exit_code=0,
                    execution_id=process.execution_id,
                ),
                terminal_reason="completed",
                terminated_by="natural",
            )

        with patch.object(SubAgentProcess, "run", new=finish):
            await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Verify session child delegation",
                        task_id="t1",
                        prompt="x",
                        session_id="a",
                    )
                ],
            )
            await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Verify session child delegation",
                        task_id="t2",
                        prompt="y",
                        session_id="b",
                    )
                ],
            )

        snapshot = session.attached_dispatch_snapshot()
        assert snapshot == pool.attached_dispatch_snapshot()
        assert (snapshot.dispatch_sequence, [e.session_id for e in snapshot.entries]) == (2, ["b"])
        assert [event.kind for event in received][0] == "sub_agent_dispatch_started"


class TestSloAgentSessionChildAbortFacade:
    """``abort_child`` / ``child_control_capability`` facade (feature 94 a.4, T09)."""

    _RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"

    def _request(self, *, owner: str) -> ChildAbortRequestDAO:
        return ChildAbortRequestDAO(
            request_id="c3b2a190-8e7d-4c6b-9a58-473625140f0e",
            owner_session_id=owner,
            orchestrator_session_id="orch-1",
            session_id="child-1",
            run_id=self._RUN_ID,
            execution_id="0f9a4c1e-6a1b-4f5e-9d3c-2b7a8e6f1c40",
        )

    def _attached_session(self, tmp_path: Path) -> tuple[SloAgentSession, SubAgentPool]:
        from langchain_core.tools import BaseTool

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False)
        )
        pool = SubAgentPool(
            orchestrator_session_id="orch-1",
            default_model=None,
            relay=session.event_relay,
            owner_session_id="orch-1",
            run_id=self._RUN_ID,
            history_root=tmp_path / "history",
        )
        tool: MagicMock = MagicMock(spec=BaseTool)
        tool.name = "spawn_sub_agents"
        session.attach_sub_agent_pool(pool=pool, spawn_tool=tool)
        return session, pool

    async def test_session_without_pool_returns_unavailable_and_no_capability(self, tmp_path: Path) -> None:
        """No attached pool: a fixed unavailable outcome for the exact request, no capability."""
        session: SloAgentSession = SloAgentSession(
            workdir=tmp_path, session_id="s1", agent=_build_faux_agent(tmp_path), enable_history=False
        )
        request = self._request(owner="s1")

        outcome = await session.abort_child(request=request)

        assert (outcome.outcome, outcome.request_id, outcome.execution_id) == (
            "unavailable",
            request.request_id,
            request.execution_id,
        )
        assert outcome.safe_message == "Child abort unavailable for this run."
        assert session.child_control_capability() is None

    async def test_attached_pool_receives_the_request_through_the_session(self, tmp_path: Path) -> None:
        """The facade delegates to the real pool, which applies its own validation."""
        session, pool = self._attached_session(tmp_path)

        outcome = await session.abort_child(request=self._request(owner="orch-1"))

        assert outcome.outcome == "not_owned"  # unknown child: the pool, not the facade, decided
        assert pool.registry.count == 0

    def test_no_history_attached_capability_is_valid_without_files(self, tmp_path: Path) -> None:
        """A no-history attached session exposes the pool capability; no control files exist."""
        session, pool = self._attached_session(tmp_path)

        capability = session.child_control_capability()

        assert capability == pool.child_control_capability()
        assert capability is not None and capability.accepting is True
        assert capability.run_id == self._RUN_ID
        assert not (tmp_path / "history").exists()


class TestSloAgentSessionAttachSubAgentPool:
    """``attach_sub_agent_pool()`` promotion seam (sub-spec 03.a)."""

    def test_attach_pool_merges_spawn_tool_into_extra_tools(self, tmp_path: Path) -> None:
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

        config = session._config
        assert config is not None
        assert config.extra_tools is not None
        tool_names: list[str] = [tool.name for tool in config.extra_tools]
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

        config = session._config
        assert config is not None
        assert config.append_system_prompt is not None
        assert "spawn_sub_agents" in config.append_system_prompt

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

    def test_attach_pool_accepts_tool_list(self, tmp_path: Path) -> None:
        """``spawn_tools`` merges every supplied tool into ``extra_tools`` (spec 57.a.2)."""
        from unittest.mock import MagicMock
        from langchain_core.tools import BaseTool

        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )
        spawn_tool: MagicMock = MagicMock(spec=BaseTool)
        spawn_tool.name = "spawn_sub_agents"
        launch_tool: MagicMock = MagicMock(spec=BaseTool)
        launch_tool.name = "launch_workflow"
        status_tool: MagicMock = MagicMock(spec=BaseTool)
        status_tool.name = "workflow_status"

        session.attach_sub_agent_pool(
            pool=_build_pool_mock(),
            spawn_tools=[spawn_tool, launch_tool, status_tool],
        )

        assert session._config is not None
        assert session._config.extra_tools is not None
        tool_names: list[str] = [t.name for t in session._config.extra_tools]
        assert tool_names[-3:] == ["spawn_sub_agents", "launch_workflow", "workflow_status"]

    def test_attach_pool_requires_at_least_one_tool(self, tmp_path: Path) -> None:
        """Neither ``spawn_tool`` nor ``spawn_tools`` supplied raises ``ValueError``."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-5.4",
                enable_history=False,
            )
        )

        with pytest.raises(ValueError, match="at least one tool"):
            session.attach_sub_agent_pool(pool=_build_pool_mock())

    def test_attach_pool_raises_when_agent_already_built(self, tmp_path: Path) -> None:
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

    async def test_abort_calls_pool_abort_and_drain_when_pool_attached(self, tmp_path: Path) -> None:
        """``abort()`` schedules ``pool.abort_and_drain()`` when a pool is attached."""
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
        pool.abort_and_drain = AsyncMock()
        mock_tool: MagicMock = MagicMock(spec=BaseTool)
        mock_tool.name = "spawn_sub_agents"
        session.attach_sub_agent_pool(pool=pool, spawn_tool=mock_tool)

        session.abort()
        await asyncio.sleep(0)

        pool.abort_and_drain.assert_awaited_once()

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
            ModelPoolEntryDAO(model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1),
        ]
    )


def _openai_anthropic_kfc_dao() -> ModelPoolDAO:
    """Build a three-provider pool DAO."""
    return ModelPoolDAO(
        entries=[
            ModelPoolEntryDAO(model_name="gpt-5.4", provider=ProviderName.OPENAI, priority=0),
            ModelPoolEntryDAO(model_name="claude-sonnet-4-6", provider=ProviderName.ANTHROPIC, priority=1),
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
            ModelPoolEntryDAO(model_name=active, provider=provider_for_model(model_name=active), priority=0),
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
    def test_build_agent_passes_pool_dao(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """_build_agent threads config.model_pool_dao into the SloAgent constructor."""
        captured: dict = {}
        monkeypatch.setattr("src.agents.slo_agent.sessions.service.SloAgent", _capturing_agent(captured))
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
        monkeypatch.setattr("src.agents.slo_agent.sessions.service.SloAgent", _capturing_agent(captured))
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
    def test_large_history_does_not_turn_advisory_tpm_hint_into_wait(self, tmp_path: Path) -> None:
        """History can enlarge the estimate, but a nonempty TPM window never gates the provider lane."""
        session = _single_model_session("gpt-5.4", workdir=tmp_path)
        policy = policy_for_model(model_name="gpt-5.4")
        assert policy.tokens_per_minute is not None
        now = time.monotonic()
        session._recent_request_token_estimates.append((now, policy.tokens_per_minute - 9000))
        big_history = [_HumanMessage(content="x" * 4000), _AIMessage(content="y" * 4000)]

        decision_without = session._build_preflight_decision(
            text="hi",
            message_history=[],
            policy=policy,
        )
        decision_with = session._build_preflight_decision(
            text="hi",
            message_history=big_history,
            policy=policy,
        )

        assert decision_with.estimated_tokens > decision_without.estimated_tokens
        assert decision_without.wait_seconds == 0
        assert decision_with.wait_seconds == 0


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
    """Pool-clearing ``switch_model`` paths.

    Every case switches to ``claude-sonnet-4-6``; ``switch_model`` validates the
    selection credential through ``CredentialResolver.require``. The ambient
    environment may not carry Anthropic credentials, so each test pins the
    default model and stubs the Anthropic selection credential.
    """

    @pytest.fixture(autouse=True)
    def _pin_default_and_anthropic_credential(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pin the global default and stub Anthropic selection credentials.

        cfg resolves the short key dynamically; the ambient SLO_DEFAULT_MODEL_NAME
        is captured at config.cfg import, before this fixture's patch.
        """
        monkeypatch.setenv("DEFAULT_MODEL_NAME", "gpt-5.4")
        monkeypatch.setattr(
            "src.agents.slo_agent.sessions.service.CredentialResolver.require",
            lambda *, provider: CredentialDAO(
                provider=provider, auth_type=AuthType.API_KEY, access_token="fixture"
            ),
        )

    def test_switch_model_when_reasoning_clamp_fails_preserves_existing_state(self, tmp_path: Path) -> None:
        """A failed synchronous selection derives values before mutating session state."""
        session = _session_with_pool(_two_member_dao(), workdir=tmp_path)
        before_config = session._config
        before_model: str = session.active_model_name
        before_pool = session.model_pool_dao
        before_agent = session._agent
        before_usage = session.usage_snapshot()

        with patch(
            "src.agents.slo_agent.sessions.service.clamp_reasoning_level",
            side_effect=ValueError("unsupported reasoning"),
        ):
            with pytest.raises(ValueError, match="unsupported reasoning"):
                session.switch_model(model_name="claude-sonnet-4-6")

        assert session._config is before_config
        assert session.active_model_name == before_model
        assert session.model_pool_dao is before_pool
        assert session._agent is before_agent
        assert session.usage_snapshot() == before_usage

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
    async def test_switch_model_new_name_persists_via_next_turn_mechanism(self, tmp_path: Path) -> None:
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


class TestRecordWorkflowUpdate:
    """``record_workflow_update`` persists synthetic completed turns (spec 57.a.4)."""

    @staticmethod
    def _build_history_session(*, tmp_path: Path, session_id: str | None = None) -> SloAgentSession:
        """Build a history-backed lazy session rooted under ``tmp_path``.

        Args:
            tmp_path (Path): Test-scoped directory for the history root.
            session_id (str | None): Optional fixed session id for resume tests.

        Returns:
            SloAgentSession: Session with history enabled on a tmp root.
        """
        return SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                history_root=tmp_path / "history",
                session_id=session_id,
            )
        )

    @pytest.mark.asyncio
    async def test_record_workflow_update_appends_synthetic_completed_turn(self, tmp_path: Path) -> None:
        """One workflow note becomes one terminal-by-construction one-event turn."""
        session: SloAgentSession = self._build_history_session(tmp_path=tmp_path)

        persisted: bool = await session.record_workflow_update(
            text="[workflow wf-3f2a] phase 1: 2 task(s), all_completed=True",
            message_id="msg-1",
            workflow_id="wf-3f2a",
        )

        assert persisted is True
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        workflow_events = [event for event in events if event.kind == "workflow_update"]
        assert len(workflow_events) == 1
        event = workflow_events[0]
        assert event.turn_id is not None
        assert event.payload.content == "[workflow wf-3f2a] phase 1: 2 task(s), all_completed=True"
        assert event.payload.metadata["workflow_id"] == "wf-3f2a"
        assert event.payload.metadata["inbox_message_id"] == "msg-1"
        # The synthetic turn contains exactly this one event — no run envelope.
        same_turn_events = [e for e in events if e.turn_id == event.turn_id]
        assert same_turn_events == [event]

    @pytest.mark.asyncio
    async def test_record_workflow_update_is_idempotent_on_message_id(self, tmp_path: Path) -> None:
        """A re-claimed inbox message persists at most one event."""
        session: SloAgentSession = self._build_history_session(tmp_path=tmp_path)

        first: bool = await session.record_workflow_update(
            text="phase 1 done", message_id="msg-1", workflow_id="wf-3f2a"
        )
        second: bool = await session.record_workflow_update(
            text="phase 1 done", message_id="msg-1", workflow_id="wf-3f2a"
        )

        assert first is True
        assert second is False
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        assert len([event for event in events if event.kind == "workflow_update"]) == 1

    @pytest.mark.asyncio
    async def test_record_workflow_update_idempotency_survives_reload(self, tmp_path: Path) -> None:
        """The seen-set reseeds from disk after a simulated TUI restart."""
        session: SloAgentSession = self._build_history_session(tmp_path=tmp_path)
        await session.record_workflow_update(text="phase 1 done", message_id="msg-1", workflow_id="wf-3f2a")

        resumed: SloAgentSession = self._build_history_session(
            tmp_path=tmp_path,
            session_id=session.session_id,
        )
        duplicate: bool = await resumed.record_workflow_update(
            text="phase 1 done", message_id="msg-1", workflow_id="wf-3f2a"
        )

        assert duplicate is False
        assert resumed.history_store is not None
        events = await resumed.history_store.load_events(session_id=resumed.session_id)
        assert len([event for event in events if event.kind == "workflow_update"]) == 1

    @pytest.mark.asyncio
    async def test_record_workflow_update_history_disabled_noop(self, tmp_path: Path) -> None:
        """History-disabled sessions skip persistence and return ``False``."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                enable_history=False,
            )
        )

        persisted: bool = await session.record_workflow_update(
            text="phase 1 done", message_id="msg-1", workflow_id="wf-3f2a"
        )

        assert persisted is False

    @pytest.mark.asyncio
    async def test_resume_context_equals_live_context(self, tmp_path: Path) -> None:
        """A reloaded session projects the same message history as the live one."""
        session: SloAgentSession = self._build_history_session(tmp_path=tmp_path)
        await session.record_workflow_update(text="phase 1 done", message_id="msg-1", workflow_id="wf-3f2a")
        await session.record_workflow_update(text="phase 2 done", message_id="msg-2", workflow_id="wf-3f2a")
        live_history = await session._load_message_history()

        resumed: SloAgentSession = self._build_history_session(
            tmp_path=tmp_path,
            session_id=session.session_id,
        )
        resumed_history = await resumed._load_message_history()

        assert [message.content for message in resumed_history] == [
            message.content for message in live_history
        ]
        assert [message.content for message in live_history] == [
            "[workflow update] phase 1 done",
            "[workflow update] phase 2 done",
        ]


class TestAstraSessionReasoningState:
    """Feature 83.a.1: Astra sessions seed, persist, and switch canonical levels."""

    @pytest.fixture(autouse=True)
    def authenticated_selection(self, isolated_slo_home: Path) -> None:
        """Supply real contained auth now required by synchronous model selection."""
        from src.auth.credential_store import CredentialStore
        from src.auth.credential_dao import AuthType, CredentialDAO, ProviderName

        store = CredentialStore()
        assert store.path.resolve().is_relative_to(isolated_slo_home.resolve())
        store.persist(
            cred=CredentialDAO(
                provider=ProviderName.OPENAI,
                auth_type=AuthType.API_KEY,
                access_token="fixture-astra-selection",
            )
        )

    def test_astra_session_seeds_high_reasoning_default(self, tmp_path: Path) -> None:
        """An Astra session with no override seeds to ``high``."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-6-astra",
                enable_history=False,
            )
        )

        assert session.active_model_name == "gpt-6-astra"
        assert session.active_reasoning_level == "high"

    def test_astra_session_switch_reasoning_to_off_preserves_off_state(self, tmp_path: Path) -> None:
        """Switching to ``off`` keeps canonical off state (never rewritten to low)."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-6-astra",
                enable_history=False,
            )
        )

        active_level = session.switch_reasoning_level(reasoning_level="off")

        assert active_level == "off"
        assert session.active_reasoning_level == "off"

    def test_astra_session_switch_reasoning_to_max_selects_max(self, tmp_path: Path) -> None:
        """Switching to canonical ``max`` selects ``max`` unchanged for Astra."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-6-astra",
                enable_history=False,
            )
        )

        active_level = session.switch_reasoning_level(reasoning_level="max")

        assert active_level == "max"
        assert session.active_reasoning_level == "max"

    def test_astra_off_state_survives_model_switch_away_and_back(self, tmp_path: Path) -> None:
        """Switching away from Astra clamps per the new model; returning keeps off."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-6-astra",
                reasoning_level="off",
                enable_history=False,
            )
        )

        session.switch_model(model_name="gpt-4.1")
        assert session.active_reasoning_level == "off"

        session.switch_model(model_name="gpt-6-astra")
        assert session.active_reasoning_level == "off"

    def test_max_reasoning_reclamps_when_switching_to_legacy_model(self, tmp_path: Path) -> None:
        """Astra ``max`` clamps to the legacy highest level on a model switch."""
        session: SloAgentSession = SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-6-astra",
                reasoning_level="max",
                enable_history=False,
            )
        )

        session.switch_model(model_name="gpt-5.4")

        assert session.active_reasoning_level == "xhigh"


class TestAstraBoundedSessionContracts:
    """Feature 83.c.1: Astra-configured sessions preserve policy through recovery."""

    @staticmethod
    def _forbid_discovery() -> MagicMock:
        """Patch catalog discovery to fail loudly if invoked.

        Returns:
            MagicMock: The failing refresh stand-in for call assertions.
        """
        return MagicMock(side_effect=AssertionError("discovery forbidden"))

    @staticmethod
    def _build_astra_session(tmp_path: Path) -> SloAgentSession:
        """Build a lazy Astra-configured session with no history.

        Args:
            tmp_path (Path): Test workdir.

        Returns:
            SloAgentSession: Config-driven session; the agent is built lazily.
        """
        return SloAgentSession.build(
            config=SessionConfigDAO(
                workdir=tmp_path,
                model_name="gpt-6-astra",
                reasoning_level="high",
                enable_history=False,
            )
        )

    @staticmethod
    def _api_key_credential() -> CredentialDAO:
        """Build a fake OpenAI API-key credential.

        Returns:
            CredentialDAO: API-key credential; never a real token.
        """
        return CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.API_KEY,
            access_token="sk-fake-test-only",
        )

    @staticmethod
    def _observing_build_agent(
        *,
        session: SloAgentSession,
        captured: list[tuple[str, str, str, str | None, bool | None, bool]],
    ) -> Callable[[], SloAgent]:
        """Wrap ``session._build_agent`` to record the stable attempt tuple.

        Replaces the real LLM with a ``FauxChatModel`` after the real build so
        the lazy seam runs exactly once and no network is touched.

        Args:
            session (SloAgentSession): Session whose lazy build is observed.
            captured (list[tuple[str, str, str, str | None, bool | None, bool]]):
                Sink for one tuple per policy observation.

        Returns:
            callable: The observing ``_build_agent`` replacement.
        """
        from src.agents.reasoning_capabilities import resolve_reasoning_config

        real_build_agent = session._build_agent

        def _observing_build_agent() -> SloAgent:
            agent: SloAgent = real_build_agent()
            llm = agent.llm
            assert llm is not None
            resolved = resolve_reasoning_config(
                model_name=session.active_model_name,
                requested_level=session.active_reasoning_level,
            )
            captured.append(
                (
                    session.active_model_name,
                    "api_key",
                    resolved.active_level,
                    resolved.provider_effort,
                    _uses_responses_api(llm=llm),
                    _omits_astra_sampling_parameters(llm=llm),
                )
            )
            agent._llm = FauxChatModel(responses=[])
            return agent

        return _observing_build_agent

    @pytest.mark.asyncio
    async def test_astra_pre_commit_disconnect_reconnects_once_with_unchanged_policy(
        self, tmp_path: Path
    ) -> None:
        """A typed pre-commit disconnect reconnects once with an unchanged policy tuple."""
        from src.agents.providers.stream_recovery.dao import (
            ProviderStreamFailure,
            StreamRecoveryAction,
            StreamRecoveryDecisionDAO,
        )

        captured: list[tuple[str, str, str, str | None, bool | None, bool]] = []
        session: SloAgentSession = self._build_astra_session(tmp_path=tmp_path)
        invocation_count: int = 0

        async def _scripted_invoke(**_: object):
            nonlocal invocation_count
            invocation_count += 1
            if invocation_count == 1:
                raise ProviderStreamFailure(
                    decision=StreamRecoveryDecisionDAO(
                        action=StreamRecoveryAction.RETRY_FRESH_CONNECTION,
                        reason_code="provider_stream_disconnected",
                        retry_delay_seconds=0.0,
                        exception_family="httpx.RemoteProtocolError",
                    ),
                    partial_output_committed=False,
                    attempt_number=1,
                )
            yield AgentStreamEventDAO(kind="run_completed", content="recovered")

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=self._api_key_credential(),
            ),
            patch.object(
                session,
                "_build_agent",
                self._observing_build_agent(session=session, captured=captured),
            ),
            patch(
                "src.agents.model_catalog.discovery.ProviderModelDiscoveryService.refresh",
                self._forbid_discovery(),
            ) as mock_refresh,
        ):
            await session._ensure_agent_ready()
            with patch.object(session.agent, "invoke", _scripted_invoke):
                events: list[AgentStreamEventDAO] = []
                async for event in session.invoke(text="recover"):
                    events.append(event)

        assert invocation_count == 2
        assert [event.kind for event in events] == ["stream_reconnecting", "run_completed"]
        expected_tuple = ("gpt-6-astra", "api_key", "high", "high", True, True)
        assert captured == [expected_tuple]
        assert [
            (
                session.active_model_name,
                "api_key",
                session.active_reasoning_level,
                "high",
                True,
                True,
            )
            for _ in range(invocation_count)
        ] == [expected_tuple, expected_tuple]
        mock_refresh.assert_not_called()
        assert session.active_model_name == "gpt-6-astra"
        assert session.active_reasoning_level == "high"
        assert session.is_running is False

    @pytest.mark.asyncio
    async def test_astra_committed_disconnect_uses_existing_continuation_without_raw_replay(
        self, tmp_path: Path
    ) -> None:
        """A committed disconnect continues once without replaying raw transport text."""
        from src.agents.providers.stream_recovery.dao import (
            ProviderStreamFailure,
            StreamRecoveryAction,
            StreamRecoveryDecisionDAO,
        )

        captured: list[tuple[str, str, str, str | None, bool | None, bool]] = []
        session: SloAgentSession = self._build_astra_session(tmp_path=tmp_path)
        invocation_texts: list[str] = []

        async def _scripted_invoke(*, query: str, **_: object):
            invocation_texts.append(query)
            if len(invocation_texts) == 1:
                yield AgentStreamEventDAO(kind="text_delta", delta="partial", iteration=0)
                raise ProviderStreamFailure(
                    decision=StreamRecoveryDecisionDAO(
                        action=StreamRecoveryAction.DO_NOT_REPLAY,
                        reason_code="provider_stream_interrupted",
                        exception_family="httpx.ReadTimeout",
                    ),
                    partial_output_committed=True,
                    attempt_number=1,
                )
            yield AgentStreamEventDAO(kind="run_completed", content="recovered")

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=self._api_key_credential(),
            ),
            patch.object(
                session,
                "_build_agent",
                self._observing_build_agent(session=session, captured=captured),
            ),
            patch(
                "src.agents.model_catalog.discovery.ProviderModelDiscoveryService.refresh",
                self._forbid_discovery(),
            ) as mock_refresh,
        ):
            await session._ensure_agent_ready()
            with patch.object(session.agent, "invoke", _scripted_invoke):
                events: list[AgentStreamEventDAO] = []
                async for event in session.invoke(text="finish the task"):
                    events.append(event)

        assert [event.kind for event in events] == [
            "text_delta",
            "run_retrying",
            "run_completed",
        ]
        assert invocation_texts[0] == "finish the task"
        assert len(invocation_texts) == 2
        assert "Continuation attempt 2/5." in invocation_texts[1]
        assert "finish the task" in invocation_texts[1]
        assert "httpx.ReadTimeout" not in invocation_texts[1]
        expected_tuple = ("gpt-6-astra", "api_key", "high", "high", True, True)
        assert captured == [expected_tuple]
        assert [
            (
                session.active_model_name,
                "api_key",
                session.active_reasoning_level,
                "high",
                True,
                True,
            )
            for _ in invocation_texts
        ] == [expected_tuple, expected_tuple]
        mock_refresh.assert_not_called()
        assert session.is_running is False

    @pytest.mark.asyncio
    async def test_astra_oauth_4xx_is_terminal_without_discovery_or_api_key_fallback(
        self, tmp_path: Path
    ) -> None:
        """A representative OAuth-classified OTHER error terminates once with no fallback."""
        session: SloAgentSession = self._build_astra_session(tmp_path=tmp_path)
        oauth_cred: CredentialDAO = CredentialDAO(
            provider=ProviderName.OPENAI,
            auth_type=AuthType.OAUTH,
            access_token="fake-oauth-token-test-only",
        )

        with (
            patch(
                "src.agents.base.CredentialResolver.require",
                return_value=oauth_cred,
            ) as mock_require,
            patch(
                "src.agents.base.build_chatgpt_backed_chat_openai",
                side_effect=ValueError("Error code: 403 - unsupported model for this credential"),
            ) as mock_oauth_builder,
            patch(
                "src.agents.base.ChatOpenAI",
            ) as mock_api_key_constructor,
            patch(
                "src.agents.model_catalog.discovery.ProviderModelDiscoveryService.refresh",
                self._forbid_discovery(),
            ) as mock_refresh,
        ):
            events: list[AgentStreamEventDAO] = []
            with pytest.raises(ValueError, match="unsupported model"):
                async for event in session.invoke(text="hello"):
                    events.append(event)

        assert [event.kind for event in events] == []
        # Local eligibility precheck, OAuth warm and factory build each resolve
        # their own credential; the API-key constructor never runs.
        assert mock_require.call_count == 3
        assert all(call.kwargs["provider"] is ProviderName.OPENAI for call in mock_require.call_args_list)
        mock_oauth_builder.assert_called_once()
        mock_api_key_constructor.assert_not_called()
        mock_refresh.assert_not_called()
        assert session.is_running is False

        session._agent = SloAgent(llm=FauxChatModel(responses=[]), cwd=str(tmp_path))
        follow_up_events: list[AgentStreamEventDAO] = []

        async def _completing_invoke(**_: object):
            yield AgentStreamEventDAO(kind="run_completed", content="follow-up ok")

        with patch.object(session.agent, "invoke", _completing_invoke):
            async for event in session.invoke(text="next action"):
                follow_up_events.append(event)

        assert [event.kind for event in follow_up_events] == ["run_completed"]
