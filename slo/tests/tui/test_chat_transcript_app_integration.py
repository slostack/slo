"""Bounded real-app composition journeys for Feature 96 (dispatch 9)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import pytest
from textual.widgets import Static

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.transcript import TranscriptEntryDAO
from src.agents.slo_agent.orchestrator.workflow_registry import WorkflowHandleDAO
from src.agents.slo_agent.sessions.dao import AgentEventSubscriber, SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import PromptInput, SloTUI
from src.tui.components.chat_transcript.component import ChatTranscript
from src.tui.widgets.assistant_stream_block import AssistantStreamBlock
from src.tui.widgets.user_message_block import UserMessageBlock
from src.tui.workflows.dao import ProgressViewportDAO, WorkflowSessionKeyDAO
from src.tui.workflows.session_progress_screen import SessionProgressScreen


class ObservedSession(SloAgentSession):
    """Record public lifecycle boundaries while retaining real replay and delivery."""

    def __init__(self, *, config: SessionConfigDAO, trace: list[str]) -> None:
        """Build a finite Faux-backed session with real temporary persistence."""
        self.trace = trace
        self.on_subscribe: Callable[[], None] = lambda: None
        self.on_startup: Callable[[], None] = lambda: None
        super().__init__(
            workdir=config.workdir,
            session_id=config.session_id or str(uuid4()),
            config=config,
            agent=SloAgent(
                llm=FauxChatModel(responses=[FauxChatModel.assistant_message(content="answer from session")]),
                cwd=str(config.workdir),
                tools=[],
            ),
            history_store=FilesystemSessionHistoryStore(root=config.history_root),
            enable_history=True,
        )

    async def hydrate_transcript_entries(self) -> list[TranscriptEntryDAO]:
        """Record both sides of the real replay read, not a canned history result."""
        self.trace.append("hydrate:start")
        entries = await super().hydrate_transcript_entries()
        self.trace.append("hydrate:return")
        return entries

    async def should_show_startup_notice(self) -> bool:
        """Record the startup boundary and retain the session's actual decision."""
        self.on_startup()
        self.trace.append("startup")
        return await super().should_show_startup_notice()

    def subscribe(self, *, handler: AgentEventSubscriber) -> None:
        """Observe already-mounted replay before registering the actual handler."""
        self.on_subscribe()
        self.trace.append("subscribe")
        super().subscribe(handler=handler)

    def unsubscribe(self, *, handler: AgentEventSubscriber) -> None:
        """Record retirement while preserving actual handler removal."""
        self.trace.append("unsubscribe")
        super().unsubscribe(handler=handler)


class RecordingSessionFactory:
    """Construct real sessions at the app's existing replacement injection seam."""

    def __init__(self) -> None:
        """Retain call inputs and created sessions for journey assertions."""
        self.calls: list[tuple[SessionConfigDAO, bool]] = []
        self.sessions: list[ObservedSession] = []
        self.trace: list[str] = []

    def __call__(self, *, config: SessionConfigDAO, allow_pending_preparation: bool) -> SloAgentSession:
        """Build an unsubscribed session; never invoke or subscribe on its behalf."""
        self.calls.append((config, allow_pending_preparation))
        self.trace.append("build")
        session = ObservedSession(config=config, trace=self.trace)
        self.sessions.append(session)
        return session


class RecordingLauncher:
    """Replace only the OS terminal launch side effect through constructor injection."""

    def __init__(self, *, launched: bool) -> None:
        """Choose the launch outcome and retain exact target identities."""
        self.launched = launched
        self.calls: list[str] = []

    def __call__(self, *, parent_session_id: str) -> bool:
        """Record one launch without opening a terminal or starting a process."""
        self.calls.append(parent_session_id)
        return self.launched


def session_config(*, tmp_path: Path) -> SessionConfigDAO:
    """Keep every session artifact inside the existing pytest temporary root."""
    return SessionConfigDAO(workdir=tmp_path, history_root=tmp_path / "history", model_name="gpt-5.4")


