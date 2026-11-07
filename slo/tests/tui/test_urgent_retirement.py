"""Real SQLite admission uncertainty retains urgent identity across editor retirement."""

import asyncio
from pathlib import Path

from langchain_core.messages import AIMessage

from src.agents.slo_agent.messaging.dao import MessagingLimitsDAO
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate
from tests.integration.test_messaging_yield import isolated_journey_tasks
from tests.tui.test_composer_prerequisites import gated_session
from tests.tui.test_durable_composer import _wait_until
from src.tui.app import SloTUI


async def test_urgent_unknown_retirement_keeps_same_bytes_and_new_editor(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """Reset cannot guess a replacement ID or restore an old urgent draft over successor text."""
    gate = CompletionGate(hold_before=True)
    model = RecordingModel(responses=[AIMessage(content="once")])
    session = gated_session(
        tmp_path=tmp_path, model=model, gate=gate, limits=MessagingLimitsDAO(admission_seconds=0.05)
    )
    app = SloTUI(session=session, messaging_enabled=True)
    reset: asyncio.Task[None] | None = None
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(PromptInputComponent)
            gate.armed = True
            prompt.insert(text="immutable urgent")
            await pilot.press("ctrl+enter")
            await _wait_until(predicate=lambda: bool(prompt.list_recoverable_drafts()))
            original = prompt.list_recoverable_drafts()[0].draft_submission.message_submission
            encoded = original.model_dump_json()
            assert original.priority == "urgent"
            reset = asyncio.create_task(coro=prompt.reset())
            await _wait_until(predicate=lambda: prompt.text == "")
            gate.release.set()
            await reset
            await pilot.press("n", "e", "w")
            drafts = prompt.list_recoverable_drafts()
            assert len(drafts) == 1
            assert drafts[0].draft_submission.message_submission.model_dump_json() == encoded
            assert prompt.text == "new"
            prompt.load_text(f"/messages retry {original.message_id[:8]}")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: not prompt.list_recoverable_drafts())
            await pilot.press("n", "e", "w")
            model.release.set()
            await _wait_until(predicate=lambda: not session.is_running)
            assert prompt.text == "new"
            assert len(model.requests) == 1
    finally:
        gate.release.set()
        model.release.set()
        if reset is not None:
            await asyncio.gather(reset, return_exceptions=True)
        await session.close_messaging()
