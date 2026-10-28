"""Mounted presentation journeys using the existing real session/history fixtures."""

import asyncio
from pathlib import Path

import pytest

from textual.widgets import Static
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.transcript import ReplayEntryProjector

from textual.app import App, ComposeResult

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.components.chat_transcript.component import ChatTranscript, HistoryReader
from src.tui.theme import SLO_DEFAULT_THEME
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.user_message_block import UserMessageBlock
from tests.tui.test_replay_resume import _build_session_with_history, _drain_session


async def seed_history(*, root: Path, count: int) -> list[TranscriptEntryDAO]:
    """Persist actual assistant events and read canonical replay entries back."""
    store = FilesystemSessionHistoryStore(root=root)
    await store.ensure_session(session_id="seed", workdir=root, model_name=None)
    for index in range(count):
        await store.append_event(
            event=SessionHistoryEventDAO(
                session_id="seed",
                kind="assistant_message",
                iteration=index,
                turn_id=f"turn-{index}",
                payload=SessionHistoryEventPayloadDAO(content=f"entry-{index:02}"),
            )
        )
    return ReplayEntryProjector.build_entries(events=await store.load_events(session_id="seed"))


async def test_terminal_growth_follows_and_hidden_growth_retains_reading() -> None:
    """Final output follows without a rescue delta; hide/show preserves reading."""

    async def empty_history() -> list[TranscriptEntryDAO]:
        """Supply an empty canonical history boundary."""
        return []

    transcript = ChatTranscript(history_reader=empty_history)
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test(size=(80, 24)) as pilot:
        await transcript.echo_user(text="question")
        block = await transcript.mount_assistant_block()
        block.finalize(final_text="\n\n".join(f"line-{index:03}" for index in range(80)))
        await pilot.pause()
        await pilot.pause()
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "line-079" in painted, (
            transcript._capture_follow_snapshot(),
            transcript._active_pin,
            transcript._transcript_scroll.scroll_y,
            transcript._transcript_scroll.max_scroll_y,
        )
        scroll = transcript.query_one("#transcript-scroll")
        scroll.focus()
        await pilot.press("pageup")
        await pilot.pause()
        before = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        transcript.set_visible(visible=False)
        transcript.write_transcript_line(content="hidden-tail", classes="tool-result")
        await pilot.pause()
        transcript.set_visible(visible=True)
        await pilot.pause()
        after = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert after == before
        transcript.scroll_to_bottom()
        await pilot.pause()
        assert "hidden-tail" in "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def test_production_app_mounts_single_component_and_routes_parent_output(tmp_path: Path) -> None:
    """The actual application mounts the owner and delivers a persisted live turn once."""
    from src.tui.app import SloTUI

    session = _build_session_with_history(
        workdir=tmp_path,
        history_root=tmp_path / "history",
        responses=[FauxChatModel.assistant_message(content="cutover-answer")],
    )
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        transcript = app.query_one(ChatTranscript)
        await app._submit_or_queue_prompt(text="cutover-question")
        await pilot.pause()
        if app._in_flight_task is not None:
            await app._in_flight_task
        await pilot.pause()
        assert len(app.query(ChatTranscript)) == 1
        assert transcript.query_one(UserMessageBlock).get_copyable_text() == "cutover-question"
        assert transcript.query_one(AssistantStreamBlock).get_copyable_text() == "cutover-answer"
        await app.action_clear()
        assert transcript.logical_copy_text() == ""
    entries = await session.hydrate_transcript_entries()
    assert sum(entry.content == "cutover-question" for entry in entries) == 1
    assert sum(entry.answer == "cutover-answer" for entry in entries) == 1


class TranscriptTestApp(App[None]):
    """Mount the production component without the production app stylesheet."""

    def __init__(self, *, transcript: ChatTranscript) -> None:
        """Borrow the component for this one Pilot lifetime."""
        super().__init__()
        self.transcript = transcript
        self.register_theme(SLO_DEFAULT_THEME)
        self.theme = SLO_DEFAULT_THEME.name

    def compose(self) -> ComposeResult:
        """Mount only the real presentation boundary."""
        yield self.transcript


