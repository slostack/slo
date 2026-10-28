"""Mounted startup-notice and replay-hydration inner-await lifetime cutoffs (R173-1).

Every inner startup continuation must revalidate its captured session against the
monotonic app cutoff after each real await and before any rendering or marker
persistence. Public ``on_unmount`` may complete while ``on_mount`` is suspended
inside these helpers because the mount runtime task is registered only after they
return. These tests use a real mounted ``SloTUI`` with an injected Faux agent and
a real temporary ``FilesystemSessionHistoryStore``; no provider, Herdr executable
or window is used.
"""

import asyncio
import inspect
from src.tui.components.chat_transcript.component import ChatTranscript

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.dao import (
    HistoryEventKind,
    SessionHistoryEventDAO,
    SessionHistoryEventPayloadDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.tui.app import SloTUI
import src.tui.components.chat_transcript.component as app_module


def _build_session(*, tmp_path: Path, session_id: str, enable_history: bool = True) -> SloAgentSession:
    """Build a session with an injected Faux agent and a real temp history store."""
    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    store = FilesystemSessionHistoryStore(root=root)
    return SloAgentSession(
        agent=SloAgent(
            llm=FauxChatModel(responses=[AIMessage(content="unused")]), tools=[], cwd=str(tmp_path)
        ),
        workdir=tmp_path,
        session_id=session_id,
        history_store=store,
        enable_history=enable_history,
    )


async def _marker_written(*, session: SloAgentSession) -> bool:
    """Return whether the captured session's durable startup marker exists."""
    store = session._history_store
    assert store is not None
    if not await store.session_exists(session_id=session.session_id):
        return False
    metadata = await store.read_metadata(session_id=session.session_id)
    return metadata.startup_notice_shown_at is not None


@pytest.mark.parametrize("cutoff", ["closing", "displaced"])
async def test_notice_inner_await_cutoff_blocks_late_render_and_marker(tmp_path: Path, cutoff: str) -> None:
    """Hold the real history predicate, seal shutdown or displace, then resume.

    The continuation must observe the captured-owner cutoff before any repaint
    or marker persistence: no late lines, no new ``startup_notice_shown_at``
    metadata, and no successor-state access for the displaced variant.
    """
    session = _build_session(tmp_path=tmp_path, session_id="11111111-1111-4111-8111-111111111111")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.should_show_startup_notice
    late_lines: list[str] = []
    original_write = app._chat_transcript.write_transcript_line

    async def predicate() -> bool:
        """Retain the actual history result before the notice continuation resumes."""
        result = await original()
        entered.set()
        await release.wait()
        return result

    def write(*, content: str, classes: str) -> None:
        """Observe actual notice output after the monotonic cutoff."""
        if app._app_closing or app._session is not session:
            late_lines.append(content)
        original_write(content=content, classes=classes)

    async def seal_during_predicate() -> None:
        """Seal the selected cutoff while on_mount is suspended inside its helper."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            if cutoff == "closing":
                await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
                assert app._app_closing
                assert not await _marker_written(session=session)
            else:
                successor = _build_session(
                    tmp_path=tmp_path, session_id="22222222-2222-4222-8222-222222222222"
                )
                successor.should_show_startup_notice = AsyncMock(  # type: ignore[method-assign]
                    side_effect=AssertionError("successor state must not be consulted")
                )
                app._session = successor
        finally:
            release.set()

    with (
        patch.object(session, "should_show_startup_notice", side_effect=predicate),
        patch.object(app._chat_transcript, "write_transcript_line", side_effect=write),
    ):
        driver = asyncio.create_task(coro=seal_during_predicate())
        try:
            async with app.run_test():
                await driver
                assert late_lines == []
                assert not await _marker_written(session=session)
                if cutoff == "closing":
                    assert app._mount_runtime_task is None
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)


@pytest.mark.parametrize("mode", ["history", "memory"])
async def test_notice_open_path_renders_once_with_marker(tmp_path: Path, mode: str) -> None:
    """An open mount renders both startup lines exactly once and persists the marker."""
    session = _build_session(
        tmp_path=tmp_path,
        session_id="33333333-3333-4333-8333-333333333333",
        enable_history=mode == "history",
    )
    app = SloTUI(session=session)
    lines: list[str] = []
    original_write = app._chat_transcript.write_transcript_line

    def write(*, content: str, classes: str) -> None:
        """Record ordinary open-path startup output."""
        lines.append(content)
        original_write(content=content, classes=classes)

    with patch.object(app._chat_transcript, "write_transcript_line", side_effect=write):
        async with app.run_test() as pilot:
            await pilot.pause()
    assert len(lines) == 2
    assert lines[0].startswith("slo, Copyright (C) 2026")
    assert lines[1].startswith("Tip: use /help to see available commands.")
    if mode == "history":
        assert await _marker_written(session=session)
    else:
        assert session._startup_notice_shown_in_memory


async def test_replacement_startup_uses_successor_only(tmp_path: Path) -> None:
    """A committed ``/new`` renders one notice for the successor, none for the old."""
    old = SloAgentSession.build(config=SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history"))
    app = SloTUI(session=old)
    lines: list[tuple[str, str]] = []
    original_write = app._chat_transcript.write_transcript_line

    def write(*, content: str, classes: str) -> None:
        """Record startup output attributed to the session selected at render time."""
        lines.append((app._session.session_id, content))
        original_write(content=content, classes=classes)

    with patch.object(app._chat_transcript, "write_transcript_line", side_effect=write):
        async with app.run_test() as pilot:
            await pilot.pause()
            await app._start_new_session(requested_name=None)
            successor = app._session
            assert successor is not old
            await pilot.pause()
    old_lines = [content for owner, content in lines if owner == old.session_id]
    successor_lines = [content for owner, content in lines if owner == successor.session_id]
    assert len(old_lines) == 2
    assert old_lines[0].startswith("slo, Copyright (C) 2026")
    assert len(successor_lines) == 2
    assert successor_lines[0].startswith("slo, Copyright (C) 2026")
    assert successor_lines[1].startswith("Tip: use /help to see available commands.")


async def _seed_complete_turn(*, session: SloAgentSession, prompt: str) -> None:
    """Persist one complete replayable turn through the real store boundary."""
    store = session._history_store
    assert store is not None
    await store.ensure_session(session_id=session.session_id, workdir=session.workdir, model_name=None)
    turn_id = "turn-hydration"
    seeded: list[tuple[HistoryEventKind, str | None]] = [
        ("user_message", prompt),
        ("assistant_message", "done"),
        ("run_completed", None),
    ]
    for kind, content in seeded:
        await store.append_event(
            event=SessionHistoryEventDAO(
                session_id=session.session_id,
                turn_id=turn_id,
                kind=kind,
                payload=SessionHistoryEventPayloadDAO(content=content),
            )
        )


@pytest.mark.parametrize("cutoff", ["closing", "displaced"])
async def test_hydration_inner_await_cutoff_blocks_late_replay(tmp_path: Path, cutoff: str) -> None:
    """Hold the real replay read, seal shutdown or displace, then resume.

    The hydration continuation must observe the captured-owner cutoff before
    mounting any replay entry; no late projector activity may follow.
    """
    session = _build_session(tmp_path=tmp_path, session_id="66666666-6666-4666-8666-666666666666")
    await _seed_complete_turn(session=session, prompt="hydrate me")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.hydrate_transcript_entries
    mounted: list[object] = []

    async def read() -> list[TranscriptEntryDAO]:
        """Retain the actual replay result before the hydration continuation resumes."""
        entries = await original()
        entered.set()
        await release.wait()
        return entries

    async def project(*, entry: object) -> None:
        """Observe projector mounting after the monotonic cutoff."""
        mounted.append(entry)

    async def seal_during_read() -> None:
        """Seal the selected cutoff while on_mount is suspended inside hydration."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            if cutoff == "closing":
                app._app_closing = True
            else:
                app._session = _build_session(
                    tmp_path=tmp_path, session_id="77777777-7777-4777-8777-777777777777"
                )
        finally:
            release.set()

    with (
        patch.object(app._chat_transcript, "_history_reader", side_effect=read),
        patch.object(app._chat_transcript._projector, "project_replay_entry", side_effect=project),
    ):
        driver = asyncio.create_task(coro=seal_during_read())
        try:
            async with app.run_test():
                await driver
                assert mounted == []
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)


