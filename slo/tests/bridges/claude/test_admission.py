"""Real session admission with synthetic native authentication only."""

import asyncio
from pathlib import Path
from typing import Self

import pytest

from src.agents.tools.bundles import create_local_tools
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.history.dao import SessionHistoryEventDAO, SessionHistoryEventPayloadDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.cli.test_claude_bridge import scripted_adapter_class
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter
from src.bridges.claude.sdk.dao import ClaudeAuthenticationStatusDAO, ClaudeBridgeConfigurationDAO
from tests.bridges.claude.test_lifecycle import ready_status
from tests.cli.test_claude_bridge import ScriptedClaudeTransport

LOCAL_TOOL_NAMES: tuple[str, ...] = tuple(tool.name for tool in create_local_tools())


async def test_close_during_native_startup_cannot_publish_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Session closure owns a candidate even while its native authentication is blocked."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    entered = asyncio.Event()
    finished = asyncio.Event()

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Expose the native auth lifetime without native activity."""
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            finished.set()
        return ClaudeAuthenticationStatusDAO(state="ready", safe_message="ready")

    class BlockedAdapter(SloClaudeBridgeAdapter):
        """Use real adapter cancellation and candidate ownership."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Register the blocked external status dependency."""
            return cls(configuration=configuration, authentication_check=status)

    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-bridge:claude-haiku-5-5"),
        bridge_adapter_class=BlockedAdapter,
    )
    startup = asyncio.create_task(coro=session.prepare_startup())
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            await session.close_agent_resources()
            assert finished.is_set()
            outcomes = await asyncio.gather(startup, return_exceptions=True)
        assert isinstance(outcomes[0], (asyncio.CancelledError, RuntimeError))
        assert session.preparation_status != "ready"
    finally:
        startup.cancel()
        await asyncio.gather(startup, return_exceptions=True)
        await session.close_agent_resources()


async def test_failed_automatic_pool_drain_cannot_adopt_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed retained drain blocks selection and never drops standard capability ownership."""
    from src.agents.slo_agent.orchestrator.bootstrap import OrchestratorSessionBootstrap
    from src.agents.slo_agent.orchestrator.pool import SubAgentPool

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )

    class FailedDrainPool(SubAgentPool):
        """Inject one failed capability boundary through standard bootstrap construction."""

        async def abort_and_drain(self) -> None:
            """Report failed drainage, never a successful retirement."""
            raise RuntimeError("synthetic drain failure")

    class FailedDrainBootstrap(OrchestratorSessionBootstrap):
        """Use canonical standard attachment with an injected pool implementation."""

        @classmethod
        def _build_pool(cls, *, session: SloAgentSession, owner_session_id: str) -> SubAgentPool:
            """Construct the fail-on-drain capability using the normal pool contract."""
            return FailedDrainPool(
                orchestrator_session_id=session.session_id,
                default_model=session.active_model_name,
                relay=session.event_relay,
                owner_session_id=owner_session_id,
                run_id="synthetic",
                history_root=tmp_path / "history",
            )

    FailedDrainBootstrap.attach(session=session)
    tools = session.orchestration_tools
    try:
        with pytest.raises(RuntimeError, match="drain|cleanup"):
            await session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
        assert session.active_model_name == "gpt-5.4"
        assert session.orchestration_tools == tools
        assert not transport.connected
    finally:
        await session.close_agent_resources()


async def test_selection_reserves_admission_before_awaited_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent prompt cannot mutate history while a model transition owns admission."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    entered = asyncio.Event()
    release = asyncio.Event()

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Hold selection while a competing prompt tries admission."""
        entered.set()
        await release.wait()
        return ClaudeAuthenticationStatusDAO(state="ready", safe_message="ready")

    class SelectionAdapter(SloClaudeBridgeAdapter):
        """Keep real internal owners and replace only status observation."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Register the external status barrier."""
            return cls(configuration=configuration, authentication_check=status)

    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    session = SloAgentSession(
        workdir=tmp_path,
        session_id="selection",
        history_store=store,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
        bridge_adapter_class=SelectionAdapter,
    )
    selection = asyncio.create_task(
        coro=session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
    )
    try:
        async with asyncio.timeout(2):
            await entered.wait()
            with pytest.raises(RuntimeError, match="transition|selection"):
                _ = [event async for event in session.invoke(text="must not run")]
            assert await store.load_events(session_id="selection") == []
            release.set()
            assert (await selection).startswith("active model switched")
    finally:
        release.set()
        await asyncio.gather(selection, return_exceptions=True)
        await session.close_agent_resources()


async def test_default_startup_checks_native_status_without_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A prefixed configured startup observes native admission before reporting ready."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    checks: list[str] = []
    transport = ScriptedClaudeTransport()

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Record a non-inference external status observation."""
        checks.append("checked")
        return ClaudeAuthenticationStatusDAO(
            state="login_required", safe_message="Use Claude Code /login outside Slo."
        )

    class StartupAdapter(SloClaudeBridgeAdapter):
        """Control native I/O only, leaving startup ownership real."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Build the actual adapter with synthetic auth and wire boundaries."""
            return cls(configuration=configuration, transport=transport, authentication_check=status)

    session = SloAgentSession.build(
        config=SessionConfigDAO(
            workdir=tmp_path, model_name="claude-bridge:claude-haiku-5-5", enable_history=False
        ),
        bridge_adapter_class=StartupAdapter,
    )
    with pytest.raises(ValueError, match="Claude Code /login"):
        await session.prepare_startup()
    assert checks == ["checked"]
    assert session.active_model_name == "claude-bridge:claude-haiku-5-5"
    assert session.preparation_status == "failed"
    assert not transport.connected
    assert transport.prompts == []
    await session.close_agent_resources()