async def test_mounted_history_tail_is_read_only_and_live_turn_is_persisted_once(tmp_path: Path) -> None:
    """Replay the newest 30 entries, then deliver a real Faux session turn once."""
    session = _build_session_with_history(
        workdir=tmp_path,
        history_root=tmp_path / "history",
        responses=[FauxChatModel.assistant_message(content=f"answer-{index:02}") for index in range(17)],
    )
    for index in range(16):
        await _drain_session(session=session, text=f"question-{index:02}")
    history_file = tmp_path / "history" / session.session_id / "events.jsonl"
    before = history_file.read_bytes()
    transcript = ChatTranscript(history_reader=session.hydrate_transcript_entries)
    app = TranscriptTestApp(transcript=transcript)

    async with app.run_test() as pilot:
        await transcript.hydrate()
        await transcript.hydrate()
        await pilot.pause()
        assert history_file.read_bytes() == before
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == [
            f"question-{index:02}" for index in range(1, 16)
        ]
        assert [block.get_copyable_text() for block in transcript.query(AssistantStreamBlock)] == [
            f"answer-{index:02}" for index in range(1, 16)
        ]
        transcript.begin_run()
        await transcript.echo_user(text="live-question")
        async for event in session.invoke(text="live-question"):
            await transcript.present_event(event=event)
        await pilot.pause()
        assert transcript.query(UserMessageBlock).last().get_copyable_text() == "live-question"
        assert transcript.query(AssistantStreamBlock).last().get_copyable_text() == "answer-16"
        assert transcript.logical_copy_text().count("> live-question") == 1
        transcript.query_one("#transcript-scroll").scroll_end(animate=False)
        await pilot.pause()
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert "answer-16" in painted

    entries = await session.hydrate_transcript_entries()
    assert sum(entry.content == "live-question" for entry in entries) == 1
    assert sum(entry.answer == "answer-16" for entry in entries) == 1


async def test_failed_initial_history_read_leaves_mounted_surface_usable() -> None:
    """An unavailable reader does not prevent the next accepted user echo."""

    async def unavailable_history() -> list[TranscriptEntryDAO]:
        """Fail at the injected read boundary, without replacing projection."""
        raise OSError("history unavailable")

    transcript = ChatTranscript(history_reader=unavailable_history)
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        await transcript.hydrate()
        await transcript.echo_user(text="still usable")
        await pilot.pause()
        assert transcript.query_one(UserMessageBlock).get_copyable_text() == "still usable"


@pytest.mark.parametrize("operation", ["clear", "bind", "close"])
async def test_initial_read_cannot_publish_after_lifecycle_reset(tmp_path: Path, operation: str) -> None:
    """A cancellation-suppressing real-store read cannot publish into a reset lifetime."""
    session = _build_session_with_history(
        workdir=tmp_path,
        history_root=tmp_path / "history",
        responses=[FauxChatModel.assistant_message(content="old answer")],
    )
    await _drain_session(session=session, text="old question")
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def gated_reader() -> list[TranscriptEntryDAO]:
        """Retain genuine replay bytes across a deliberately delayed cancellation."""
        entries = await session.hydrate_transcript_entries()
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            await release.wait()
        return entries

    transcript = ChatTranscript(history_reader=gated_reader)
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        hydration = asyncio.create_task(transcript.hydrate())
        await asyncio.wait_for(entered.wait(), timeout=5)
        try:
            if operation == "bind":
                cleanup = asyncio.create_task(
                    transcript.bind_history(history_reader=session.hydrate_transcript_entries)
                )
            else:
                cleanup = asyncio.create_task(getattr(transcript, operation)())
        except BaseException:
            release.set()
            await hydration
            raise
        try:
            await asyncio.wait_for(cancelled.wait(), timeout=5)
            delivery = asyncio.create_task(transcript.echo_user(text="after reset"))
            await asyncio.sleep(0)
            assert not cleanup.done()
            assert not delivery.done()
            cleanup.cancel()
            await asyncio.sleep(0)
            assert not cleanup.done()
        finally:
            release.set()
            await asyncio.gather(hydration, cleanup, return_exceptions=True)
        await delivery
        await pilot.pause()
        expected = [] if operation == "close" else ["after reset"]
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == expected
        assert not list(transcript.query(AssistantStreamBlock))
        assert "old question" not in transcript.logical_copy_text()
        if operation == "bind":
            await transcript.hydrate()
            assert transcript.query_one(AssistantStreamBlock).get_copyable_text() == "old answer"


