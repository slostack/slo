"""Pre-mutation snapshot transport at real mounted stream-widget boundaries."""

from collections.abc import Callable

import pytest
from textual.app import App, ComposeResult

from src.tui.theme import SLO_DEFAULT_THEME
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock, FollowSnapshotDAO
from src.tui.widgets.assistant_stream_thinking_block import AssistantStreamThinkingBlock


class SnapshotApp(App[None]):
    """Record delivered notifications without replacing the widgets' render path."""

    def __init__(self, *, block: AssistantStreamBlock | AssistantStreamThinkingBlock) -> None:
        """Borrow one real block and collect its exact messages for this mount."""
        super().__init__()
        self.block = block
        self.messages: list[AssistantStreamBlock.Rendered] = []
        self.register_theme(SLO_DEFAULT_THEME)
        self.theme = SLO_DEFAULT_THEME.name

    def compose(self) -> ComposeResult:
        """Mount the stream widget with no component message consumer."""
        yield self.block

    def on_assistant_stream_block_rendered(self, message: AssistantStreamBlock.Rendered) -> None:
        """Retain the actual queued message, not a reconstructed snapshot."""
        self.messages.append(message)


@pytest.mark.parametrize("terminal", ["abort", "fail"])
@pytest.mark.parametrize("pending", [False, True])
async def test_terminal_warning_captures_once_before_any_render(terminal: str, pending: bool) -> None:
    """Warning-only and dirty-answer terminal updates share one pre-mutation capture."""
    snapshot = FollowSnapshotDAO(was_following=True, presentation_generation=7, viewport_revision=9)
    observations: list[tuple[str, bool]] = []

    def capture() -> FollowSnapshotDAO:
        """Observe the visible body and warning at the supplied owner boundary."""
        observations.append((block.visible_answer_text, block._terminal_note.display))
        return snapshot

    block = AssistantStreamBlock(follow_snapshot=capture)
    app = SnapshotApp(block=block)
    async with app.run_test() as pilot:
        if pending:
            block.append_text(delta="pending answer")
        if terminal == "abort":
            block.mark_aborted()
        else:
            block.mark_failed(error_message="test failure")
        assert observations == [("", False)]
        assert block.visible_answer_text == ("pending answer" if pending else "")
        assert block.terminal_note_text == ("(aborted)" if terminal == "abort" else "(error: test failure)")
        await pilot.pause()
        assert len(app.messages) == 1
        assert app.messages[0].snapshot is snapshot
        assert app.messages[0].source is block
        assert block._flush_timer is None


async def test_thinking_expansion_captures_before_visibility_and_transports_identity() -> None:
    """A direct expansion is a layout mutation even when no new text is dirty."""
    snapshot = FollowSnapshotDAO(was_following=False, presentation_generation=2, viewport_revision=4)
    observations: list[bool] = []

    def capture() -> FollowSnapshotDAO:
        """Record visible state before the requested visibility change."""
        observations.append(block._body.display)
        return snapshot

    block = AssistantStreamThinkingBlock(follow_snapshot=capture)
    block.set_thinking(content="reasoning")
    app = SnapshotApp(block=block)
    async with app.run_test() as pilot:
        block.set_expanded(expanded=False)
        assert observations == [True]
        assert not block._body.display
        await pilot.pause()
        assert len(app.messages) == 1
        assert app.messages[0].snapshot is snapshot
        assert app.messages[0].source is block


@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("terminal", [False, True])
async def test_stream_flush_transports_exact_pre_mutation_snapshot(thinking: bool, terminal: bool) -> None:
    """Both timer and terminal flushes capture the old visible buffer exactly once."""
    snapshot = FollowSnapshotDAO(was_following=True, presentation_generation=2, viewport_revision=3)
    observations: list[str] = []
    visible: Callable[[], str]

    def capture() -> FollowSnapshotDAO:
        """Observe the old painted buffer through the explicit borrowed callback."""
        observations.append(visible())
        return snapshot

    block: AssistantStreamBlock | AssistantStreamThinkingBlock
    if thinking:
        block = AssistantStreamThinkingBlock(follow_snapshot=capture)
        visible = lambda: block.get_copyable_text()
    else:
        block = AssistantStreamBlock(follow_snapshot=capture)
        visible = lambda: block.visible_answer_text if isinstance(block, AssistantStreamBlock) else ""
    app = SnapshotApp(block=block)
    async with app.run_test() as pilot:
        if isinstance(block, AssistantStreamBlock):
            block.append_text(delta="first")
            block.append_text(delta=" second")
        else:
            block.append_thinking(delta="first")
            block.append_thinking(delta=" second")
        if terminal:
            block.seal()
        await pilot.pause()
        assert observations == [""]
        assert "first" in block.get_copyable_text()
        assert len(app.messages) == 1
        assert app.messages[0].snapshot is snapshot
        assert app.messages[0].source is block
