"""Mounted teardown retains the real OS lease until optional observers actually join."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.messaging.dao import MessageSubmissionDAO, SessionAlreadyOwnedError
from src.agents.slo_agent.messaging.ownership import SessionExecutionOwnership
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.tui.app import SloTUI
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.agents.slo_agent.messaging.test_delivery import RealAgentFactory
from tests.integration.test_messaging_yield import InterruptedProvider, isolated_journey_tasks
from tests.tui.test_durable_composer import _wait_until


async def test_mounted_close_joins_observer_before_os_lease_release(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """Repeatedly cancelled owner close cannot release a callback's live session lease."""
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def observer(event: AgentStreamEventDAO) -> None:
        """Suppress cancellation until this test explicitly acknowledges observation cleanup."""
        if event.kind != "text_delta":
            return
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    session_id = str(uuid4())
    model = InterruptedProvider(responses=[FauxChatModel.assistant_message(content="done")])
    model.partial = True
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    session.subscribe(handler=observer)
    app = SloTUI(session=session, messaging_enabled=True)
    close: asyncio.Task[None] | None = None
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(PromptInputComponent)
            prompt.insert(text="Start")
            await pilot.press("enter")
            await _wait_until(predicate=entered.is_set)
            # A separately borrowed client owns observation only, never the target execution.
            client = LocalSessionMessagingClient(
                session=session, target=session.messaging_target, principal=session.messaging_owner_principal
            )
            await client.close()
            assert not model.cancelled.is_set() and session.is_running
            app.exit()
            close = asyncio.create_task(coro=session.close_messaging())
            await _wait_until(predicate=cancelled.is_set)
            close.cancel()
            await asyncio.sleep(delay=0)
            close.cancel()
            await asyncio.sleep(delay=0)
            assert not close.done()
            with pytest.raises(SessionAlreadyOwnedError):
                await SessionExecutionOwnership.acquire(root=root, session_id=session_id)
            assert model.cancelled.is_set()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await close
        lease = await SessionExecutionOwnership.acquire(root=root, session_id=session_id)
        await lease.release()
    finally:
        release.set()
        model.release.set()
        if close is not None:
            await asyncio.gather(close, return_exceptions=True)
        await session.close_messaging()


async def test_new_joins_predecessor_observer_before_adopting_successor(
    tmp_path: Path, isolated_journey_tasks: None
) -> None:
    """A local /new cannot adopt the next binding while predecessor observation still owns work."""
    from src.agents.slo_agent.agent import SloAgent
    from tests.agents.slo_agent.messaging.test_delivery import RecordingModel

    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def observer(event: AgentStreamEventDAO) -> None:
        """Keep a completed run's observer retiring until explicit cleanup acknowledgement."""
        if event.kind != "run_completed":
            return
        entered.set()
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()

    root = tmp_path / "history"
    assert root.resolve().is_relative_to(tmp_path.resolve())
    model = RecordingModel(responses=[FauxChatModel.assistant_message(content="done")])
    model.release.set()
    session = SloAgentSession(
        workdir=tmp_path,
        session_id=str(uuid4()),
        config=SessionConfigDAO(workdir=tmp_path, history_root=root, model_name="gpt-5.4"),
        history_store=FilesystemSessionHistoryStore(root=root),
        messaging_agent_factory=RealAgentFactory(model=model, workdir=tmp_path),
    )
    successors: list[SloAgentSession] = []

    def factory(*, config: SessionConfigDAO, allow_pending_preparation: bool) -> SloAgentSession:
        """Supply only an external-provider-backed candidate through the host's existing factory."""
        successor = SloAgentSession(
            agent=SloAgent(llm=FauxChatModel(responses=[]), tools=[], cwd=str(tmp_path)),
            workdir=tmp_path,
            session_id=str(uuid4()),
            config=config,
            history_store=FilesystemSessionHistoryStore(root=root),
        )
        successors.append(successor)
        return successor

    session.subscribe(handler=observer)
    app = SloTUI(session=session, messaging_enabled=True, session_factory=factory)
    try:
        async with app.run_test(size=(120, 40)) as pilot:
            await _wait_until(predicate=lambda: session.is_messaging_ready)
            prompt = app.query_one(PromptInputComponent)
            prompt.insert(text="run")
            await pilot.press("enter")
            await _wait_until(predicate=lambda: entered.is_set() and not session.is_running)
            prompt.insert(text="/new")
            # Posting the native intent leaves Textual's owner free to wait on teardown.
            prompt.request_submission(priority="urgent")
            await _wait_until(predicate=cancelled.is_set)
            assert successors and not successors[0].is_messaging_ready
            with pytest.raises(SessionAlreadyOwnedError):
                await SessionExecutionOwnership.acquire(root=root, session_id=session.session_id)
            release.set()
            await _wait_until(predicate=lambda: successors[0].is_messaging_ready)
            await pilot.pause()
            assert prompt.text == "" and prompt.has_focus
            lease = await SessionExecutionOwnership.acquire(root=root, session_id=session.session_id)
            await lease.release()
    finally:
        release.set()
        await session.close_messaging()
        for successor in successors:
            await successor.close_messaging()