async def test_history_loads_30_then_30_then_5_without_writes(tmp_path: Path) -> None:
    """A real 65-entry history is published once in complete chronological order."""
    entries = await seed_history(root=tmp_path / "history", count=65)
    assert len(entries) == 65
    history = tmp_path / "history" / "seed" / "events.jsonl"
    original = history.read_bytes()

    async def read_history() -> list[TranscriptEntryDAO]:
        """Return the canonical real-store projection."""
        return entries

    transcript = ChatTranscript(history_reader=read_history)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        for start in (35, 5, 0):
            await pilot.pause()
            assert [block.get_copyable_text() for block in transcript.query(AssistantStreamBlock)] == [
                f"entry-{index:02}" for index in range(start, 65)
            ]
            if start:
                assert str(transcript.query_one("#transcript-earlier-summary").render()).find(str(start)) >= 0
            await transcript.load_older()
        assert not list(transcript.query("#transcript-earlier-summary"))
        assert history.read_bytes() == original


async def test_window_501st_mount_and_terminal_do_not_deadlock() -> None:
    """Real 500/10 window removes settled prefix but retains live blocks and newest text."""

    async def empty_history() -> list[TranscriptEntryDAO]:
        """No persisted entries exist for this live-only journey."""
        return []

    transcript = ChatTranscript(history_reader=empty_history)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.present_event(
            event=AgentStreamEventDAO(kind="text_delta", delta="live", iteration=0)
        )
        live = transcript.query_one(AssistantStreamBlock)
        for index in range(510):
            transcript.write_transcript_line(content=f"notice-{index}", classes="tool-result")
        await asyncio.wait_for(
            transcript.present_event(event=AgentStreamEventDAO(kind="text_end")), timeout=5
        )
        await pilot.pause()
        content = transcript.query_one("#transcript-content")
        ordinary = [child for child in content.children if child.id != "transcript-earlier-summary"]
        assert len(ordinary) == 500
        assert live in ordinary and not live.finalized
        assert [str(child.render()) for child in ordinary[-10:]] == [f"notice-{i}" for i in range(500, 510)]
        assert "notice-0" in transcript.logical_copy_text()
        await asyncio.wait_for(
            transcript.present_event(event=AgentStreamEventDAO(kind="run_completed")), timeout=5
        )


async def test_tree_and_steering_are_separate_from_clear_and_expansion() -> None:
    """Clear drops ordinary/pending content but retains tree identity and expansion policy."""

    async def empty_history() -> list[TranscriptEntryDAO]:
        """Supply an empty read-only history."""
        return []

    transcript = ChatTranscript(history_reader=empty_history)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        tree = Static("tree")
        await transcript.mount_tree_output(widget=tree)
        await transcript.show_pending_steering(message="first")
        await transcript.show_pending_steering(message="second")
        await transcript.present_event(event=AgentStreamEventDAO(kind="steering_applied", content="first"))
        assert len(list(transcript.query("SteeringPendingBlock"))) == 1
        assert transcript.query_one(UserMessageBlock).get_copyable_text() == "first"
        transcript.toggle_expandable_details()
        await transcript.clear()
        await pilot.pause()
        assert tree.parent is transcript.query_one("#transcript-scroll")
        assert not list(transcript.query_one("#transcript-content").children)
        assert transcript.logical_copy_text() == ""
        await transcript.present_event(
            event=AgentStreamEventDAO(kind="steering_applied", content="unmatched")
        )
        assert transcript.query_one(UserMessageBlock).get_copyable_text() == "unmatched"