async def wait_for_answer(*, app: SloTUI) -> None:
    """Wait for terminal app cleanup with a bound, not a fixed timing assumption."""
    async with asyncio.timeout(5):
        while app._in_flight_task is not None:
            await asyncio.sleep(0.01)


async def test_injected_factory_new_session_persists_only_to_replacement(tmp_path: Path) -> None:
    """Drive /new and a prompt through the real input, session and disk store."""
    factory = RecordingSessionFactory()
    initial = factory(config=session_config(tmp_path=tmp_path), allow_pending_preparation=True)
    app = SloTUI(session=initial, session_factory=factory)
    async with app.run_test() as pilot:
        transcript = app.query_one(ChatTranscript)
        await transcript.echo_user(text="old presentation")
        factory.trace.clear()
        app.query_one(PromptInput).load_text("/new replacement")
        await pilot.press("enter")
        await pilot.pause()
        assert len(factory.calls) == 2
        replacement = factory.sessions[1]
        assert factory.trace == ["build", "unsubscribe", "subscribe", "startup"]
        config, pending = factory.calls[1]
        assert pending is True
        assert (config.workdir, config.history_root, config.model_name) == (
            initial.workdir,
            initial.history_root,
            initial.active_model_name,
        )
        assert config.session_id is None
        assert replacement.session_id != initial.session_id
        assert replacement.session_name == "replacement"
        assert app.query_one(ChatTranscript) is transcript
        assert not list(transcript.query(UserMessageBlock))
        await initial.event_relay(AgentStreamEventDAO(kind="text_delta", delta="retired output", iteration=1))
        assert "retired output" not in transcript.logical_copy_text()
        app.query_one(PromptInput).load_text("replacement prompt")
        await pilot.press("enter")
        await wait_for_answer(app=app)
        await pilot.pause()
        assert len(list(transcript.query(UserMessageBlock))) == 1
        assert [block.get_copyable_text() for block in transcript.query(AssistantStreamBlock)] == [
            "answer from session"
        ]
    store = FilesystemSessionHistoryStore(root=tmp_path / "history")
    events = await store.load_events(session_id=replacement.session_id)
    assert [event.payload.content for event in events if event.kind == "user_message"] == [
        "replacement prompt"
    ]
    assert [event.payload.content for event in events if event.kind == "assistant_message"] == [
        "answer from session"
    ]
    assert not any(
        event.kind == "user_message" for event in await store.load_events(session_id=initial.session_id)
    )
    assert factory.trace.count("subscribe") == 1
    assert factory.trace[-1] == "unsubscribe"


async def test_replay_is_mounted_before_startup_and_live_subscription(tmp_path: Path) -> None:
    """Observe exact startup order and mounted content at the subscribe boundary."""
    config = session_config(tmp_path=tmp_path)
    seeded = ObservedSession(config=config, trace=[])
    async for _ in seeded.invoke(text="persisted prompt"):
        pass
    resumed = ObservedSession(config=config.model_copy(update={"session_id": seeded.session_id}), trace=[])
    app = SloTUI(session=resumed)
    history_file = tmp_path / "history" / seeded.session_id / "events.jsonl"
    before = history_file.read_bytes()

    def assert_replay_mounted() -> None:
        """Fail if subscription precedes projection, even after the reader returned."""
        transcript = app.query_one(ChatTranscript)
        assert [block.get_copyable_text() for block in transcript.query(UserMessageBlock)] == [
            "persisted prompt"
        ]
        assert [block.get_copyable_text() for block in transcript.query(AssistantStreamBlock)] == [
            "answer from session"
        ]

    resumed.on_startup = assert_replay_mounted
    resumed.on_subscribe = assert_replay_mounted
    async with app.run_test() as pilot:
        assert resumed.trace == ["hydrate:start", "hydrate:return", "startup", "subscribe"]
        assert history_file.read_bytes() == before
        app.query_one(PromptInput).load_text("live prompt")
        await pilot.press("enter")
        await wait_for_answer(app=app)
        await pilot.pause()
        assert [block.get_copyable_text() for block in app.query(UserMessageBlock)] == [
            "persisted prompt",
            "live prompt",
        ]
        assert len(list(app.query(AssistantStreamBlock))) == 2
    events = await FilesystemSessionHistoryStore(root=config.history_root).load_events(
        session_id=seeded.session_id
    )
    assert [event.payload.content for event in events if event.kind == "user_message"] == [
        "persisted prompt",
        "live prompt",
    ]


