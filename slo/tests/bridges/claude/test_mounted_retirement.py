"""Mounted replacement refuses adoption while a parked native owner cannot close."""

import asyncio
from contextlib import aclosing
from pathlib import Path

import pytest

from src.bridges.claude.bridge import SloClaudeBridge
from src.bridges.claude.sdk.adapter import SloClaudeBridgeAdapter

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class


@pytest.mark.parametrize("action", ["cancel", "unmount"])
async def test_mounted_parked_waiter_cancel_or_unmount_joins_before_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    """Enter-driven native wait is joined on Ctrl+C or mounted shutdown."""
    from src.tui.components.prompt_input.component import PromptInputComponent
    from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "unused.txt"

    class ParkedTransport(ToolRoundTransport):
        """Hold cleanup so terminal publication ordering is observable."""

        def __init__(self) -> None:
            """Expose barriers only at the external transport boundary."""
            super().__init__(path=target)
            self.closing = asyncio.Event()
            self.release = asyncio.Event()
            self.receipt = asyncio.Event()

        async def write(self, data: str) -> None:
            """Hold provider continuation after the real MCP receipt, never emit success."""
            import json

            message = json.loads(data)
            if message["type"] == "control_response" and message["response"]["request_id"].startswith(
                "tool-rpc"
            ):
                self.tool_results.append(message["response"])
                self.receipt.set()
                return
            await super().write(data=data)

        async def close(self) -> None:
            """Hold official SDK disconnect until the test releases cleanup."""
            self.closing.set()
            await self.release.wait()
            await super().close()

    transport = ParkedTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="mounted-parked",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    app = SloTUI(session=session)
    try:
        async with asyncio.timeout(10):
            async with app.run_test() as pilot:
                await pilot.pause()
                app.query_one(PromptInputComponent).text = "Read unused.txt"
                await pilot.press("enter")
                await transport.receipt.wait()
                # Provider is still reading after the exact-ID callback receipt.
                if action == "cancel":
                    await pilot.press("ctrl+c")
                    shutdown = None
                else:
                    shutdown = asyncio.create_task(coro=app.on_unmount())
                await transport.closing.wait()
                store = FilesystemSessionHistoryStore(root=tmp_path / "history")
                events = await store.load_events(session_id="mounted-parked")
                assert not any(e.kind in {"run_completed", "run_aborted"} for e in events)
                transport.release.set()
                if shutdown is not None:
                    await shutdown
                await session.close_agent_resources()
                assert transport.closed
                model = session.agent.llm
                assert isinstance(model, SloClaudeBridge)
                assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
                runtime = model.bridge_adapter._runtime
                assert runtime._owner is not None and runtime._tool_bridge is not None
                assert runtime._owner.done() and not runtime._tool_bridge.pending_calls
                assert transport.prompts == ["Read unused.txt"]
    finally:
        transport.release.set()
        await session.close_agent_resources()


async def test_mounted_model_selection_cancel_during_cleanup_keeps_old_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A11: cancellation at actual model-retirement cleanup cannot adopt its candidate."""
    from src.tui.slash_router import SlashRouter

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")

    class HeldClose(ToolRoundTransport):
        """Park the borrowed native resource until explicit release."""

        def __init__(self) -> None:
            """Allocate external cleanup barriers."""
            super().__init__(path=tmp_path / "unused.txt")
            self.closing, self.release = asyncio.Event(), asyncio.Event()

        async def close(self) -> None:
            """Wait at the SDK's supported transport cleanup seam."""
            self.closing.set()
            await self.release.wait()
            await super().close()

    transport = HeldClose()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            enable_history=False,
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    app = SloTUI(session=session)
    try:
        async with asyncio.timeout(8):
            async with app.run_test() as pilot:
                await pilot.pause()
                # Complete a declared tool response without abandoning the retained native invocation.
                model = session.agent.llm
                assert isinstance(model, SloClaudeBridge)
                _ = [event async for event in model.astream(input="Read unused.txt")]
                old_agent = session.agent
                selecting = asyncio.create_task(
                    coro=SlashRouter.dispatch(line="/model claude-bridge:claude-opus-4-8", session=session)
                )
                await transport.closing.wait()
                selecting.cancel()
                await asyncio.sleep(0)
                assert not selecting.done()
                assert session.agent is old_agent and app._session is session
                assert session.active_model_name == "claude-bridge:claude-haiku-5-5"
                transport.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await selecting
                assert session.agent is old_agent
                assert session.active_model_name == "claude-bridge:claude-haiku-5-5"
                assert transport.closed and transport.prompts == ["Read unused.txt"]
    finally:
        transport.release.set()
        await session.close_agent_resources()


async def test_mounted_new_retains_failed_parked_owner_then_explicit_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed SDK cleanup blocks mounted /new adoption, not only direct adapter admission."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "answer.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("real receipt", encoding="utf-8")

    class RefusingTransport(ToolRoundTransport):
        """Retain the parked invocation until explicit cleanup is allowed."""

        refuse = True

        async def close(self) -> None:
            """Raise without discarding resource ownership."""
            if self.refuse:
                raise OSError("unconfirmed synthetic closure")
            await super().close()

    transport = RefusingTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="old",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    app = SloTUI(session=session)
    try:
        async with asyncio.timeout(10):
            async with app.run_test() as pilot:
                await pilot.pause()
                with pytest.raises(RuntimeError, match="closure is unconfirmed"):
                    async with aclosing(session.invoke(text="Read answer.txt")) as stream:
                        async for event in stream:
                            if event.kind == "tool_call_start":
                                session.abort()
                model = session.agent.llm
                assert isinstance(model, SloClaudeBridge)
                assert isinstance(model.bridge_adapter, SloClaudeBridgeAdapter)
                runtime = model.bridge_adapter._runtime
                assert runtime._owner is not None and runtime._tool_bridge is not None
                assert not runtime._owner.done()
                from src.tui.components.prompt_input.component import PromptInputComponent

                old_agent = session.agent
                before = (
                    len(app._chat_transcript._adapter.lines)
                    if app._chat_transcript._adapter is not None
                    else 0
                )
                app.query_one(PromptInputComponent).text = "/model claude-bridge:claude-opus-4-8"
                await pilot.press("enter")
                await pilot.pause()
                assert app._chat_transcript._adapter is not None
                notices = [
                    content
                    for content, _ in app._chat_transcript._adapter.lines[before:]
                    if "unconfirmed" in content
                ]
                assert notices == ["previous model cleanup is unconfirmed; retry /model or /new"]
                assert session.active_model_name == "claude-bridge:claude-haiku-5-5"
                assert session.agent is old_agent
                await app._start_new_session(requested_name=None)
                assert app._session is session
                assert session.agent.llm is model
                assert model.bridge_adapter._runtime is runtime
                assert transport.prompts == ["Read answer.txt"] and not transport.tool_results
                transport.refuse = False
                await session.close_agent_resources()
                await app._start_new_session(requested_name=None)
                assert app._session is not session
                assert runtime._owner.done() and not runtime._tool_bridge.pending_calls
                assert transport.closed
    finally:
        transport.refuse = False
        await session.close_agent_resources()
