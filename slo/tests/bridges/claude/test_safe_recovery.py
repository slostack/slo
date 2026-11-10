"""Bounded native recovery through real sessions, SDK transport and temp history."""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.bridges.claude.sdk.exceptions import ClaudeBridgeError
from src.bridges.claude.sdk.dao import ClaudeSessionOptionsDAO
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, ToolRoundTransport, scripted_adapter_class


@pytest.mark.parametrize("failures", [1, 3])
async def test_transient_unsent_connect_is_bounded_on_same_route(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failures: int
) -> None:
    """Only demonstrated transient, unsent failures retry; exhaustion stays actionable."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")

    class TransientConnectTransport(ScriptedClaudeTransport):
        """Refuse a known number of external connections before any query can be written."""

        def __init__(self) -> None:
            """Keep attempt accounting outside the host's retry implementation."""
            super().__init__()
            self.connect_calls: int = 0

        async def connect(self) -> None:
            """Raise a concrete transient connection error, never an authentication error."""
            self.connect_calls += 1
            if self.connect_calls <= failures:
                raise ConnectionRefusedError("synthetic temporary connection refusal")
            self.closed = False
            await super().connect()

    transport = TransientConnectTransport()
    options: list[ClaudeSessionOptionsDAO] = []
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="retry",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport, session_options=options),
    )
    observed: list[str] = []
    try:
        async with asyncio.timeout(10):
            if failures == 3:
                with pytest.raises(ClaudeBridgeError, match="not submitted"):
                    async for event in session.invoke(text="hello"):
                        observed.append(event.kind)
            else:
                async for event in session.invoke(text="hello"):
                    observed.append(event.kind)
        assert transport.connect_calls == (3 if failures == 3 else 2)
        assert transport.prompts == ([] if failures == 3 else ["hello"])
        assert observed.count("run_failed") == int(failures == 3)
        assert observed.count("run_completed") == int(failures == 1)
        assert observed.count("run_retrying") == (2 if failures == 3 else 1)
        assert session.active_model_name == "claude-bridge:claude-haiku-5-5"
        assert {option.model_id for option in options} == {session.active_model_name}
        history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id="retry"
        )
        assert [e.payload.content for e in history if e.kind == "user_message"] == ["hello"]
        assert sum(e.kind == "run_failed" for e in history) == failures
        assert sum(e.kind == "run_started" for e in history) == transport.connect_calls
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize("tool_round, thinking_after_text", [(False, False), (True, False), (False, True)])
async def test_native_failure_retains_text_and_explicit_next_prompt_uses_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool_round: bool, thinking_after_text: bool
) -> None:
    """Closed native text is not terminal success; partial progress survives a fresh explicit turn."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "value.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("durable tool receipt", encoding="utf-8")

    class FailingTextTransport(ToolRoundTransport):
        """Fail at native terminal only after delivering visible answer fragments."""

        async def connect(self) -> None:
            """Allow the next explicit prompt on a fresh native connection."""
            self.closed = False
            await super().connect()

        async def write(self, data: str) -> None:
            """Use tools only on the first requested journey, not on the explicit follow-up."""
            if not tool_round or (self.prompts and json.loads(data)["type"] == "user"):
                await ScriptedClaudeTransport.write(self, data=data)
                return
            await super().write(data=data)

        async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
            """Leave SDK parsing and host history real, replacing only the vendor result."""
            async for message in super().read_messages():
                if (
                    tool_round
                    and len(self.prompts) == 1
                    and message["type"] == "stream_event"
                    and message["event"]["type"] == "message_delta"
                    and message["event"]["delta"]["stop_reason"] == "tool_use"
                ):
                    for event in (
                        {
                            "type": "content_block_start",
                            "index": 1,
                            "content_block": {"type": "text", "text": "Inspect round 1."},
                        },
                        {"type": "content_block_stop", "index": 1},
                    ):
                        yield {**message, "event": event}
                if (
                    tool_round
                    and message["type"] == "assistant"
                    and message["message"]["content"][0]["type"] == "tool_use"
                ):
                    message["message"]["content"].append({"type": "text", "text": "Inspect round 1."})
                if (
                    thinking_after_text
                    and len(self.prompts) == 1
                    and message["type"] == "stream_event"
                    and message["event"]["type"] == "message_delta"
                ):
                    for event in (
                        {
                            "type": "content_block_start",
                            "index": 1,
                            "content_block": {"type": "thinking", "thinking": "Still working"},
                        },
                        {"type": "content_block_stop", "index": 1},
                    ):
                        yield {**message, "event": event}
                if len(self.prompts) == 1 and message["type"] == "result":
                    message = {
                        **message,
                        "subtype": "error_during_execution",
                        "is_error": True,
                        "errors": ["synthetic terminal failure"],
                    }
                yield message

    transport = FailingTextTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="partial",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    try:
        async with asyncio.timeout(10):
            failed_events = []
            with pytest.raises(ClaudeBridgeError, match="Submission may have occurred"):
                async for event in session.invoke(text="inspect"):
                    failed_events.append(event)
            assert failed_events[-1].kind == "run_failed"
            assert failed_events[-1].iteration == int(tool_round)
            history = await store.load_events(session_id="partial")
            assistant_text = [e.payload.content for e in history if e.kind == "assistant_message"]
            expected = ["Inspect round 1."] if tool_round else []
            assert assistant_text == ["Hello bridge"]
            # Tool-round assistant text is carried by tool_call records, not
            # separate assistant_message rows; only unfinished text needs flushing.
            calls = [e.payload.content for e in history if e.kind == "tool_call"]
            assert list(dict.fromkeys(calls)) == expected
            assert sum(e.kind == "tool_result" for e in history) == int(tool_round)
            assert not any(e.kind in {"run_completed", "stream_reconnecting"} for e in history)
            # No automatic replay after text, tool execution or result delivery.
            assert len(transport.prompts) == 1
            result = [event async for event in session.invoke(text="continue explicitly")]
            assert result[-1].kind == "run_completed"
            assert len(transport.prompts) == 2
            sent: object = transport.prompts[-1]
            assert isinstance(sent, list), "fresh native handoff carries transcript blocks"
            transcript = "".join(block["text"] for block in sent[:-1])
            assert transcript.count("Hello bridge") == 1
            for text in expected:
                assert transcript.count(text) == 1
            if tool_round:
                assert transcript.count("durable tool receipt") == 1
                assert len(transport.tool_results) == 1
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize("failure", ["auth", "config", "generic-os"])
async def test_unsent_nontransient_failure_never_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Unsent is not enough: login/configuration/unknown OS failures need explicit operator action."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    from src.bridges.claude.sdk.exceptions import ClaudeSubmissionNotStartedError

    class NontransientTransport(ScriptedClaudeTransport):
        """Reject native connection with a non-transient category."""

        def __init__(self) -> None:
            """Retain exact external attempts."""
            super().__init__()
            self.connect_calls: int = 0

        async def connect(self) -> None:
            """Never promote an arbitrary startup failure to automatic retry."""
            self.connect_calls += 1
            if failure == "config":
                raise ValueError("invalid native configuration")
            raise OSError("unknown startup failure")

    transport = NontransientTransport()
    base_adapter = scripted_adapter_class(transport=transport)
    admissions: list[str] = []

    # The fixture returns a concrete SDK adapter subclass bound to this transport.
    class NontransientAdapter(base_adapter):  # type: ignore[misc, valid-type]
        """Reject auth at inert admission, as the concrete adapter does."""

        async def start_session(self, *, session_options: ClaudeSessionOptionsDAO) -> None:
            """Record exact route and refuse login without native work."""
            admissions.append(session_options.model_id)
            if failure == "auth":
                raise ClaudeSubmissionNotStartedError(
                    code="authentication_required", safe_message="Native login required; use Claude /login."
                )
            await super().start_session(session_options=session_options)

    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="nontransient",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=NontransientAdapter,
    )
    observed: list[str] = []
    try:
        with pytest.raises(ClaudeSubmissionNotStartedError):
            async for event in session.invoke(text="hello"):
                observed.append(event.kind)
        assert admissions == ["claude-bridge:claude-haiku-5-5"]
        assert transport.connect_calls == int(failure != "auth")
        assert transport.prompts == []
        assert observed.count("run_failed") == 1
        assert "run_retrying" not in observed
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize("cancel", ["none", "abort", "task"])
async def test_unsent_cleanup_settles_before_retry_and_cancellation_prevents_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: str
) -> None:
    """Gate real SDK rollback: no replacement/native query is admitted while cleanup is held."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    entered = asyncio.Event()
    release = asyncio.Event()

    class GatedConnectTransport(ScriptedClaudeTransport):
        """Fail once before query and hold the SDK-owned disconnect."""

        def __init__(self) -> None:
            """Count connect and closure independently of host events."""
            super().__init__()
            self.connect_calls: int = 0

        async def connect(self) -> None:
            """Refuse one connection with a transient type."""
            self.connect_calls += 1
            if self.connect_calls == 1:
                raise ConnectionResetError("temporary startup failure")
            self.closed = False
            await super().connect()

        async def close(self) -> None:
            """Hold all failed-attempt cleanup until the test explicitly releases it."""
            if self.connect_calls == 1:
                entered.set()
                await release.wait()
            await super().close()

    transport = GatedConnectTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="gated",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    observed: list[str] = []

    async def invoke() -> None:
        """Drain the real submission while recording forbidden terminal notifications."""
        async for event in session.invoke(text="hello"):
            observed.append(event.kind)

    task = asyncio.create_task(coro=invoke())
    try:
        async with asyncio.timeout(10):
            await entered.wait()
            assert transport.connect_calls == 1
            assert transport.prompts == []
            assert "run_completed" not in observed
            if cancel == "abort":
                session.abort()
            elif cancel == "task":
                task.cancel()
            # Cancellation intent still cannot authorize a successor or completion.
            assert transport.connect_calls == 1
            release.set()
            await task
        assert transport.connect_calls == (2 if cancel == "none" else 1)
        assert transport.prompts == (["hello"] if cancel == "none" else [])
        assert observed[-1] == ("run_completed" if cancel == "none" else "run_aborted")
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await session.close_agent_resources()