@pytest.mark.parametrize("operation", ["clear", "bind", "close"])
async def test_older_read_cannot_publish_after_reset(tmp_path: Path, operation: str) -> None:
    """Late older results are invalidated and pending live delivery waits for cleanup."""
    entries = await seed_history(root=tmp_path / "history", count=65)
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    reads = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Gate only older reads, retaining canonical entries after cancellation."""
        nonlocal reads
        reads += 1
        if reads > 1:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
        return entries

    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        older = asyncio.create_task(transcript.load_older())
        await asyncio.wait_for(entered.wait(), timeout=5)
        repeated = asyncio.create_task(transcript.load_older())
        cleanup = asyncio.create_task(
            transcript.bind_history(history_reader=reader)
            if operation == "bind"
            else getattr(transcript, operation)()
        )
        try:
            await asyncio.wait_for(cancelled.wait(), timeout=5)
            delivery = asyncio.create_task(transcript.echo_user(text="new lifetime"))
            await asyncio.sleep(0)
            assert not delivery.done()
            assert reads == 2
        finally:
            release.set()
            await asyncio.gather(older, repeated, cleanup, return_exceptions=True)
        await delivery
        await pilot.pause()
        assert not list(transcript.query(AssistantStreamBlock))
        assert not list(transcript.query("#transcript-earlier-summary"))
        assert [b.get_copyable_text() for b in transcript.query(UserMessageBlock)] == (
            [] if operation == "close" else ["new lifetime"]
        )


class FailingOlderTranscript(ChatTranscript):
    """Inject a failure at the existing public mount boundary, never the projector."""

    fail_older: bool = False
    older_mounts: int = 0

    async def mount_assistant_block(
        self, *, title_prefix: str | None = None, before: int | None = None
    ) -> AssistantStreamBlock:
        """Retain one older message and an unrelated notice before failing the next."""
        if before is not None:
            self.older_mounts += 1
            if self.fail_older and self.older_mounts == 2:
                self.workflow_notice.write(content="concurrent notice", classes="tool-result")
                raise RuntimeError("private failure detail")
        return await super().mount_assistant_block(title_prefix=title_prefix, before=before)


async def test_partial_older_failure_retains_prefix_and_suppresses_retry(tmp_path: Path) -> None:
    """Only reset permits another read after partially displayed older history."""
    entries = await seed_history(root=tmp_path / "history", count=65)
    reads = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Count canonical-history reads without replacing persistence."""
        nonlocal reads
        reads += 1
        return entries

    transcript = FailingOlderTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        transcript.fail_older = True
        await transcript.load_older()
        await transcript.load_older()
        await pilot.pause()
        assert reads == 2
        assert [b.get_copyable_text() for b in transcript.query(AssistantStreamBlock)] == [
            "entry-05",
            *[f"entry-{i:02}" for i in range(35, 65)],
        ]
        assert transcript.logical_copy_text().count("concurrent notice") == 1
        assert "private failure detail" not in transcript.logical_copy_text()
        assert str(transcript.query_one("#transcript-earlier-summary").render()) == (
            "▲ earlier messages partially displayed — resume this session to reload history"
        )
        await transcript.clear()
        transcript.fail_older = False
        await transcript.hydrate()
        await transcript.load_older()
        assert reads == 4


