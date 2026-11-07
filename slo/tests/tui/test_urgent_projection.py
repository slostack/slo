"""Exact live/replay interruption correlation through the mounted transcript command."""

from pathlib import Path
from uuid import uuid4

from src.agents.slo_agent.events.stream import AgentStreamEventDAO, StreamEventKind
from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.chat_transcript.commands import PresentAgentEventDAO
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock
from tests.tui.test_prompt_component_protocol import build_session


async def test_exact_attempt_iteration_blocks_ignore_only_matching_late_ends(tmp_path: Path) -> None:
    """A later attempt can reuse block IDs and iteration without inheriting interruption."""
    app = SloTUI(session=build_session(tmp_path=tmp_path))
    first, second = str(uuid4()), str(uuid4())
    async with app.run_test(size=(120, 40)) as pilot:
        transcript = app.query_one(ChatTranscriptComponent)
        script: list[tuple[str, StreamEventKind, str | None]] = [
            (first, "text_delta", "partial-one"),
            (first, "thinking_delta", "plan-one"),
            (second, "text_delta", "partial-two"),
            (second, "thinking_delta", "plan-two"),
            (first, "iteration_interrupted", None),
            (first, "text_end", "WRONG-REPAIR"),
            (first, "thinking_end", "WRONG-PLAN"),
            (first, "run_completed", "WRONG-FINAL"),
            (second, "thinking_end", "repaired-two"),
            (second, "run_completed", "final-two"),
        ]
        for attempt, kind, text in script:
            await transcript.handle(
                command=PresentAgentEventDAO(
                    event=AgentStreamEventDAO(
                        kind=kind,
                        attempt_turn_id=attempt,
                        iteration=0,
                        block_id="shared",
                        delta=text if kind.endswith("delta") else None,
                        content=None if kind.endswith("delta") else text,
                    )
                )
            )
        await pilot.pause()
        blocks = list(app.query(AssistantStreamBlock))
        thinking = list(app.query(AssistantStreamThinkingBlock))
        assert [b.answer_text for b in blocks] == ["partial-one", "final-two"]
        assert [b.thinking_text for b in thinking] == ["plan-one", "repaired-two"]
        assert all(b.finalized for b in blocks + thinking)
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "Response interrupted for urgent input." in painted
        assert "final-two" in painted and "WRONG" not in painted


async def test_interruption_does_not_mark_other_attempt_tool_incomplete(tmp_path: Path) -> None:
    """A partial argument block from another attempt must not inherit interruption."""
    from src.tui.widgets.tool_execution_block import ToolExecutionBlock

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    first, second = str(uuid4()), str(uuid4())
    async with app.run_test(size=(120, 40)):
        transcript = app.query_one(ChatTranscriptComponent)
        for attempt, call in [(first, "first"), (second, "second")]:
            await transcript.handle(
                command=PresentAgentEventDAO(
                    event=AgentStreamEventDAO(
                        kind="tool_call_delta",
                        attempt_turn_id=attempt,
                        iteration=0,
                        tool_call_id=call,
                        tool_name="read",
                        tool_arguments_delta='{"path":"partial',
                    )
                )
            )
        await transcript.handle(
            command=PresentAgentEventDAO(
                event=AgentStreamEventDAO(
                    kind="iteration_interrupted",
                    attempt_turn_id=first,
                    iteration=0,
                )
            )
        )
        blocks = {b.tool_call_id: b for b in app.query(ToolExecutionBlock)}
        assert blocks["first"].is_incomplete
        assert not blocks["second"].is_incomplete


async def test_same_tool_id_after_interruption_has_distinct_live_widget(tmp_path: Path) -> None:
    """Response ownership prevents call-ID reuse and stale arguments repairing old blocks."""
    from src.tui.widgets.tool_execution_block import ToolExecutionBlock

    app = SloTUI(session=build_session(tmp_path=tmp_path))
    attempt = str(uuid4())
    async with app.run_test(size=(120, 40)) as pilot:
        transcript = app.query_one(ChatTranscriptComponent)
        script: list[AgentStreamEventDAO] = [
            AgentStreamEventDAO(
                kind="tool_call_delta",
                attempt_turn_id=attempt,
                iteration=0,
                tool_call_id="shared",
                tool_name="read",
                tool_arguments_delta='{"path":"old',
            ),
            AgentStreamEventDAO(kind="iteration_interrupted", attempt_turn_id=attempt, iteration=0),
            AgentStreamEventDAO(
                kind="tool_call_delta",
                attempt_turn_id=attempt,
                iteration=1,
                tool_call_id="shared",
                tool_name="read",
                tool_arguments_delta='{"path":"new"}',
            ),
            AgentStreamEventDAO(
                kind="tool_call_delta",
                attempt_turn_id=attempt,
                iteration=0,
                tool_call_id="shared",
                tool_name="read",
                tool_arguments_delta='-STALE"}',
            ),
            AgentStreamEventDAO(
                kind="tool_call_end",
                attempt_turn_id=attempt,
                iteration=0,
                tool_call_id="shared",
                tool_name="read",
                tool_input={"path": "STALE"},
            ),
            AgentStreamEventDAO(
                kind="tool_call_end",
                attempt_turn_id=attempt,
                iteration=1,
                tool_call_id="shared",
                tool_name="read",
                tool_input={"path": "new"},
            ),
            AgentStreamEventDAO(
                kind="tool_result",
                attempt_turn_id=attempt,
                iteration=1,
                tool_call_id="shared",
                tool_name="read",
                content="actual result",
            ),
            AgentStreamEventDAO(kind="run_completed", attempt_turn_id=attempt, iteration=1, content="done"),
        ]
        for event in script:
            await transcript.handle(command=PresentAgentEventDAO(event=event))
        await pilot.pause()
        blocks = list(app.query(ToolExecutionBlock))
        assert len(blocks) == 2
        assert blocks[0].is_incomplete and blocks[0].tool_input != {"path": "STALE"}
        assert not blocks[1].is_incomplete and blocks[1].tool_input == {"path": "new"}
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert blocks[0].result_output is None and blocks[1].result_output == "actual result"
        assert "done" in painted and "STALE" not in painted
