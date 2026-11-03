"""Messaging steering follows the ordinary durable composer admission path."""

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.widgets.user_message_block import UserMessageBlock
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.tui.test_durable_composer import _build_factory_session, _wait_until


async def test_steer_uses_normal_admission_in_messaging_session(tmp_path: Path) -> None:
    """A held run receives one normal instruction, with one echo and accepted recall."""
    model = RecordingModel(responses=[AIMessage(content="first"), AIMessage(content="adjusted")])
    session = _build_factory_session(tmp_path=tmp_path, model=model, stop_after_first=False)
    app = SloTUI(session=session, messaging_enabled=True)
    async with app.run_test() as pilot:
        try:
            prompt = app.query_one(PromptInputComponent)
            await _wait_until(predicate=lambda: app._messaging_session is session)
            prompt.load_text("initial")
            await pilot.press("enter")
            await asyncio.wait_for(model.entered.wait(), timeout=3)
            prompt.load_text("/steer adjust")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: app._queued_prompt_block is not None)
            assert app._queued_prompt_block is not None
            assert "adjust" in str(app._queued_prompt_block.render())
            model.release.set()
            await _wait_until(predicate=lambda: len(model.requests) == 2 and not session.is_running)
            await pilot.pause()
            assert [block.text for block in app.query(UserMessageBlock)] == ["initial", "adjust"]
            assert [
                message.content for message in model.requests[-1] if isinstance(message, HumanMessage)
            ] == ["initial", "adjust"]
            assert session._history_store is not None
            events = await session._history_store.load_events(session_id=session.session_id)
            applied = [
                event
                for event in events
                if event.kind == "workflow_update" and event.payload.content == "adjust"
            ]
            assert len(applied) == 1
            assert applied[0].payload.metadata["messaging_v1"]["kind"] == "agent_input"
            assert not [event for event in events if event.kind == "steering_message"]
        finally:
            model.release.set()