@pytest.mark.parametrize("failed_read", ["error", "empty"])
async def test_older_read_failure_is_retryable(tmp_path: Path, failed_read: str) -> None:
    """Read failures preserve the cursor and visible tail, unlike projection failure."""
    entries = await seed_history(root=tmp_path / "history", count=65)
    reads = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Fail once after successful hydration."""
        nonlocal reads
        reads += 1
        if reads == 2:
            if failed_read == "error":
                raise OSError("unavailable")
            return []
        return entries

    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test():
        await transcript.hydrate()
        await transcript.load_older()
        assert len(list(transcript.query(AssistantStreamBlock))) == 30
        await transcript.load_older()
        assert len(list(transcript.query(AssistantStreamBlock))) == 60


async def test_local_adapters_record_without_rendering_and_before_is_visual_only() -> None:
    """Fresh adapters isolate logical lines; workflow notices preserve literal classes/text."""
    from src.tui.components.chat_transcript.adapters.transcript import TranscriptNoticeDisplayAdapter
    from src.tui.components.chat_transcript.adapters.workflow_notice import WorkflowNoticeAdapter

    async def reader() -> list[TranscriptEntryDAO]:
        """No replay is needed for display admission."""
        return []

    transcript = ChatTranscript(history_reader=reader)
    first = TranscriptNoticeDisplayAdapter.register(tui=transcript)
    second = TranscriptNoticeDisplayAdapter.register(tui=transcript)
    first.record(content=first.TURN_SEPARATOR, classes="turn-separator")
    assert not first.has_prior_turn_content() and second.lines == []
    first.record(content="record only", classes="tool-result")
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        assert not list(transcript.query_one("#transcript-content").children)
        first.write(content="tail", classes="tool-result")
        first.write(content="prefix", classes="tool-result", before=0)
        WorkflowNoticeAdapter.register(tui=transcript).write(content="literal [text]", classes="tool-line")
        await pilot.pause()
        children = list(transcript.query_one("#transcript-content").children)
        assert [str(child.render()) for child in children] == ["prefix", "tail", "literal [text]"]
        assert children[-1].has_class("tool-line")
        assert first.lines[-2:] == [("tail", "tool-result"), ("prefix", "tool-result")]
        assert second.lines == []
        await transcript.close()
        transcript.workflow_notice.write(content="late", classes="tool-result")
        assert transcript.logical_copy_text() == ""


class TailNoticeTranscript(ChatTranscript):
    """Inject a synchronous notice during the first older mount."""

    notice_sent: bool = False

    async def mount_user_message_block(self, *, text: str, before: int | None = None) -> UserMessageBlock:
        """Tail growth during AwaitMount must not change the stable prepend boundary."""
        block = await super().mount_user_message_block(text=text, before=before)
        if before is not None and not self.notice_sent:
            self.notice_sent = True
            self.workflow_notice.write(content="concurrent tail", classes="tool-result")
        return block


async def test_successful_older_batch_ignores_concurrent_tail_notice(tmp_path: Path) -> None:
    """Every older user remains after its separator and before its answer and old tail."""
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    await store.ensure_session(session_id="pairs", workdir=tmp_path, model_name=None)
    for index in range(32):
        pairs: list[tuple[HistoryEventKind, str]] = [
            ("user_message", f"question-{index}"),
            ("assistant_message", f"answer-{index}"),
        ]
        for kind, text in pairs:
            await store.append_event(
                event=SessionHistoryEventDAO(
                    session_id="pairs",
                    turn_id=f"turn-{index}",
                    kind=kind,
                    payload=SessionHistoryEventPayloadDAO(content=text),
                )
            )

    async def reader() -> list[TranscriptEntryDAO]:
        """Read canonical pairs from the real disposable store."""
        return ReplayEntryProjector.build_entries(events=await store.load_events(session_id="pairs"))

    transcript = TailNoticeTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        await transcript.load_older()
        await pilot.pause()
        children = list(transcript.query_one("#transcript-content").children)
        expected = []
        for index in range(2, 32):
            if index != 17:
                expected.append("separator")
            expected.extend([f"question-{index}", f"answer-{index}"])
        actual = []
        for child in children[1:-1]:
            if child.has_class("turn-separator"):
                actual.append("separator")
            else:
                assert isinstance(child, (UserMessageBlock, AssistantStreamBlock))
                actual.append(child.get_copyable_text())
        assert actual == expected
        assert str(children[-1].render()) == "concurrent tail"
        assert transcript.logical_copy_text().count("concurrent tail") == 1


@pytest.mark.parametrize("theme_name", ["default", "dark"])
@pytest.mark.parametrize("size", [(60, 20), (80, 24), (120, 40)])
async def test_component_css_is_scoped_without_app_styles(theme_name: str, size: tuple[int, int]) -> None:
    """Both themes render component semantics without styling an unrelated sibling."""
    from src.tui.theme import SLO_DARK_THEME

    async def reader() -> list[TranscriptEntryDAO]:
        """No history is needed to inspect mounted semantic styling."""
        return []

    transcript = ChatTranscript(history_reader=reader)
    app = TranscriptTestApp(transcript=transcript)
    app.register_theme(SLO_DARK_THEME)
    app.theme = SLO_DARK_THEME.name if theme_name == "dark" else SLO_DEFAULT_THEME.name
    async with app.run_test(size=size) as pilot:
        sibling = Static("outside", classes="tool-line")
        await app.mount(sibling)
        transcript.write_transcript_line(content="inside", classes="tool-line")
        await pilot.pause()
        inside = transcript.query_one(".tool-line")
        assert inside.styles.color != sibling.styles.color
        assert transcript.query_one("#transcript-content").styles.padding == (1, 1, 0, 1)
        assert inside.region.width > 0
        assert "inside" in "\n".join(strip.text for strip in app.screen._compositor.render_strips())


async def test_protected_saturation_does_not_busy_loop() -> None:
    """Pending tools may exceed the real cap; terminal results permit later convergence."""

    async def reader() -> list[TranscriptEntryDAO]:
        """Supply empty history for a live-only saturation case."""
        return []

    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        for index in range(501):
            await transcript.present_event(
                event=AgentStreamEventDAO(
                    kind="tool_call_end", tool_call_id=f"tool-{index}", tool_name="read", tool_input={}
                )
            )
        await asyncio.wait_for(pilot.pause(), timeout=5)
        assert len(list(transcript.query("ToolExecutionBlock"))) == 501
        assert transcript._window_task is None  # task-settlement observation, not injected state
        for index in range(2):
            await transcript.present_event(
                event=AgentStreamEventDAO(
                    kind="tool_result", tool_call_id=f"tool-{index}", tool_name="read", content="done"
                )
            )
        await pilot.pause()
        assert len(list(transcript.query("ToolExecutionBlock"))) == 500


async def test_hidden_surface_retains_identity_and_accepts_output_without_reread() -> None:
    """Visibility is presentation only: hidden updates survive, clear keeps visibility."""
    reads = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Observe that hide/show never rehydrates."""
        nonlocal reads
        reads += 1
        return []

    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        await transcript.present_event(event=AgentStreamEventDAO(kind="text_delta", delta="before"))
        block = transcript.query_one(AssistantStreamBlock)
        transcript.set_visible(visible=False)
        await transcript.present_event(event=AgentStreamEventDAO(kind="text_delta", delta=" after"))
        await transcript.present_event(event=AgentStreamEventDAO(kind="run_completed"))
        await pilot.pause()
        assert not transcript.display
        transcript.set_visible(visible=True)
        await pilot.pause()
        assert transcript.query_one(AssistantStreamBlock) is block
        assert block.get_copyable_text() == "before after"
        assert reads == 1
        transcript.set_visible(visible=False)
        await transcript.clear()
        assert not transcript.display
        transcript.set_visible(visible=True)
        await pilot.pause()
        assert not list(transcript.query(AssistantStreamBlock))