async def test_hydration_open_path_mounts_seeded_replay(tmp_path: Path) -> None:
    """An open mount mounts the seeded replay entries through the real projector."""
    session = _build_session(tmp_path=tmp_path, session_id="99999999-9999-4999-8999-999999999999")
    await _seed_complete_turn(session=session, prompt="hydrate me")
    app = SloTUI(session=session)
    mounted: list[TranscriptEntryDAO] = []
    original = app._chat_transcript._projector.project_replay_entry

    async def project(*, entry: TranscriptEntryDAO) -> None:
        """Observe open-path replay mounting through the real projector."""
        mounted.append(entry)
        await original(entry=entry)

    with patch.object(app._chat_transcript._projector, "project_replay_entry", side_effect=project):
        async with app.run_test() as pilot:
            await pilot.pause()
    assert len(mounted) == 2


async def test_marker_write_admitted_before_cutoff_is_owned(tmp_path: Path) -> None:
    """A marker write admitted before the cutoff completes; no notice repeats it."""
    session = _build_session(tmp_path=tmp_path, session_id="88888888-8888-4888-8888-888888888888")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.mark_startup_notice_shown
    lines: list[str] = []
    original_write = app._chat_transcript.write_transcript_line

    async def marker() -> None:
        """Hold the already-admitted marker write at the final boundary."""
        entered.set()
        await release.wait()
        await original()

    def write(*, content: str, classes: str) -> None:
        """Record startup output admitted before the cutoff."""
        lines.append(content)
        original_write(content=content, classes=classes)

    async def close_during_marker() -> None:
        """Seal public shutdown after rendering but during the owned marker write."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            app._app_closing = True
        finally:
            release.set()

    with (
        patch.object(session, "mark_startup_notice_shown", side_effect=marker),
        patch.object(app._chat_transcript, "write_transcript_line", side_effect=write),
    ):
        driver = asyncio.create_task(coro=close_during_marker())
        try:
            async with app.run_test():
                await driver
                assert len(lines) == 2
                assert await _marker_written(session=session)
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)
    assert await _marker_written(session=session)
    assert len(lines) == 2


@pytest.mark.parametrize("cutoff", ["closing", "displaced"])
async def test_hydration_per_entry_cutoff_blocks_next_replay_mount(tmp_path: Path, cutoff: str) -> None:
    """Seal shutdown or displace after the first real replay mount completes.

    Every ``project_replay_entry`` await is a real mount; the captured-owner
    cutoff must be revalidated after each one so no later entry, the earlier
    summary, or the final scroll can follow the cutoff. The real projector and
    real seeded history are retained; only the mount continuation is held.
    """
    session = _build_session(tmp_path=tmp_path, session_id="55555555-5555-4555-8555-555555555555")
    await _seed_complete_turn(session=session, prompt="per-entry replay cutoff")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = app._chat_transcript._projector.project_replay_entry
    late_entries: list[str] = []
    calls = 0

    async def project(*, entry: TranscriptEntryDAO) -> None:
        """Retain real mounting and hold its first completion at the await boundary."""
        nonlocal calls
        calls += 1
        if app._app_closing or app._session is not session:
            late_entries.append(entry.kind)
        await original(entry=entry)
        if calls == 1:
            entered.set()
            await release.wait()

    async def seal_after_first_mount() -> None:
        """Seal the selected cutoff before the next replay entry is initiated."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            if cutoff == "closing":
                await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
            else:
                app._session = _build_session(
                    tmp_path=tmp_path, session_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
                )
        finally:
            release.set()

    with patch.object(app._chat_transcript._projector, "project_replay_entry", side_effect=project):
        driver = asyncio.create_task(coro=seal_after_first_mount())
        try:
            async with app.run_test():
                await driver
                assert calls == 1
                assert late_entries == []
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)


