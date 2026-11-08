"""Hold the host at a tool-start boundary beyond provider idle."""

import asyncio
from pathlib import Path

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class


@pytest.mark.parametrize("stall_after_receipt", [False, True])
async def test_real_executor_fifo_io_suspends_then_reactivates_watchdog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stall_after_receipt: bool
) -> None:
    """Read's three real opens wait on bounded FIFO I/O; provider timing resumes after result."""
    import json
    import os
    import threading
    import time

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    monkeypatch.setenv(name="SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS", value="0.15")
    monkeypatch.setenv(name="SLO_PROVIDER_STREAM_FIRST_PROGRESS_TIMEOUT_SECONDS", value="0.15")
    target = tmp_path / "slow.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    os.mkfifo(target)
    reader_entered = threading.Event()

    def supply_two_reads() -> None:
        """Serve Pillow probe, binary sniff and UTF-8 read separately, never a permanent blocking writer."""
        for index in range(3):
            deadline = time.monotonic() + 4
            while True:
                try:
                    fd = os.open(target, os.O_WRONLY | os.O_NONBLOCK)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError("canonical read did not open FIFO")
                    time.sleep(0.01)
            try:
                if index == 2:
                    reader_entered.set()
                    time.sleep(0.5)
                os.write(fd, b"real slow executor receipt\n")
            finally:
                os.close(fd)
            # Let the sniff reader observe EOF before the text reader opens.
            time.sleep(0.05)

    class ReceiptStallTransport(ToolRoundTransport):
        """Optionally stop provider progress only after actual tool completion."""

        async def write(self, data: str) -> None:
            """Record the receipt without manufacturing subsequent provider progress."""
            message = json.loads(data)
            if (
                stall_after_receipt
                and message["type"] == "control_response"
                and message["response"]["request_id"].startswith("tool-rpc")
            ):
                self.tool_results.append(message["response"])
                return
            await super().write(data=data)

    transport = ReceiptStallTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="executor-io",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    writer = asyncio.create_task(coro=asyncio.to_thread(supply_two_reads))
    events = []
    caught = None
    try:
        async with asyncio.timeout(8):
            try:
                async for event in session.invoke(text="Read slow.txt"):
                    events.append(event)
            except Exception as error:
                caught = error
                if not stall_after_receipt:
                    raise
            await writer
        assert reader_entered.is_set()
        stored = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id="executor-io"
        )
        assert sum(event.kind == "tool_result" for event in stored) == 1
        assert "real slow executor receipt" in str(transport.tool_results)
        assert sum(event.kind == "run_completed" for event in stored) == (0 if stall_after_receipt else 1)
        if stall_after_receipt:
            from src.agents.providers.stream_recovery.dao import ProviderStreamProgressTimeout

            assert sum(e.kind == "run_started" for e in stored) == 1, [e.kind for e in stored]
            chain = []
            current: BaseException | None = caught
            while current is not None:
                chain.append(current)
                current = current.__cause__ or current.__context__
            assert any(isinstance(error, ProviderStreamProgressTimeout) for error in chain), repr(chain)
            assert any(event.kind == "run_failed" for event in stored), (
                repr(caught),
                [e.kind for e in stored],
            )
            assert transport.closed and transport.close_calls == 1
        assert transport.prompts == ["Read slow.txt"]
    finally:
        await session.close_agent_resources()
        await writer


async def test_host_tool_boundary_wait_does_not_expire_provider_watchdog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delayed host consumer precedes the real read, with one MCP receipt."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    monkeypatch.setenv(name="SLO_PROVIDER_STREAM_IDLE_TIMEOUT_SECONDS", value="0.15")
    target = tmp_path / "answer.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("real slow receipt", encoding="utf-8")
    transport = ToolRoundTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="slow",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(5):
            events = []
            async for event in session.invoke(text="Read answer.txt"):
                events.append(event)
                if event.kind == "tool_call_start":
                    await asyncio.sleep(0.5)
            assert any(event.kind == "run_completed" for event in events)
            assert not any(event.kind == "run_failed" for event in events)
            assert "real slow receipt" in str(transport.tool_results)
            stored = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                session_id="slow"
            )
            assert sum(event.kind == "tool_result" for event in stored) == 1
    finally:
        await session.close_agent_resources()