class GatedProjectionTranscript(ChatTranscript):
    """Hold a public mount while lifecycle admission waits behind live delivery."""

    def __init__(self, *, history_reader: HistoryReader) -> None:
        """Create explicit scheduling barriers for this mounted test."""
        super().__init__(history_reader=history_reader)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def mount_user_message_block(self, *, text: str, before: int | None = None) -> UserMessageBlock:
        """Pause only the first echo after its real widget is mounted."""
        block = await super().mount_user_message_block(text=text, before=before)
        if text == "held":
            self.entered.set()
            await self.release.wait()
        return block


@pytest.mark.parametrize("operation", ["clear", "bind", "close"])
async def test_lifecycle_waits_for_admitted_projection(operation: str) -> None:
    """Already-admitted live work finishes before reset; later work is not lost."""

    async def reader() -> list[TranscriptEntryDAO]:
        """No history is needed for a live mount ordering check."""
        return []

    transcript = GatedProjectionTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        echo = asyncio.create_task(transcript.echo_user(text="held"))
        await asyncio.wait_for(transcript.entered.wait(), timeout=5)
        cleanup = asyncio.create_task(
            transcript.bind_history(history_reader=reader)
            if operation == "bind"
            else getattr(transcript, operation)()
        )
        await asyncio.sleep(0)
        assert not cleanup.done()
        later = asyncio.create_task(transcript.echo_user(text="later"))
        transcript.release.set()
        await asyncio.wait_for(asyncio.gather(echo, cleanup, later), timeout=5)
        await pilot.pause()
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == (
            [] if operation == "close" else ["later"]
        )


async def test_hidden_programmatic_scroll_does_not_change_geometry() -> None:
    """Public and direct framework starts cannot move a hidden transcript."""
    from src.tui.components.chat_transcript.component import TranscriptScroll

    async def reader() -> list[TranscriptEntryDAO]:
        """Supply no replay for the native geometry journey."""
        return []

    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.finalize(final_text="\n\n".join(f"line-{i}" for i in range(100)))
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        transcript.set_visible(visible=False)
        before = scroll.scroll_y
        scroll.scroll_to(y=0, animate=False, immediate=True)
        assert scroll.scroll_y == before
        scroll._scroll_to(y=0, animate=False)
        assert scroll.scroll_y == before


