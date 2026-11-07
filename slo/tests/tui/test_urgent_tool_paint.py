"""Native mounted paint while a real local offloaded tool leaf is held."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.tools._blocking import run_blocking_tool_call
from src.agents.tools.tool_output import ToolOutputUpdateDAO
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory, RecordingModel
from tests.integration.test_messaging_yield import isolated_journey_tasks
from tests.tui.test_durable_composer import _wait_until


@pytest.mark.parametrize(argnames="theme", argvalues=["slo-default", "slo-dark"])
@pytest.mark.parametrize(argnames="size", argvalues=[(60, 20), (80, 24), (120, 40)])
async def test_offloaded_leaf_paints_before_release(
    tmp_path: Path, theme: str, size: tuple[int, int], isolated_journey_tasks: None
) -> None:
    """Editing and a painted tool snapshot precede leaf release in every required viewport."""
    entered = threading.Event()
    release = threading.Event()
    joined = threading.Event()
    effect = tmp_path / "effect.txt"
    assert effect.resolve().is_relative_to(tmp_path.resolve())

    def write_effect() -> str:
        """Hold a real worker thread, then write only the test-owned regular file."""
        entered.set()
        try:
            assert release.wait(timeout=20)
            effect.write_text(data="actual effect", encoding="utf-8")
            return "actual result"
        finally:
            joined.set()

    @tool
    async def held_write(config: RunnableConfig) -> str:
        """Publish live output then perform an actual off-loop file effect."""
        callback = config["configurable"]["slo_tool_output_update_callback"]
        await callback(
            snapshot=ToolOutputUpdateDAO(
                tool_call_id="", tool_name="", content_snapshot="PAINT-BEFORE-RELEASE"
            )
        )
        return await run_blocking_tool_call(func=write_effect)

    model = RecordingModel(
        responses=[
            AIMessage(content="", tool_calls=[{"id": "held", "name": "held_write", "args": {}}]),
            AIMessage(content="Urgent handled"),
        ]
    )
    model.release.set()
    root = tmp_path / "history"
    session_id = str(uuid4())
    history = FilesystemSessionHistoryStore(root=root)
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=history,
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path, tools=[held_write]),
    )
    app = SloTUI(session=session, messaging_enabled=True)
    app.theme = theme
    try:
        async with app.run_test(size=size) as pilot:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(PromptInputComponent)
            initial_region = prompt.region
            prompt.insert(text="Write")
            await pilot.press("enter")
            await _wait_until(predicate=entered.is_set)
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "PAINT-BEFORE-RELEASE" in painted
            assert not release.is_set() and not effect.exists()
            await pilot.press("u", "r", "g", "e", "n", "t", "alt+u")
            await _wait_until(predicate=lambda: prompt.text == "")
            await pilot.press("n", "e", "w")
            await pilot.pause()
            painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
            assert "new" in painted
            assert "delivery deferred" in painted
            assert prompt.text == "new" and prompt.has_focus
            assert prompt.region == initial_region
            assert not joined.is_set() and len(model.requests) == 1
            release.set()
            await _wait_until(
                predicate=lambda: joined.is_set() and len(model.requests) == 2 and not session.is_running
            )
            assert effect.read_text(encoding="utf-8") == "actual effect"
            events = await history.load_events(session_id=session_id)
            results = [e for e in events if e.kind == "tool_result"]
            assert len(results) == 1 and results[0].payload.tool_output == "actual result"
            deferred = [
                e
                for e in events
                if e.payload.metadata.get("cooperative_yield_v1", {}).get("disposition") == "deferred"
            ]
            assert len(deferred) == 1
    finally:
        release.set()
        await session.close_messaging()
    assert joined.is_set()