@pytest.mark.parametrize("cancel", ["abort", "task"])
async def test_cancellation_during_retry_admission_prevents_second_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: str
) -> None:
    """An abort delivered at the retry notice cannot be cleared by a new graph invocation."""
    from src.agents.slo_agent.events.stream import AgentStreamEventDAO

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    entered = asyncio.Event()
    release = asyncio.Event()

    class RetryTransport(ScriptedClaudeTransport):
        """Count attempted external connections."""

        connect_calls: int = 0

        async def connect(self) -> None:
            """Refuse every connect; a second one is forbidden after cancellation."""
            self.connect_calls += 1
            raise ConnectionRefusedError("transient")

    transport = RetryTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="retry-cancel",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )

    async def notice(event: AgentStreamEventDAO) -> None:
        """Hold the public retry notice while the operator cancels admission."""
        if event.kind == "run_retrying":
            entered.set()
            await release.wait()

    session.subscribe(handler=notice)
    observed: list[str] = []

    async def invoke() -> None:
        """Record the actual session terminal."""
        async for event in session.invoke(text="hello"):
            observed.append(event.kind)

    task = asyncio.create_task(coro=invoke())
    try:
        async with asyncio.timeout(10):
            await entered.wait()
            if cancel == "abort":
                session.abort()
            else:
                task.cancel()
            release.set()
            await task
        assert transport.connect_calls == 1
        assert transport.prompts == []
        assert observed[-1] == "run_aborted"
        assert "run_completed" not in observed
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await session.close_agent_resources()


