"""Hold the host at a tool-start boundary beyond provider idle."""

import asyncio
from collections.abc import Awaitable
from pathlib import Path

import pytest

from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from tests.cli.test_claude_bridge import ToolRoundTransport, scripted_adapter_class


async def join_fifo_cleanup(
    *, cleanups: tuple[Awaitable[None], ...], primary: BaseException | None, rendezvous: list[str]
) -> None:
    """Join every test-owned cleanup and retain failures without replacing an active primary.

    Args:
        cleanups: Already requested session/writer cleanup, joined in order.
        primary: Active test failure, or None when cleanup must fail independently.
        rendezvous: Writer open stages and relative monotonic timings.

    Raises:
        BaseException: The first cleanup failure when no test failure is active.
    """
    cleanup_failure: BaseException | None = None
    for cleanup in cleanups:
        try:
            await cleanup
        except BaseException as error:
            note = f"FIFO cleanup {type(error).__name__}: {error}; timings={rendezvous}"
            print(note, flush=True)
            if primary is not None:
                primary.add_note(note)
            elif cleanup_failure is None:
                cleanup_failure = error
    if cleanup_failure is not None:
        raise cleanup_failure


@pytest.mark.parametrize("has_primary", [False, True])
async def test_fifo_cleanup_preserves_primary_and_still_fails_without_one(has_primary: bool) -> None:
    """Cleanup joins all owners, preserving an active failure rather than masking it."""
    closed: list[str] = []
    primary = ValueError("primary stream failure") if has_primary else None

    async def fail_writer() -> None:
        """Represent a settled writer-open failure without real I/O or delays."""
        raise TimeoutError("writer open index=2")

    async def close_session() -> None:
        """Record that another cleanup owner was joined despite writer failure."""
        closed.append("session")

    if primary is None:
        with pytest.raises(TimeoutError, match="writer open index=2"):
            await join_fifo_cleanup(
                cleanups=(fail_writer(), close_session()), primary=None, rendezvous=["open[2] start=0.1"]
            )
    else:
        with pytest.raises(ValueError, match="primary stream failure") as raised:
            try:
                raise primary
            finally:
                await join_fifo_cleanup(
                    cleanups=(fail_writer(), close_session()),
                    primary=primary,
                    rendezvous=["open[2] start=0.1"],
                )
        assert raised.value is primary
        assert "writer open index=2" in str(primary.__notes__)
        assert "open[2] start=0.1" in str(primary.__notes__)
    assert closed == ["session"]


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
    started = time.monotonic()
    rendezvous: list[str] = []

    def supply_two_reads() -> None:
        """Serve Pillow probe, binary sniff and UTF-8 read separately, never a permanent blocking writer."""
        for index in range(3):
            rendezvous.append(f"open[{index}] start={time.monotonic() - started:.6f}")
            deadline = time.monotonic() + 4
            while True:
                try:
                    fd = os.open(target, os.O_WRONLY | os.O_NONBLOCK)
                    rendezvous.append(f"open[{index}] accepted={time.monotonic() - started:.6f}")
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            f"canonical read did not open FIFO index={index}; timings={rendezvous}"
                        )
                    time.sleep(0.01)
            try:
                if index == 2:
                    reader_entered.set()
                    time.sleep(0.5)
                os.write(fd, b"real slow executor receipt\n")
            finally:
                os.close(fd)
                rendezvous.append(f"open[{index}] closed={time.monotonic() - started:.6f}")
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
                error.add_note(f"FIFO primary; timings={rendezvous}")
                print(f"FIFO PRIMARY {type(error).__name__}: {error}; timings={rendezvous}", flush=True)
                if not stall_after_receipt:
                    raise
            try:
                await writer
            except Exception as writer_error:
                if caught is None:
                    raise
                caught.add_note(f"FIFO writer {writer_error!r}; timings={rendezvous}")
                raise caught
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
        import sys

        await join_fifo_cleanup(
            cleanups=(session.close_agent_resources(), asyncio.shield(writer)),
            primary=sys.exception(),
            rendezvous=rendezvous,
        )
        print(f"FIFO TIMINGS {rendezvous}", flush=True)


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