@pytest.mark.parametrize("prior_kind", ["slash_command", "user_message", "assistant_message", "tool_call"])
async def test_prior_history_does_not_block_bridge_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prior_kind: str
) -> None:
    """Any prior history, whichever model wrote it, is welcome on a bridge switch."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await store.ensure_session(session_id="freshness", workdir=tmp_path, model_name="gpt-5.4")
    await store.append_event(
        event=SessionHistoryEventDAO.model_validate(
            {
                "session_id": "freshness",
                "kind": prior_kind,
                "payload": SessionHistoryEventPayloadDAO(content="synthetic audit or conversation"),
            }
        )
    )
    transport = ScriptedClaudeTransport()
    session = SloAgentSession(
        workdir=tmp_path,
        session_id="freshness",
        history_store=store,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4"),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    result = await session.prepare_model_selection(model_name="claude-bridge:claude-haiku-5-5")
    assert result.startswith("active model switched")
    events = [event async for event in session.invoke(text="hello")]
    assert events[-1].kind == "run_completed"
    await session.close_agent_resources()
    [sent] = transport.prompts
    if prior_kind == "slash_command":
        assert sent == "hello"
        return
    assert isinstance(sent, list) and sent[-1] == {"type": "text", "text": "hello"}
    assert "synthetic audit or conversation" in "".join(block["text"] for block in sent[:-1])


@pytest.mark.parametrize("state", ["login_required", "unsupported", "conflict", "unavailable"])
async def test_native_auth_rejection_preserves_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """ER-01: unavailable native authentication cannot commit a model selection."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport()

    async def status() -> ClaudeAuthenticationStatusDAO:
        """Return safe synthetic status, without native execution."""
        return ClaudeAuthenticationStatusDAO.model_validate(
            {"state": state, "safe_message": "Native unavailable."}
        )

    class RejectedAdapter(SloClaudeBridgeAdapter):
        """Use the real adapter with a non-ready vendor status boundary."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Register inertly for selection without replacing internal owners."""
            return cls(configuration=configuration, transport=transport, authentication_check=status)

    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=False),
        bridge_adapter_class=RejectedAdapter,
    )
    selection = await session.prepare_model_selection(model_name="claude-bridge:claude-sonnet-4-6")
    assert session.active_model_name == "gpt-5.4", selection
    assert "Native unavailable" in selection
    assert not transport.connected
    assert transport.prompts == []
    await session.close_agent_resources()


async def test_auth_failure_leaves_fresh_prompt_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A native admission rejection is not treated as an already-submitted prompt."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    attempts: list[str] = []

    class FlakyAuthAdapter(SloClaudeBridgeAdapter):
        """Fail native admission once without replacing real session or history owners."""

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Register the scripted external status dependency."""

            async def status() -> ClaudeAuthenticationStatusDAO:
                """Fail before inference once, then admit the same candidate."""
                if not attempts:
                    attempts.append("failed")
                    return ClaudeAuthenticationStatusDAO(
                        state="unavailable", safe_message="Native login unavailable."
                    )
                return ClaudeAuthenticationStatusDAO(state="ready", safe_message="ready")

            return cls(
                configuration=configuration,
                transport=ScriptedClaudeTransport(
                    initialized_tools=tuple(f"mcp__slo__{name}" for name in LOCAL_TOOL_NAMES)
                ),
                authentication_check=status,
            )

    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-bridge:claude-haiku-5-5"),
        bridge_adapter_class=FlakyAuthAdapter,
    )
    try:
        with pytest.raises(ValueError, match="Native login unavailable"):
            await session.prepare_startup()
        await session.prepare_startup()
        events = [event async for event in session.invoke(text="hello")]
        assert events[-1].kind == "run_completed"
        followup = [event async for event in session.invoke(text="again")]
        assert followup[-1].kind == "run_completed"
    finally:
        await session.close_agent_resources()


def test_bridge_rejects_steering_but_compacts_like_any_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Steering stays unsupported; manual compaction takes the shared path (nothing to compact yet)."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    session = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-bridge:claude-haiku-5-5"),
        bridge_adapter_class=scripted_adapter_class(transport=ScriptedClaudeTransport()),
    )
    with pytest.raises(ValueError, match="steering"):
        session.steer(message="later")

    async def compaction_result() -> object:
        """Invoke the real manual operation inside the session's running loop."""
        return await session._compact_context_locked()

    from src.agents.slo_agent.sessions.dao import ManualCompactionResultDAO

    result = asyncio.run(compaction_result())
    assert isinstance(result, ManualCompactionResultDAO)
    assert result.status == "nothing_to_compact"


async def test_dispose_unmounted_candidate_closes_its_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed replacement cannot abandon an authenticated native candidate."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    closes: list[str] = []

    class CloseRecordingAdapter(SloClaudeBridgeAdapter):
        """Record supported closure through the real session owner."""

        async def close(self) -> None:
            """Record host closure and delegate to native owner."""
            closes.append("closed")
            await super().close()

        @classmethod
        def register(cls, *, configuration: ClaudeBridgeConfigurationDAO) -> Self:
            """Register the real adapter with synthetic native admission."""
            return cls(configuration=configuration, authentication_check=ready_status)

    candidate = SloAgentSession.build(
        config=SessionConfigDAO(workdir=tmp_path, model_name="claude-bridge:claude-haiku-5-5"),
        bridge_adapter_class=CloseRecordingAdapter,
    )
    await candidate.prepare_startup()
    await candidate.dispose_unmounted_session()
    assert closes == ["closed"]