@pytest.mark.parametrize("launched", [False, True])
async def test_both_visualizer_routes_use_injected_launcher(
    tmp_path: Path, launched: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Route attached child and detached tool events through the mounted app once."""
    session = ObservedSession(config=session_config(tmp_path=tmp_path), trace=[])
    monkeypatch.setenv("SLO_AUTO_VISUALIZE", "1")
    launcher = RecordingLauncher(launched=launched)
    app = SloTUI(session=session, visualizer_launcher=launcher)
    handle = WorkflowHandleDAO(
        workflow_id="wf-test",
        owner_session_id=session.session_id,
        orchestrator_session_id="detached-session",
        pid=4242,
        brief="test",
        cwd=str(tmp_path),
    )
    attached = AgentStreamEventDAO(kind="sub_agent_spawned", sub_agent_id="child", task_id="task")
    detached = AgentStreamEventDAO(
        kind="tool_result",
        tool_name="launch_workflow",
        tool_call_id="launch",
        content=handle.model_dump_json(),
    )
    async with app.run_test() as pilot:
        for event in (attached, attached, detached, detached):
            await session.event_relay(event)
        await pilot.pause()
        await asyncio.gather(*tuple(app._visualizer_launch_tasks.values()))
        # Main now retries failed viewers; successful requests stay deduplicated.
        assert set(launcher.calls) == {session.session_id, "detached-session"}
        if launched:
            assert launcher.calls == [session.session_id, "detached-session"]
        notices = [
            str(widget.content) for widget in app.query(Static) if widget.has_class("sub-agent-notice")
        ]
        if launched:
            assert notices.count("⊇ Opened workflow visualizer in a new window.") == 2
        else:
            for identity in (session.session_id, "detached-session"):
                assert any(f"slo visualize --session {identity} --follow" in notice for notice in notices)
        assert not list(app.query(AssistantStreamBlock))


async def test_hide_show_retains_progress_modal_focus_and_usable_prompt(tmp_path: Path) -> None:
    """Visibility is presentation-only while a real progress modal owns focus."""
    session = ObservedSession(config=session_config(tmp_path=tmp_path), trace=[])
    app = SloTUI(session=session)
    async with app.run_test() as pilot:
        transcript = app.query_one(ChatTranscript)
        prompt = app.query_one(PromptInput)
        await transcript.echo_user(text="retained entry")
        retained = transcript.query_one(UserMessageBlock)
        retained.focus()
        await pilot.pause()
        assert app.focused is retained
        app.set_transcript_visible(visible=False)
        await pilot.pause()
        assert app.focused is prompt
        app.set_transcript_visible(visible=True)
        await pilot.pause()
        assert app.focused is prompt
        modal = SessionProgressScreen(
            key=WorkflowSessionKeyDAO(orchestrator_session_id="parent", session_id="child"),
            viewport=ProgressViewportDAO(),
        )
        await app.push_screen(modal)
        await pilot.pause()
        focused = app.focused
        assert focused is not None and focused.screen is modal
        reads = session.trace.count("hydrate:start")
        app.set_transcript_visible(visible=False)
        await session.event_relay(AgentStreamEventDAO(kind="text_delta", delta="hidden output", iteration=1))
        await pilot.pause()
        assert app.screen is modal and app.focused is focused
        assert not transcript.display
        app.set_transcript_visible(visible=True)
        await pilot.pause()
        assert app.screen is modal and app.focused is focused
        assert transcript.query_one(UserMessageBlock) is retained
        assert transcript.query_one(AssistantStreamBlock).get_copyable_text() == "hidden output"
        assert session.trace.count("hydrate:start") == reads
        await modal.dismiss()
        await pilot.pause()
        assert app.focused is prompt
        await pilot.press("o", "k")
        assert prompt.text == "ok"
        assert app.focused is prompt
        assert len(app.screen_stack) == 1