class FailingInitialTranscript(ChatTranscript):
    """Fail a public replay mount once, after a visible prefix was committed."""

    mounts: int = 0

    async def mount_assistant_block(
        self, *, title_prefix: str | None = None, before: int | None = None
    ) -> AssistantStreamBlock:
        """Expose a partial initial hydration failure without replacing projection."""
        self.mounts += 1
        if self.mounts == 2:
            raise RuntimeError("private initial failure")
        return await super().mount_assistant_block(title_prefix=title_prefix, before=before)


async def test_partial_initial_hydration_does_not_duplicate_prefix_on_retry(tmp_path: Path) -> None:
    """A failed publication cannot silently replay its committed prefix again."""
    entries = await seed_history(root=tmp_path / "history", count=3)

    async def reader() -> list[TranscriptEntryDAO]:
        """Return real-store replay entries."""
        return entries

    transcript = FailingInitialTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test():
        with pytest.raises(RuntimeError, match="private initial failure"):
            await transcript.hydrate()
        await transcript.hydrate()
        assert [b.get_copyable_text() for b in transcript.query(AssistantStreamBlock)] == ["entry-00"]
        await transcript.clear()
        await transcript.hydrate()
        assert [b.get_copyable_text() for b in transcript.query(AssistantStreamBlock)] == [
            "entry-00",
            "entry-01",
            "entry-02",
        ]


@pytest.mark.parametrize("keys", [("pageup", "end"), ("end", "pageup")])
async def test_native_supersession_and_final_growth(keys: tuple[str, str]) -> None:
    """The last native input owns settlement even without a rescue output delta."""
    from src.tui.components.chat_transcript.component import TranscriptScroll

    async def reader() -> list[TranscriptEntryDAO]:
        """Supply an empty replay boundary."""
        return []

    transcript = ChatTranscript(history_reader=reader)
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.append_text(delta="\n\n".join(f"READ-{i:03}" for i in range(100)))
        block._flush_dirty_regions()
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.focus()
        await pilot.press(*keys)
        block.finalize(final_text=block.get_copyable_text() + "\n\nEND-MARKER")
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        painted = "\n".join(strip.text for strip in app.screen._compositor.render_strips())
        assert ("END-MARKER" in painted) == (keys[-1] == "end")
        assert transcript._native_navigation is None


async def test_horizontal_first_input_preserves_programmatic_reading_viewport() -> None:
    """An x input reconciles a public programmatic y move before upper growth."""
    from src.tui.components.chat_transcript.component import TranscriptScroll

    async def reader() -> list[TranscriptEntryDAO]:
        """Supply an empty replay boundary."""
        return []

    transcript = ChatTranscript(history_reader=reader)
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        upper = await transcript.mount_assistant_block()
        upper.finalize(final_text="upper")
        wide = Static("\n".join((f"READ-{i:03} " * 30) for i in range(80)))
        wide.styles.width = 300
        wide.styles.height = 80
        await transcript.mount_tree_output(widget=wide)
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        scroll.styles.overflow_x = "scroll"
        scroll.scroll_to(y=30, animate=False, immediate=True)
        await pilot.pause()
        before = [strip.text for strip in app.screen._compositor.render_strips()]
        row = next(i for i, line in enumerate(before) if "READ-032" in line)
        scroll.focus()
        await pilot.press("right")
        upper.finalize(final_text="\n\n".join(f"growth-{i}" for i in range(10)))
        await pilot.wait_for_scheduled_animations()
        await pilot.pause()
        after = [strip.text for strip in app.screen._compositor.render_strips()]
        assert "READ-032" in after[row]
        assert scroll.scroll_x > 0
        assert transcript._native_navigation is None


