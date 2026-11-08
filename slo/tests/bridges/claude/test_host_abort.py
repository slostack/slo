"""Normal graph-item abort ordering through the real session, SDK and history."""

import asyncio
from contextlib import aclosing
from pathlib import Path

import pytest

from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class


@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_available_tool_boundary_abort_joins_before_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cleanup_fails: bool,
) -> None:
    """Abort on a yielded tool call while the graph's completed update is available.

    Only native transport/authentication are substituted. Cleanup is held outside
    the SDK owner; failed cleanup stays failed until the operator explicitly retries.
    """
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "answer.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("receipt", encoding="utf-8")
    cleanup_entered = asyncio.Event()
    release_cleanup = asyncio.Event()
    terminal_observed = asyncio.Event()
    observed_kinds: list[str] = []

    class GatedCleanupTransport(ToolRoundTransport):
        """Keep native disconnect pending, or unconfirmed, until explicitly released."""

        reject_cleanup: bool = cleanup_fails

        async def close(self) -> None:
            """Signal entry before blocking so assertions do not depend on SDK timing."""
            cleanup_entered.set()
            await release_cleanup.wait()
            if self.reject_cleanup:
                raise OSError("synthetic unconfirmed native closure")
            await super().close()

    transport = GatedCleanupTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="available-abort",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )

    async def consume() -> None:
        """Request abort from a real yielded graph item, not a blocked response read."""
        async with aclosing(session.invoke(text="Read answer.txt")) as stream:
            async for event in stream:
                observed_kinds.append(event.kind)
                if event.kind == "tool_call_start":
                    model = session.agent.llm
                    assert isinstance(model, SloClaudeBridge)
                    assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
                    runtime = model.bridge_adapter._runtime
                    assert runtime._owner is not None and runtime._tool_bridge is not None
                    while not runtime._tool_bridge.pending_calls:
                        await asyncio.sleep(0)
                    session.abort()
                if event.kind == "run_aborted":
                    terminal_observed.set()
                    assert transport.closed
                    model = session.agent.llm
                    assert isinstance(model, SloClaudeBridge)
                    assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
                    runtime = model.bridge_adapter._runtime
                    assert runtime._owner is not None and runtime._tool_bridge is not None
                    assert runtime._owner.done()
                    assert not runtime._tool_bridge.pending_calls

    consumer = asyncio.create_task(coro=consume())
    try:
        async with asyncio.timeout(10):
            await cleanup_entered.wait()
            assert "tool_call_start" in observed_kinds
            # A premature terminal completes the consumer while disconnect is held.
            done, _ = await asyncio.wait({consumer}, timeout=0.05)
            assert not terminal_observed.is_set()
            assert not done
            store = FilesystemSessionHistoryStore(root=tmp_path / "history")
            history = await store.load_events(session_id="available-abort")
            assert not any(event.kind == "run_aborted" for event in history)
            model = session.agent.llm
            assert isinstance(model, SloClaudeBridge)
            assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
            runtime = model.bridge_adapter._runtime
            assert runtime._owner is not None and runtime._tool_bridge is not None
            assert not runtime._owner.done()
            release_cleanup.set()
            if cleanup_fails:
                with pytest.raises(RuntimeError, match="closure is unconfirmed"):
                    await consumer
                assert not terminal_observed.is_set()
                assert session.agent.llm is model
                assert model.bridge_adapter._runtime is runtime
                assert not runtime._owner.done()
                with pytest.raises(RuntimeError, match="new session"):
                    _ = [event async for event in session.invoke(text="must not send")]
                transport.reject_cleanup = False
                await session.close_agent_resources()
            else:
                await consumer
                assert observed_kinds.count("run_aborted") == 1
            assert runtime._owner.done()
            assert not runtime._tool_bridge.pending_calls
            assert transport.closed
            assert transport.prompts == ["Read answer.txt"]
            assert not transport.tool_results
            history = await store.load_events(session_id="available-abort")
            assert sum(event.kind == "run_aborted" for event in history) == int(not cleanup_fails)
            assert not any(event.kind == "run_completed" for event in history)
            await session.close_agent_resources()
            assert transport.close_calls == 1
    finally:
        transport.reject_cleanup = False
        release_cleanup.set()
        await asyncio.gather(consumer, return_exceptions=True)
        await session.close_agent_resources()
