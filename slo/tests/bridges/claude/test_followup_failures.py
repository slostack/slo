"""Later native turns: fresh tool bindings and uncertain submission closure."""

import asyncio
from collections.abc import AsyncIterator
import json
from pathlib import Path
from typing import Any, cast

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, ToolRoundTransport, scripted_adapter_class


async def test_later_tool_turns_allow_repeated_call_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each resumed turn executes its new call exactly once, even with repeated native IDs."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "value.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())

    class RepeatedToolTransport(ToolRoundTransport):
        """Reuse the same response and tool IDs on every new native connection."""

        async def connect(self) -> None:
            """Reset only per-turn script state, retaining all wire receipts."""
            self.closed = False
            self.round = 0
            await super().connect()

    transport = RepeatedToolTransport(path=target)
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="tools",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            for index in range(3):
                target.write_text(f"receipt-{index}", encoding="utf-8")
                result = [event async for event in session.invoke(text=f"Read version {index}")]
                assert result[-1].kind == "run_completed"
                assert len(transport.tool_results) == index + 1
                assert f"receipt-{index}" in json.dumps(transport.tool_results[index])
        assert transport.prompts == [f"Read version {index}" for index in range(3)]
        assert transport.close_calls == 3
        events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id="tools"
        )
        assert sum(event.kind == "tool_call" for event in events) == 3
        assert sum(event.kind == "tool_result" for event in events) == 3
        assert sum(event.kind == "run_completed" for event in events) == 3
    finally:
        await session.close_agent_resources()


async def test_foreign_result_on_resumed_turn_is_not_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign session result cannot complete the new invocation."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")

    class ForeignResultTransport(ScriptedClaudeTransport):
        """Supply a different session's terminal result on the second connection."""

        async def connect(self) -> None:
            """Keep the scripted SDK connection reusable."""
            self.closed = False
            await super().connect()

        async def read_messages(self) -> AsyncIterator[dict[str, Any]]:
            """Corrupt only external terminal identity, leaving SDK parsing real."""
            async for message in super().read_messages():
                if len(self.prompts) == 2 and message["type"] == "result":
                    message = {**message, "session_id": "foreign-native"}
                yield message

    transport = ForeignResultTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="foreign",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            _ = [event async for event in session.invoke(text="first")]
            with pytest.raises(RuntimeError, match="new session"):
                _ = [event async for event in session.invoke(text="second")]
        events = await FilesystemSessionHistoryStore(root=tmp_path / "history").load_events(
            session_id="foreign"
        )
        assert sum(event.kind == "run_completed" for event in events) == 1
        assert sum(event.kind == "run_failed" for event in events) == 1
        assert transport.prompts == ["first", "second"]
        assert transport.closed
    finally:
        await session.close_agent_resources()


async def test_cancel_resumed_turn_joins_before_host_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancel after a successful turn without replaying either native query."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")

    class ResumedTransport(ScriptedClaudeTransport):
        """Block the second native turn at response delivery."""

        async def connect(self) -> None:
            """Reset native connection flags but preserve query accounting."""
            self.closed = False
            self.submitted.clear()
            self.block_response = bool(self.prompts)
            await super().connect()

    transport = ResumedTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="cancel",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            _ = [event async for event in session.invoke(text="first")]
            transport.submitted.clear()

            async def cancel_after_send() -> None:
                """Abort only after observing the second native query."""
                await transport.submitted.wait()
                session.abort()

            cancellation = asyncio.create_task(coro=cancel_after_send())
            events = [event async for event in session.invoke(text="second")]
            await cancellation
            assert any(event.kind == "run_aborted" for event in events)
            assert transport.closed
            await session.close_agent_resources()
            await session.close_agent_resources()
        assert transport.prompts == ["first", "second"]
        assert transport.close_calls == 2
    finally:
        await session.close_agent_resources()


@pytest.mark.parametrize("later", [False, True])
async def test_query_write_failure_never_replays_and_next_prompt_hands_off_from_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    later: bool,
) -> None:
    """A write may reach native before raising: no automatic replay; the next prompt starts a fresh session."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")

    class UncertainTransport(ScriptedClaudeTransport):
        """Record delivery before failing the selected query write."""

        async def connect(self) -> None:
            """Allow a successfully completed first turn to resume."""
            self.closed = False
            await super().connect()

        async def write(self, data: str) -> None:
            """Fail after recording the uncertain prompt, not during connect."""
            message: dict[str, Any] = json.loads(data)
            if message["type"] == "user" and len(self.prompts) == int(later):
                self.prompts.append(message["message"]["content"])
                raise OSError("synthetic write failure after possible delivery")
            await super().write(data=data)

    transport = UncertainTransport()
    session = await SloAgentSession.prepare(
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            session_id="uncertain",
            enable_history=True,
            history_root=tmp_path / "history",
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    try:
        async with asyncio.timeout(10):
            if later:
                _ = [event async for event in session.invoke(text="first")]
            with pytest.raises(RuntimeError, match="start a new session"):
                _ = [event async for event in session.invoke(text="uncertain")]
            recovered = [event async for event in session.invoke(text="after failure")]
            assert recovered[-1].kind == "run_completed"
        assert transport.prompts[: int(later) + 1] == (["first"] if later else []) + ["uncertain"]
        sent: list[Any] = cast(Any, transport.prompts[-1])
        *transcript, prompt = sent
        assert prompt == {"type": "text", "text": "after failure"}
        replayed = "".join(block["text"] for block in transcript)
        assert "uncertain" in replayed and ("first" in replayed) is later
        assert len(transport.prompts) == int(later) + 2
    finally:
        await session.close_agent_resources()
