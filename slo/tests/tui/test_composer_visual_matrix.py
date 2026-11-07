"""DC09 mounted geometry and liveness across the complete theme/size matrix."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.tui.app import SloTUI
from tests.cli.test_app import compose_default_tui
from src.tui.components.prompt_input.component import PromptInputComponent
from src.tui.widgets.queued_prompt_block import QueuedPromptBlock
from tests.agents.slo_agent.messaging.test_delivery import RecordingModel
from tests.agents.slo_agent.messaging.test_queue_closure import CompletionGate
from tests.tui.test_composer_prerequisites import gated_session
from tests.tui.test_durable_composer import _wait_until
from tests.tui.test_prompt_component_protocol import build_session
from src.agents.slo_agent.messaging.dao import MessagingLimitsDAO
from src.tui.components.prompt_input.commands import ClearSubmissionDAO, RecordAcceptedPromptDAO


@pytest.mark.parametrize(argnames="theme", argvalues=["slo-dark", "slo-default"])
@pytest.mark.parametrize(argnames="size", argvalues=[(60, 20), (80, 24), (120, 40)])
async def test_geometry_focus_recall_and_band_match_baseline(
    tmp_path: Path, theme: str, size: tuple[int, int]
) -> None:
    """Editor, literal multiline recall and band anchor match the retained legacy composition."""
    regions = []
    literal = "[literal]\nsecond [line]"
    for messaging in (False, True):
        root = tmp_path / ("messaging" if messaging else "legacy")
        session = build_session(tmp_path=root)
        app = (
            compose_default_tui(session=session)
            if messaging
            else SloTUI(session=session, messaging_enabled=False)
        )
        app.theme = theme
        async with app.run_test(size=size) as pilot:
            await pilot.pause()
            if messaging:
                await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(PromptInputComponent)
            assert app.focused is prompt
            mounted_region = prompt.region
            await prompt.handle(command=RecordAcceptedPromptDAO(text=literal))
            await prompt.handle(command=ClearSubmissionDAO())
            await pilot.press("up")
            assert prompt.text == literal
            prompt.load_text("[literal]")
            prompt.move_cursor((0, len("[literal]")))
            await pilot.press("shift+enter")
            await pilot.press("x")
            assert prompt.text == "[literal]\nx"
            await prompt.handle(command=ClearSubmissionDAO())
            # Both production band routes converge on the retained visual helper.
            if messaging:
                assert app._messaging_client is not None
                await session._lock.acquire()
                try:
                    from tests.agents.slo_agent.messaging.test_queue_closure import submission

                    await app._messaging_client.submit(
                        submission=submission(target=session.messaging_target, text="next [literal]")
                    )
                    await _wait_until(predicate=lambda: bool(app.query(QueuedPromptBlock)))
                    await pilot.pause()
                    band = app.query_one(QueuedPromptBlock)
                    regions.append((mounted_region, prompt.region, band.region))
                finally:
                    session._lock.release()
            else:
                await app._queue_prompt(text="next [literal]")
                await pilot.pause()
                band = app.query_one(QueuedPromptBlock)
                regions.append((mounted_region, prompt.region, band.region))
            assert band.region.bottom + 1 == prompt.region.y
            assert app.focused is prompt
    assert regions[0] == regions[1]


@pytest.mark.parametrize(argnames="theme", argvalues=["slo-dark", "slo-default"])
@pytest.mark.parametrize(argnames="size", argvalues=[(60, 20), (80, 24), (120, 40)])
@pytest.mark.parametrize(argnames="held", argvalues=["provider", "admission"])
async def test_keyboard_and_paint_progress_while_work_is_held(
    tmp_path: Path, theme: str, size: tuple[int, int], held: str
) -> None:
    """Twenty individual keys and bounded paint waits progress before either worker releases."""
    gate = CompletionGate(hold_before=True)
    model = RecordingModel(responses=[AIMessage(content="done")])
    session = gated_session(tmp_path=tmp_path, model=model, gate=gate, limits=MessagingLimitsDAO())
    app = compose_default_tui(session=session)
    app.theme = theme
    async with app.run_test(size=size) as pilot:
        try:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(PromptInputComponent)
            gate.armed = held == "admission"
            prompt.load_text("submitted [literal]")
            await pilot.press("enter")
            if held == "admission":
                await _wait_until(predicate=gate.started.is_set)
            else:
                await asyncio.wait_for(model.entered.wait(), timeout=3)
            typed = "abcdefghijklmnopqrst"
            for index, key in enumerate(typed, start=1):
                await asyncio.wait_for(pilot.press(key), timeout=2)
                await asyncio.wait_for(pilot.pause(), timeout=2)
                assert prompt.text == typed[:index]
            assert not model.release.is_set()
            if held == "admission":
                assert not model.requests and not gate.release.is_set()
            gate.release.set()
            model.release.set()
            await _wait_until(predicate=lambda: len(model.requests) == 1 and not session.is_running)
            assert [
                message.content for message in model.requests[0] if isinstance(message, HumanMessage)
            ] == ["submitted [literal]"]
            assert prompt.text == typed
            assert app._in_flight_task is None and app._queued_prompt_text is None
        finally:
            gate.release.set()
            model.release.set()