async def test_clear_backpressures_real_subscriber_and_joins_repeated_cancellation(tmp_path: Path) -> None:
    """Session publication waits for clear, even when its caller repeatedly cancels."""
    entries = await seed_history(root=tmp_path / "seed", count=65)
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    reads = 0

    async def reader() -> list[TranscriptEntryDAO]:
        """Suppress cancellation of one real-history read until explicitly released."""
        nonlocal reads
        reads += 1
        if reads > 1:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
        return entries

    session = _build_session_with_history(workdir=tmp_path, history_root=tmp_path / "session", responses=[])
    transcript = ChatTranscript(history_reader=reader)

    async def subscriber(event: AgentStreamEventDAO) -> None:
        """Use the same awaited component boundary as the production subscriber."""
        await transcript.present_event(event=event)

    session.subscribe(handler=subscriber)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.hydrate()
        older = asyncio.create_task(transcript.load_older())
        await asyncio.wait_for(entered.wait(), timeout=5)
        cleanup = asyncio.create_task(transcript.clear())
        await asyncio.wait_for(cancelled.wait(), timeout=5)

        async def deliver() -> None:
            """Drive the public session relay with its awaitable subscriber contract."""
            await session.event_relay(
                AgentStreamEventDAO(kind="text_delta", delta="after-clear", iteration=1)
            )

        delivery = asyncio.create_task(deliver())
        for _ in range(3):
            cleanup.cancel()
            await asyncio.sleep(0)
            assert not cleanup.done() and not delivery.done()
        release.set()
        await asyncio.gather(older, cleanup, return_exceptions=True)
        await asyncio.wait_for(delivery, timeout=5)
        await session.event_relay(AgentStreamEventDAO(kind="text_end", content="after-clear", iteration=1))
        await pilot.pause()
        assert [b.get_copyable_text() for b in transcript.query(AssistantStreamBlock)] == ["after-clear"]
        assert cleanup.cancelled()
        assert not session.is_running
    session.unsubscribe(handler=subscriber)


async def test_ancestor_hidden_rejects_native_admission_without_changing_intent() -> None:
    """An ancestor-hidden surface cannot acquire a navigation operation or read geometry."""
    from src.tui.components.chat_transcript.component import TranscriptScroll

    async def reader() -> list[TranscriptEntryDAO]:
        """Supply an empty replay boundary."""
        return []

    transcript = ChatTranscript(history_reader=reader)
    app = TranscriptTestApp(transcript=transcript)
    async with app.run_test() as pilot:
        block = await transcript.mount_assistant_block()
        block.finalize(final_text="\n\n".join(f"row-{i}" for i in range(80)))
        await pilot.pause()
        scroll = transcript.query_one(TranscriptScroll)
        revision = transcript._viewport_revision
        app.screen.display = False
        try:
            scroll.action_page_up()
            assert transcript._native_navigation is None
            assert transcript._viewport_revision == revision
        finally:
            app.screen.display = True


class RemovalGatedUser(UserMessageBlock):
    """Delay actual Textual unmount so a notice arrives after the clear snapshot."""

    def __init__(self, *, entered: asyncio.Event, release: asyncio.Event) -> None:
        """Borrow deterministic unmount barriers for this widget lifetime."""
        super().__init__(text="old")
        self.entered = entered
        self.release = release

    async def on_unmount(self) -> None:
        """Hold removal without replacing the component cleanup operation."""
        self.entered.set()
        await self.release.wait()


async def test_notice_after_clear_snapshot_survives_removal() -> None:
    """Synchronous notices after the removal snapshot survive in DOM and logical text."""

    async def reader() -> list[TranscriptEntryDAO]:
        """Supply an empty replay boundary."""
        return []

    entered, release = asyncio.Event(), asyncio.Event()
    transcript = ChatTranscript(history_reader=reader)
    async with TranscriptTestApp(transcript=transcript).run_test() as pilot:
        await transcript.query_one("#transcript-content").mount(
            RemovalGatedUser(entered=entered, release=release)
        )
        cleanup = asyncio.create_task(transcript.clear())
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            transcript.workflow_notice.write(content="surviving notice", classes="tool-result")
        finally:
            release.set()
        await asyncio.wait_for(cleanup, timeout=5)
        await pilot.pause()
        assert transcript.logical_copy_text() == "surviving notice"
        assert [str(child.render()) for child in transcript.query_one("#transcript-content").children] == [
            "surviving notice"
        ]
