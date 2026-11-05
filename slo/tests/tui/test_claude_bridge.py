"""Actual Textual Enter journey over the real native bridge composition."""

import asyncio
import base64
from collections import Counter
import html
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from tests.cli.test_claude_bridge import ScriptedClaudeTransport, scripted_adapter_class


@pytest.mark.parametrize("tree_history", [False, True])
async def test_fresh_prompt_streams_and_persists_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tree_history: bool
) -> None:
    """A1/A3/A4: select a native route, Enter, render and read real tree/flat history."""
    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    transport = ScriptedClaudeTransport(pause_terminal=True)
    store = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path / "history")
        if tree_history
        else FilesystemSessionHistoryStore(root=tmp_path / "history")
    )
    session = SloAgentSession(
        workdir=tmp_path,
        session_id="bridge-tui",
        history_store=store,
        config=SessionConfigDAO(workdir=tmp_path, model_name="gpt-5.4", enable_history=True),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    app = SloTUI(session=session)

    async def release_on_test_timeout() -> None:
        """Unblock SDK cleanup even when an intermediate paint assertion fails."""
        await asyncio.sleep(12)
        transport.release_terminal.set()

    terminal_guard = asyncio.create_task(coro=release_on_test_timeout())
    async with app.run_test() as pilot:
        await pilot.pause()
        original_id = session.session_id
        app.query_one(PromptInput).text = "/new"
        await pilot.press("enter")
        await pilot.pause()
        session = app._session
        assert session.session_id != original_id
        assert session.active_model_name == "gpt-5.4"
        assert not any(
            event.kind in {"user_message", "assistant_message", "tool_call"}
            for event in await store.load_events(session_id=session.session_id)
        )
        app.query_one(PromptInput).text = "/model claude-bridge:claude-opus-4-8"
        await pilot.pause()
        assert app._slash_suggestion_state.visible
        assert [row.insert_text for row in app._slash_suggestion_state.rows] == [
            "claude-bridge:claude-opus-4-8"
        ]
        await pilot.press("tab")
        assert app.query_one(PromptInput).text.strip() == "/model claude-bridge:claude-opus-4-8"
        await pilot.press("enter")
        await pilot.pause()
        assert session.active_model_name == "claude-bridge:claude-opus-4-8"
        assert not transport.connected
        app.query_one(PromptInput).text = "/reasoning high"
        await pilot.press("enter")
        await pilot.pause()
        assert session.active_reasoning_level == "high"
        assert session.usage_snapshot().active_reasoning_level == "high"
        assert not any(
            event.kind in {"user_message", "assistant_message", "tool_call"}
            for event in await store.load_events(session_id=session.session_id)
        )
        app.query_one(PromptInput).text = "hello"
        await pilot.press("enter")
        await pilot.pause()
        async with asyncio.timeout(10):
            while (
                not list(app.query(AssistantStreamBlock))
                or list(app.query(AssistantStreamBlock))[0].get_copyable_text() != "Hello bridge"
            ):
                await pilot.pause()
        await pilot.pause()
        assert session.is_running
        assert not transport.closed
        screenshot = ET.fromstring(app.export_screenshot())
        painted = html.unescape("".join(screenshot.itertext())).replace("\u00a0", " ")
        assert "Hello bridge" in painted
        transport.release_terminal.set()
        async with asyncio.timeout(10):
            while not transport.closed or session.is_running:
                await pilot.pause()
        await pilot.pause()
        blocks = list(app.query(AssistantStreamBlock))
        assert len(blocks) == 1
        assert blocks[0].get_copyable_text() == "Hello bridge"
        assert app._adapter is not None
        before = len(app._adapter.lines)
        app.query_one(PromptInput).text = "/model claude-bridge:claude-haiku-5-5"
        await pilot.press("enter")
        await pilot.pause()
        rejections = [content for content, _ in app._adapter.lines[before:] if "fresh session" in content]
        assert rejections == []
        assert session.active_model_name == "claude-bridge:claude-haiku-5-5"
        assert transport.prompts == ["hello"]
        finished_session = session
        app.query_one(PromptInput).text = "/new"
        await pilot.press("enter")
        await pilot.pause()
        assert app._session is not finished_session
        assert app._session.active_model_name == "claude-bridge:claude-haiku-5-5"
        assert transport.closed
    terminal_guard.cancel()
    await asyncio.gather(terminal_guard, return_exceptions=True)
    events = await store.load_events(session_id=session.session_id)
    assert [event.payload.content for event in events if event.kind == "assistant_message"] == [
        "Hello bridge"
    ]
    assert sum(event.kind == "run_completed" for event in events) == 1
    assert transport.prompts == ["hello"]


@pytest.mark.parametrize("tree_history", [False, True])
@pytest.mark.parametrize("read_image", [False, True])
async def test_project_question_three_rounds_uses_real_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tree_history: bool, read_image: bool
) -> None:
    """A1/A5/A9: live read bytes cross MCP; flat/tree history retains only image refs."""
    from tests.cli.test_claude_bridge import ToolRoundTransport

    monkeypatch.setenv(name="SLO_CLAUDE_BRIDGE_ENABLED", value="1")
    target = tmp_path / "model.txt"
    assert target.resolve().is_relative_to(tmp_path.resolve())
    target.write_text(data="default-model = synthetic-model\n")
    image_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aC1cAAAAASUVORK5CYII="
    )
    if read_image:
        target = tmp_path / "model.png"
        assert target.resolve().is_relative_to(tmp_path.resolve())
        target.write_bytes(data=image_bytes)
    transport = ToolRoundTransport(path=target, multiple_rounds=True)
    store = (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path / "history")
        if tree_history
        else FilesystemSessionHistoryStore(root=tmp_path / "history")
    )
    session = SloAgentSession(
        workdir=tmp_path,
        session_id="tools-tui",
        history_store=store,
        config=SessionConfigDAO(
            workdir=tmp_path,
            model_name="claude-bridge:claude-haiku-5-5",
            reasoning_level="off",
            enable_history=True,
        ),
        bridge_adapter_class=scripted_adapter_class(transport=transport),
    )
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(PromptInput).text = "Locate and read default model"
        await pilot.press("enter")
        async with asyncio.timeout(10):
            while not transport.closed or session.is_running:
                await pilot.pause()
        await pilot.pause()
        assert any(block.get_copyable_text() == "Hello bridge" for block in app.query(AssistantStreamBlock))
    events = await store.load_events(session_id="tools-tui")
    calls = [e.payload for e in events if e.kind == "tool_call"]
    results = [e.payload for e in events if e.kind == "tool_result"]
    assert {c.tool_name for c in calls} == {"ls", "find", "grep", "read"}
    assert (
        {c.tool_call_id for c in calls}
        == {r.tool_call_id for r in results}
        == {"exact-native-id-1", "exact-native-id-2", "exact-native-id-3", "exact-read"}
    )
    assert [e.payload.content for e in events if e.kind == "assistant_message"][-1] == "Hello bridge"
    assert (
        sum(e.kind == "user_message" for e in events) == sum(e.kind == "run_completed" for e in events) == 1
    )
    assert transport.prompts == ["Locate and read default model"]
    assert transport.round == 3 and len(transport.tool_results) == 4
    assert transport.close_calls == 1
    expected_ids = {"exact-native-id-1", "exact-native-id-2", "exact-native-id-3", "exact-read"}
    assert Counter(c.tool_call_id for c in calls) == Counter({call_id: 1 for call_id in expected_ids})
    assert Counter(r.tool_call_id for r in results) == Counter({call_id: 1 for call_id in expected_ids})
    assert Counter(r["request_id"] for r in transport.tool_results) == Counter(
        {"tool-rpc-1": 1, "tool-rpc-2": 1, "tool-rpc-3": 1, "tool-rpc-read": 1}
    )
    ordered_ids = ["exact-native-id-1", "exact-native-id-2", "exact-native-id-3", "exact-read"]
    assert [c.tool_call_id for c in calls] == ordered_ids
    assert [r.tool_call_id for r in results] == ordered_ids
    assert [r["request_id"] for r in transport.tool_results] == [
        "tool-rpc-1",
        "tool-rpc-2",
        "tool-rpc-3",
        "tool-rpc-read",
    ]
    for result, receipt in zip(results[:3], transport.tool_results[:3], strict=True):
        assert receipt["response"]["mcp_response"]["result"] == {
            "content": [{"type": "text", "text": result.tool_output}],
            "isError": False,
        }
    assert [c.content for c in calls] == [
        "Inspect round 1.",
        "Inspect round 2.",
        "Inspect round 3.",
        "Inspect round 3.",
    ]
    assert [e.payload.content for e in events if e.kind == "assistant_message"] == ["Hello bridge"]
    assert [e.payload.content for e in events if e.kind == "run_completed"] == ["Hello bridge"]
    read_receipt = transport.tool_results[-1]["response"]["mcp_response"]["result"]
    assert read_receipt["isError"] is False
    durable_read = next(r.tool_output for r in results if r.tool_call_id == "exact-read")
    if not read_image:
        assert read_receipt["content"] == [{"type": "text", "text": "default-model = synthetic-model\n"}]
        assert durable_read == "default-model = synthetic-model\n"
        return
    assert read_receipt["content"] == [
        {"type": "image", "mimeType": "image/png", "data": base64.b64encode(image_bytes).decode("ascii")}
    ]
    assert durable_read == f"[image attached: model.png, 1x1, ref {target.resolve()}]"
    encoded_image = base64.b64encode(image_bytes).decode("ascii")
    assert encoded_image not in json.dumps([event.model_dump(mode="json") for event in events])
    for history_file in (tmp_path / "history").rglob("*"):
        if history_file.is_file():
            assert encoded_image.encode("ascii") not in history_file.read_bytes()