@pytest.mark.parametrize("failure", [False, True])
async def test_native_closure_does_not_complete_until_cleanup_and_retains_failed_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    """EF05: text/message_stop is not success; failed cleanup blocks successor admission."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    entered = asyncio.Event()
    release = asyncio.Event()

    class TerminalCleanupTransport(ScriptedClaudeTransport):
        """Hold disconnect after native closure, optionally refusing cleanup."""

        refuse: bool = failure
        connect_calls: int = 0

        async def connect(self) -> None:
            """Count successors independently of host preparation."""
            self.connect_calls += 1
            self.closed = False
            await super().connect()

        async def close(self) -> None:
            """Keep ownership unconfirmed until an explicit successful close."""
            entered.set()
            await release.wait()
            if self.refuse:
                raise OSError("synthetic cleanup failure")
            await super().close()

    transport = TerminalCleanupTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="terminal-cleanup",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    observed: list[str] = []

    async def invoke() -> None:
        """Drain text without presuming terminal completion."""
        async for event in session.invoke(text="hello"):
            observed.append(event.kind)

    task = asyncio.create_task(coro=invoke())
    try:
        async with asyncio.timeout(10):
            await entered.wait()
            assert "run_completed" not in observed
            assert transport.connect_calls == 1
            release.set()
            if failure:
                with pytest.raises(ClaudeBridgeError, match="cleanup failed"):
                    await task
                assert not session.agent.bridge_is_retired()
                with pytest.raises(RuntimeError):
                    _ = [event async for event in session.invoke(text="must not start")]
                assert transport.connect_calls == 1
                history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
                    session_id="terminal-cleanup"
                )
                assert [e.payload.content for e in history if e.kind == "assistant_message"] == [
                    "Hello bridge"
                ]
                assert not any(e.kind == "run_completed" for e in history)
                transport.refuse = False
                await session.close_agent_resources()
                assert session.agent.bridge_is_retired()
            else:
                await task
                assert observed[-1] == "run_completed"
    finally:
        release.set()
        transport.refuse = False
        await asyncio.gather(task, return_exceptions=True)
        await session.close_agent_resources()


async def test_uncertain_tool_result_write_never_replays_execution_or_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A receipt can reach native before a write fails; neither SDK nor session may send it twice."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "receipt.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text("one real read", encoding="utf-8")

    class UncertainReceiptTransport(ToolRoundTransport):
        """Record possible vendor delivery before refusing the exact-ID receipt."""

        async def write(self, data: str) -> None:
            """Make the SDK's attempted write observable, not the host's result adapter."""
            message = json.loads(data)
            if message["type"] == "control_response" and message["response"]["request_id"].startswith(
                "tool-rpc"
            ):
                self.tool_results.append(message["response"])
                raise ConnectionResetError("receipt may already have been delivered")
            await super().write(data=data)

    transport = UncertainReceiptTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="uncertain-receipt",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            with pytest.raises(ClaudeBridgeError, match="Do not replay automatically"):
                _ = [event async for event in session.invoke(text="read receipt")]
        history = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id="uncertain-receipt"
        )
        assert transport.prompts == ["read receipt"]
        assert len(transport.tool_results) == 1
        assert sum(e.kind == "tool_call" for e in history) == 1
        assert [e.payload.tool_output for e in history if e.kind == "tool_result"] == ["one real read"]
        assert sum(e.kind == "run_started" for e in history) == 1
        assert not any(e.kind in {"run_completed", "stream_reconnecting", "run_retrying"} for e in history)
    finally:
        await session.close_agent_resources()