async def test_notice_ordinary_failure_after_shutdown_renders_nothing(tmp_path: Path) -> None:
    """An ordinary predicate failure after public shutdown must not repaint.

    The fixed failure notice is still a render; the failure continuation must
    revalidate the captured owner before writing it (C7.13).
    """
    session = _build_session(tmp_path=tmp_path, session_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.should_show_startup_notice
    original_write = app._chat_transcript.write_transcript_line
    late_lines: list[str] = []

    async def predicate() -> bool:
        """Complete the real history lookup, then fail after the cutoff."""
        await original()
        entered.set()
        await release.wait()
        raise OSError("synthetic predicate failure")

    def write(*, content: str, classes: str) -> None:
        """Observe late fixed diagnostics without changing rendering."""
        if app._app_closing:
            late_lines.append(content)
        original_write(content=content, classes=classes)

    async def close_during_predicate() -> None:
        """Close publicly while startup is waiting on the failing predicate."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
        finally:
            release.set()

    with (
        patch.object(session, "should_show_startup_notice", side_effect=predicate),
        patch.object(app._chat_transcript, "write_transcript_line", side_effect=write),
    ):
        driver = asyncio.create_task(coro=close_during_predicate())
        try:
            async with app.run_test():
                await driver
                assert late_lines == []
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)


async def test_hydration_cutoff_accepts_absent_metadata_without_late_effects(tmp_path: Path) -> None:
    """Corrected observation for the preserved 173 startup-cutoff probe.

    The historical probe
    ``independent-review-wiring-173-receipts/test_startup_cutoff_probe.py``
    asserts through ``read_metadata`` after public shutdown, which now rightly
    raises ``FileNotFoundError`` because the corrected startup never persists
    metadata after the cutoff. That preserved probe stays unmodified; this
    permanent test is the explicitly identified corrected observation: it
    accepts absent metadata and asserts both no marker and no late lines.
    """
    session = _build_session(tmp_path=tmp_path, session_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc")
    app = SloTUI(session=session)
    entered, release = asyncio.Event(), asyncio.Event()
    original = session.should_show_startup_notice
    original_write = app._chat_transcript.write_transcript_line
    late_lines: list[str] = []

    async def predicate() -> bool:
        """Retain the actual history result before the notice continuation resumes."""
        result = await original()
        entered.set()
        await release.wait()
        return result

    def write(*, content: str, classes: str) -> None:
        """Observe actual notice output after the monotonic cutoff."""
        if app._app_closing:
            late_lines.append(content)
        original_write(content=content, classes=classes)

    async def close_during_predicate() -> None:
        """Use public shutdown while on_mount is suspended inside its notice helper."""
        await asyncio.wait_for(fut=entered.wait(), timeout=5)
        try:
            await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
            assert app._app_closing
        finally:
            release.set()

    with (
        patch.object(session, "should_show_startup_notice", side_effect=predicate),
        patch.object(app._chat_transcript, "write_transcript_line", side_effect=write),
    ):
        driver = asyncio.create_task(coro=close_during_predicate())
        try:
            async with app.run_test():
                await driver
                assert late_lines == []
                assert app._mount_runtime_task is None
                # Absent metadata is accepted: the marker is False whether the
                # session was never persisted or persisted without the marker.
                assert not await _marker_written(session=session)
        finally:
            release.set()
            await asyncio.gather(driver, return_exceptions=True)


@pytest.mark.parametrize("cutoff", ["closing", "displaced"])
async def test_hydration_summary_completion_cannot_initiate_late_scroll(tmp_path: Path, cutoff: str) -> None:
    """Complete the real summary mount, seal the cutoff, then forbid a new scroll.

    ``_update_earlier_summary()`` is itself a real Textual mount/removal
    await, so shutdown or displacement can complete during it; the final
    ``_scroll_transcript_to_end()`` is a *new* effect initiated after that
    await and must revalidate the captured owner first (R178-1). A summary
    mount already admitted before the cutoff remains owned. A real two-entry
    seeded turn with the hydration limit forced to one guarantees the earlier
    summary genuinely mounts; the scroll observer delegates to the real
    scroll and attributes only calls initiated directly by
    ``_hydrate_transcript_from_history`` (framework repaint callbacks are
    excluded by walking past mock frames).
    """
    session = _build_session(tmp_path=tmp_path, session_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    await _seed_complete_turn(session=session, prompt="summary boundary")
    # Two actual history entries, one retained: the summary must really mount.
    with patch.object(target=app_module, attribute="TRANSCRIPT_HYDRATION_ENTRY_LIMIT", new=1):
        app = SloTUI(session=session)
        entered, release = asyncio.Event(), asyncio.Event()
        original_summary = app._chat_transcript._update_earlier_summary
        original_scroll = app._chat_transcript._finish_viewport_mutation
        late_scrolls: list[str] = []
        admitted_scrolls: list[str] = []

        async def summary() -> None:
            """Preserve the actual summary body and its real Textual mount."""
            await original_summary()
            assert app._chat_transcript._earlier_summary is not None
            assert app._chat_transcript._earlier_summary.is_mounted
            entered.set()
            await release.wait()

        def scroll(*, snapshot) -> None:
            """Observe the new effect without replacing the real scroll implementation."""
            frame = inspect.currentframe()
            caller = frame.f_back if frame is not None else None
            # Mock dispatch frames sit between this observer and the production caller.
            while caller is not None and caller.f_code.co_filename.endswith("unittest/mock.py"):
                caller = caller.f_back
            caller_name = caller.f_code.co_name if caller is not None else "unknown"
            if caller_name == "_present_history_tail":
                if app._app_closing or app._session is not session:
                    late_scrolls.append(caller_name)
                else:
                    admitted_scrolls.append(caller_name)
            del frame, caller
            original_scroll(snapshot=snapshot)

        async def cut_off() -> None:
            """Close publicly or replace selected identity before the summary returns."""
            await asyncio.wait_for(fut=entered.wait(), timeout=5)
            try:
                if cutoff == "closing":
                    await asyncio.wait_for(fut=app.on_unmount(), timeout=5)
                    assert app._app_closing
                else:
                    app._session = _build_session(
                        tmp_path=tmp_path, session_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
                    )
            finally:
                release.set()

        with (
            patch.object(app._chat_transcript, "_update_earlier_summary", side_effect=summary),
            patch.object(app._chat_transcript, "_finish_viewport_mutation", side_effect=scroll),
        ):
            driver = asyncio.create_task(coro=cut_off())
            try:
                async with app.run_test():
                    await driver
                    assert late_scrolls == []
                    assert admitted_scrolls == []
            finally:
                release.set()
                await asyncio.gather(driver, return_exceptions=True)


async def test_hydration_open_path_summary_then_scroll_after_summary(tmp_path: Path) -> None:
    """An open hydration mounts the summary first, then initiates exactly one scroll.

    This is the positive control for the cutoff cases above: with no cutoff,
    the admitted summary mount completes and the hydration continuation then
    initiates exactly one scroll directly, proving the new summary-boundary
    revalidation does not block the admitted path.
    """
    session = _build_session(tmp_path=tmp_path, session_id="ffffffff-ffff-4fff-8fff-ffffffffffff")
    await _seed_complete_turn(session=session, prompt="summary open path")
    with patch.object(target=app_module, attribute="TRANSCRIPT_HYDRATION_ENTRY_LIMIT", new=1):
        app = SloTUI(session=session)
        original_scroll = app._chat_transcript._finish_viewport_mutation
        hydration_scrolls: list[str] = []

        def scroll(*, snapshot) -> None:
            """Attribute only scrolls initiated directly by hydration."""
            frame = inspect.currentframe()
            caller = frame.f_back if frame is not None else None
            while caller is not None and caller.f_code.co_filename.endswith("unittest/mock.py"):
                caller = caller.f_back
            caller_name = caller.f_code.co_name if caller is not None else "unknown"
            if caller_name == "_present_history_tail":
                hydration_scrolls.append(caller_name)
            del frame, caller
            original_scroll(snapshot=snapshot)

        with patch.object(app._chat_transcript, "_finish_viewport_mutation", side_effect=scroll):
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app._chat_transcript._earlier_summary is not None
                assert len(hydration_scrolls) == 1
