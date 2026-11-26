"""TUI channel journey tests (108.1 M1, A2/A3/A4/A6-recovery/A8 TUI half).

Journey: real Textual prompt submission → TuiChannelAdapter.send_prompt →
ChannelGateway → real SQLite → session poller → TuiTurnRunner → real
SloAgentSession.invoke (FauxChatModel) → accepted row + history link →
reply row → visible TUI. The prompt box stays editable throughout (A4); three
prompts sent during a run execute in FIFO order, each echo appearing at its
own run start (A3). ``/queue resume`` continues a paused poller and the
restart recovery pause shows a visible notice (108.1 §2/§6).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.messages import AIMessage
from langchain_core.tools import BaseTool
from pydantic import Field, PrivateAttr

from src.agents.providers.faux import FauxChatModel
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.app import SloTUI
from src.tui.channel.adapter import TuiChannelAdapter
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.prompt_input.component import PromptInputComponent
from tests.tui._scroll_settle import pump_until
from tests.conftest import GatedFauxChatModel

_RECOVERY_PAUSE_NOTICE: str = (
    "channel queue paused after restart — 1 queued prompt(s) held; /queue resume to continue"
)
_ABORT_HOLD_NOTICE: str = "(aborting… queued prompts held — /queue resume to continue)"


def _build_session(
    *,
    tmp_path: Path,
    responses: list[AIMessage],
    model: Optional[FauxChatModel] = None,
    session_id: Optional[str] = None,
) -> SloAgentSession:
    """Build a real session with a (possibly gated) faux provider and real history.

    Args:
        tmp_path (Path): Temp root for the workdir and the history store.
        responses (list[AIMessage]): Scripted provider responses.
        model (Optional[FauxChatModel]): Provider override; defaults to a plain
            ``FauxChatModel`` built from ``responses``.
        session_id (Optional[str]): Fixed session id; defaults to a fresh UUID.

    Returns:
        SloAgentSession: A session ready to drive ``SloTUI``.
    """
    return SloAgentSession(
        agent=SloAgent(llm=model or FauxChatModel(responses=responses), cwd=str(tmp_path), tools=[]),
        workdir=tmp_path,
        session_id=session_id or str(uuid4()),
        history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
        enable_history=True,
    )


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open one real gateway on a fresh temp database.

    Args:
        tmp_path (Path): Temp root holding ``channels.db``.

    Returns:
        ChannelGateway: The opened gateway.
    """
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


def _transcript_lines(*, app: SloTUI) -> list[tuple[str, str]]:
    """Return the recorded ``(content, classes)`` transcript lines.

    Args:
        app (SloTUI): The app under test.

    Returns:
        list[tuple[str, str]]: Recorded transcript lines in render order.
    """
    transcript: ChatTranscriptComponent = app.query_one(ChatTranscriptComponent)
    assert transcript._adapter is not None
    return transcript._adapter.lines


def _user_echo_texts(*, app: SloTUI) -> list[str]:
    """Return the echoed ``user-line`` texts in transcript order.

    Args:
        app (SloTUI): The app under test.

    Returns:
        list[str]: Echoed user texts, without their ``> `` prefix.
    """
    return [
        content.removeprefix("> ")
        for content, classes in _transcript_lines(app=app)
        if classes == "user-line"
    ]


def _first_line_index_containing(*, app: SloTUI, needle: str) -> int:
    """Return the index of the first transcript line containing ``needle``.

    Args:
        app (SloTUI): The app under test.
        needle (str): Substring searched in recorded line contents.

    Returns:
        int: Index into the recorded line list.

    Raises:
        StopIteration: The needle never appears.
    """
    return next(
        index for index, (content, _classes) in enumerate(_transcript_lines(app=app)) if needle in content
    )


async def _wait_until_db(
    *,
    predicate,
    timeout_seconds: float = 20.0,
) -> None:
    """Poll a database-backed predicate until it holds or the timeout expires.

    Args:
        predicate: Awaitable returning a truthy value.
        timeout_seconds (float): Bound before failing.
    """
    async with asyncio.timeout(timeout_seconds):
        while not await predicate():
            await asyncio.sleep(0.02)


class TestPromptSubmissionGoesThroughTheQueue:
    async def test_entered_prompt_becomes_a_queue_row_and_runs_to_a_reply(self, tmp_path: Path) -> None:
        """Journey A2/A4/A8: Enter → row → poller run → accepted → history → reply; box stays editable."""
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[AIMessage(content="hi there")],
        )
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                assert app.channel_adapter is not None
                poller = session.channel_poller
                assert poller is not None

                prompt_input = app.query_one(PromptInputComponent)
                prompt_input.text = "hello"
                await pilot.press("enter")
                await pilot.pause()

                # A4: the prompt box is cleared and immediately editable again.
                assert prompt_input.text == ""
                assert not prompt_input.disabled

                agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                async def _answered() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    replies: list[ChannelMessageDAO] = [
                        row for row in conversation if row.message_type == "reply"
                    ]
                    return bool(replies) and all(row.accepted_at is not None for row in replies)

                deadline: float = asyncio.get_event_loop().time() + 20.0
                while not await _answered():
                    if asyncio.get_event_loop().time() > deadline:
                        raise AssertionError("no reply row arrived in time")
                    await pilot.pause(0.05)
                    await asyncio.sleep(0.02)

                # A2: the request row was accepted exactly once.
                adapter = app.channel_adapter
                assert adapter is not None
                conversation: list[ChannelMessageDAO] = await gateway.repository.list_conversation_messages(
                    agent_session_id=agent_id
                )
                prompts: list[ChannelMessageDAO] = [
                    row for row in conversation if row.message_type == "prompt"
                ]
                replies: list[ChannelMessageDAO] = [
                    row for row in conversation if row.message_type == "reply"
                ]
                assert len(prompts) == 1
                assert prompts[0].accepted_at is not None
                assert prompts[0].message_contents == "hello"

                # A8: exactly one reply, linked to the request.
                assert len(replies) == 1
                assert replies[0].in_reply_to_id == prompts[0].id
                assert replies[0].message_contents == "hi there"
                assert replies[0].accepted_at is not None  # outbound accepted by the adapter

                # History carries the channel link (A7 recovery seam).
                assert session.history_store is not None
                events = await session.history_store.load_events(session_id=session.session_id)
                user_events = [event for event in events if event.kind == "user_message"]
                assert [event.payload.content for event in user_events] == ["hello"]
                assert user_events[0].payload.metadata.get("channel_message_id") == str(prompts[0].id)
        finally:
            await gateway.close()


class TestThreePromptsRunInOrder:
    async def test_three_prompts_sent_during_a_run_execute_in_fifo_order(self, tmp_path: Path) -> None:
        """A3/A4: prompts typed mid-run stay queued and unechoed; echo order interleaves with answers."""
        release_first_run: asyncio.Event = asyncio.Event()
        model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[
                AIMessage(content="answer one"),
                AIMessage(content="answer two"),
                AIMessage(content="answer three"),
            ],
            first_call_release=release_first_run,
        )
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=model)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = session.channel_poller
                assert poller is not None
                agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                prompt_input.text = "first"
                await pilot.press("enter")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["first"],
                )
                # A3: run 1 owns the session while prompts 2 and 3 are submitted.
                assert poller.busy is True

                prompt_input.text = "second"
                await pilot.press("enter")

                async def _second_row_pending() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    return any(
                        row.message_contents == "second"
                        and row.accepted_at is None
                        and row.cancelled_at is None
                        for row in conversation
                    )

                await _wait_until_db(predicate=_second_row_pending)
                assert poller.busy is True
                # A4: the box is enabled, editable, and cleared mid-run.
                assert not prompt_input.disabled
                assert prompt_input.text == ""
                # A3: the queued text is not echoed until its own run starts.
                assert "second" not in _user_echo_texts(app=app)

                prompt_input.text = "third"
                await pilot.press("enter")

                async def _third_row_pending() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    return any(
                        row.message_contents == "third"
                        and row.accepted_at is None
                        and row.cancelled_at is None
                        for row in conversation
                    )

                await _wait_until_db(predicate=_third_row_pending)
                assert poller.busy is True
                assert not prompt_input.disabled
                assert "third" not in _user_echo_texts(app=app)

                release_first_run.set()

                async def _all_replied() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    replies = [row for row in conversation if row.message_type == "reply"]
                    return len(replies) == 3 and all(row.accepted_at is not None for row in replies)

                await _wait_until_db(predicate=_all_replied, timeout_seconds=30.0)

                conversation = await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                prompts: list[ChannelMessageDAO] = [
                    row for row in conversation if row.message_type == "prompt"
                ]
                replies = [row for row in conversation if row.message_type == "reply"]
                assert [row.message_contents for row in prompts] == ["first", "second", "third"]
                assert all(row.accepted_at is not None for row in prompts)

                # FIFO: the invoke order matches the send order (read back from history).
                assert session.history_store is not None
                events = await session.history_store.load_events(session_id=session.session_id)
                user_events = [event for event in events if event.kind == "user_message"]
                assert [event.payload.content for event in user_events] == ["first", "second", "third"]
                reply_by_request: dict[UUID, ChannelMessageDAO] = {
                    reply.in_reply_to_id: reply for reply in replies if reply.in_reply_to_id is not None
                }
                assert reply_by_request[prompts[0].id].message_contents == "answer one"
                assert reply_by_request[prompts[1].id].message_contents == "answer two"
                assert reply_by_request[prompts[2].id].message_contents == "answer three"

                # A3 echo order: each echo appears at its run start, interleaved
                # with the answer it produced, in the visible transcript.
                echo_answer_order: list[int] = [
                    _first_line_index_containing(app=app, needle=needle)
                    for needle in (
                        "> first",
                        "answer one",
                        "> second",
                        "answer two",
                        "> third",
                        "answer three",
                    )
                ]
                assert echo_answer_order == sorted(echo_answer_order)
                assert len(set(echo_answer_order)) == 6
                assert _user_echo_texts(app=app) == ["first", "second", "third"]
        finally:
            await gateway.close()


class TestAbortPausesAndQueueResumeContinues:
    async def test_abort_pauses_and_queue_resume_runs_the_next_row(self, tmp_path: Path) -> None:
        """A6 (minimal M1 slice): ``/abort`` pauses; ``/queue resume`` runs the held row."""
        release_first_run: asyncio.Event = asyncio.Event()
        model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[AIMessage(content="answer one"), AIMessage(content="answer two")],
            first_call_release=release_first_run,
        )
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=model)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = session.channel_poller
                assert poller is not None
                agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                prompt_input.text = "first"
                await pilot.press("enter")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["first"],
                )
                prompt_input.text = "held"
                await pilot.press("enter")

                # Ctrl+C aborts: the poller pauses and the hold notice names /queue resume.
                await pilot.press("ctrl+c")
                await pump_until(pilot=pilot, predicate=lambda: poller.paused == "aborted")
                assert any(_ABORT_HOLD_NOTICE == content for content, _ in _transcript_lines(app=app))

                release_first_run.set()
                first_row: ChannelMessageDAO = (
                    await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                )[0]

                async def _first_run_finished_and_held_row_pending() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    held = next((r for r in conversation if r.message_contents == "held"), None)
                    first_reply = next(
                        (
                            r
                            for r in conversation
                            if r.message_type == "reply" and r.in_reply_to_id == first_row.id
                        ),
                        None,
                    )
                    return (
                        not poller.busy
                        and held is not None
                        and held.accepted_at is None
                        and held.cancelled_at is None
                        and first_reply is not None
                    )

                await _wait_until_db(predicate=_first_run_finished_and_held_row_pending, timeout_seconds=30.0)
                assert poller.paused == "aborted"

                # The operator types the documented command through the real input.
                prompt_input.text = "/queue resume"
                await pilot.press("enter")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.paused is None
                    and any("queue resumed" in content for content, _ in _transcript_lines(app=app)),
                )

                async def _held_row_ran_to_a_reply() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    held = next((r for r in conversation if r.message_contents == "held"), None)
                    if held is None or held.accepted_at is None or held.cancelled_at is not None:
                        return False
                    replies = [r for r in conversation if r.in_reply_to_id == held.id]
                    return len(replies) == 1 and replies[0].message_contents == "answer two"

                await _wait_until_db(predicate=_held_row_ran_to_a_reply, timeout_seconds=30.0)
                assert poller.paused is None
        finally:
            await gateway.close()


class TestRecoveredPauseShowsANotice:
    async def test_restart_with_leftover_rows_starts_paused_with_a_notice_and_resume_continues(
        self, tmp_path: Path
    ) -> None:
        """108.1 §6: leftover rows start the poller paused with a visible notice; resume continues."""
        fixed_session_id: str = str(uuid4())
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            # Seed the queue exactly as a crashed TUI left it: one pending prompt.
            await gateway.register_agent(
                session_id=channel_participant_id_for_session(session_id=fixed_session_id),
                name="slo restart-test",
            )
            user: ParticipantDAO = await gateway.register_user(
                channel_id=(await gateway.register_channel(kind="tui", name="tui@test")).id,
                name="operator (tui)",
                external_ref="operator",
            )
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=channel_participant_id_for_session(session_id=fixed_session_id),
                    message_contents="leftover prompt",
                )
            )
            session: SloAgentSession = _build_session(
                tmp_path=tmp_path,
                responses=[AIMessage(content="leftover answer")],
                session_id=fixed_session_id,
            )
            app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
            async with app.run_test() as pilot:
                await pilot.pause()
                poller = session.channel_poller
                assert poller is not None
                # Recovery paused the poller before any run started.
                assert poller.paused == "recovered"
                agent_id: UUID = channel_participant_id_for_session(session_id=fixed_session_id)

                async def _row_still_pending() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    row = next(
                        (r for r in conversation if r.message_contents == "leftover prompt"),
                        None,
                    )
                    return row is not None and row.accepted_at is None and row.cancelled_at is None

                await _wait_until_db(predicate=_row_still_pending)
                # The recovery notice is visible in the transcript.
                assert any(_RECOVERY_PAUSE_NOTICE in content for content, _ in _transcript_lines(app=app))

                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                prompt_input.text = "/queue resume"
                await pilot.press("enter")
                await pump_until(pilot=pilot, predicate=lambda: poller.paused is None)

                async def _leftover_row_ran() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    row = next(
                        (r for r in conversation if r.message_contents == "leftover prompt"),
                        None,
                    )
                    if row is None or row.accepted_at is None or row.cancelled_at is not None:
                        return False
                    replies = [r for r in conversation if r.in_reply_to_id == row.id]
                    return len(replies) == 1 and replies[0].message_contents == "leftover answer"

                await _wait_until_db(predicate=_leftover_row_ran, timeout_seconds=30.0)
        finally:
            await gateway.close()


class TestSlashCommandBypassesTheQueue:
    async def test_slash_command_while_poller_is_busy_runs_and_normal_send_goes_through_queue(
        self, tmp_path: Path
    ) -> None:
        """EM6 (updated for 108.2): slash text dispatches immediately; /steer queues a forced row."""
        release_first_run: asyncio.Event = asyncio.Event()
        model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[AIMessage(content="answer one")],
            first_call_release=release_first_run,
        )
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=model)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = session.channel_poller
                assert poller is not None
                agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                prompt_input.text = "first"
                await pilot.press("enter")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["first"],
                )

                prompt_input.text = "/steer be terse"
                await pilot.press("enter")
                await pilot.pause()
                prompt_input.text = "/help"
                await pilot.press("enter")
                await pilot.pause()

                # No pending-steering widget exists in 108.2; the forced send
                # confirmation is a transcript line and the row is queued with
                # forced_at set.
                assert not list(app.query("SteeringPendingBlock"))
                assert any("forced message queued" in content for content, _ in _transcript_lines(app=app))
                assert any("help" in content.lower() for content, _ in _transcript_lines(app=app))

                async def _run_row_plus_forced_row() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    prompts = [row for row in conversation if row.message_type == "prompt"]
                    return (
                        len(prompts) == 2
                        and prompts[0].message_contents == "first"
                        and prompts[1].message_contents == "be terse"
                        and prompts[1].forced_at is not None
                    )

                await _wait_until_db(predicate=_run_row_plus_forced_row)
                release_first_run.set()
        finally:
            await gateway.close()


class TestForceKeyBindingsSendThroughTheQueue:
    """F6: Enter sends normal; Ctrl+Enter and Alt+Enter send forced; Shift+Enter newlines."""

    async def test_enter_sends_normal_and_modified_enters_send_forced(self, tmp_path: Path) -> None:
        """The three submit variants land as rows with the right ``forced_at``."""
        session: SloAgentSession = _build_session(
            tmp_path=tmp_path,
            responses=[
                AIMessage(content="one"),
                AIMessage(content="two"),
                AIMessage(content="three"),
            ],
        )
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                async def _conversation_prompts() -> list[ChannelMessageDAO]:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    return [row for row in conversation if row.message_type == "prompt"]

                async def _prompt_count_is(count: int) -> bool:
                    return len(await _conversation_prompts()) == count

                async def _all_rows_accepted() -> bool:
                    return all(row.accepted_at is not None for row in await _conversation_prompts())

                prompt_input.text = "plain"
                await pilot.press("enter")
                await _wait_until_db(predicate=lambda: _prompt_count_is(1))

                prompt_input.text = "forced via ctrl"
                await pilot.press("ctrl+enter")
                await _wait_until_db(predicate=lambda: _prompt_count_is(2))

                prompt_input.text = "forced via alt"
                await pilot.press("alt+enter")
                await _wait_until_db(predicate=lambda: _prompt_count_is(3))

                prompt_input.text = "no submit"
                prompt_input.move_cursor(prompt_input.document.end)
                await pilot.press("shift+enter")
                await pilot.pause()
                assert prompt_input.text == "no submit\n"
                assert len(await _conversation_prompts()) == 3

                await _wait_until_db(predicate=_all_rows_accepted)
                prompts: list[ChannelMessageDAO] = await _conversation_prompts()
                assert [row.message_contents for row in prompts] == [
                    "plain",
                    "forced via ctrl",
                    "forced via alt",
                ]
                assert prompts[0].forced_at is None
                assert prompts[1].forced_at is not None
                assert prompts[2].forced_at is not None
        finally:
            await gateway.close()


class TestForcedSendWhileIdleRunsAtOnce:
    """F3 (TUI): a forced send while idle starts a run at once (108.2 §8)."""

    async def test_ctrl_enter_while_idle_starts_the_run_immediately(self, tmp_path: Path) -> None:
        """An idle Ctrl+Enter runs the forced row without any other trigger.

        The provider boundary is held so the started run stays in flight and
        observable: the poller owns a busy run and the user echo renders while
        the forced row exists — no second press, normal row or extra poll tick
        is needed to kick the idle run.
        """
        release: asyncio.Event = asyncio.Event()
        model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[AIMessage(content="forced idle answer")],
            first_call_release=release,
        )
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=model)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = session.channel_poller
                assert poller is not None
                assert poller.busy is False
                agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                prompt_input.text = "use pytest -x"
                await pilot.press("ctrl+enter")

                # The idle poller wakes on the same-process send and starts
                # the forced row at once; the held provider keeps it running.
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["use pytest -x"],
                )

                async def _single_forced_row() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    prompts: list[ChannelMessageDAO] = [
                        row for row in conversation if row.message_type == "prompt"
                    ]
                    return (
                        len(prompts) == 1
                        and prompts[0].message_contents == "use pytest -x"
                        and prompts[0].forced_at is not None
                    )

                await _wait_until_db(predicate=_single_forced_row)

                release.set()

                async def _answered() -> bool:
                    conversation: list[ChannelMessageDAO] = (
                        await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                    )
                    replies: list[ChannelMessageDAO] = [
                        row for row in conversation if row.message_type == "reply"
                    ]
                    return bool(replies) and all(row.accepted_at is not None for row in replies)

                await _wait_until_db(predicate=_answered)

                # The completed run is the forced row's own reply, linked back.
                conversation: list[ChannelMessageDAO] = await gateway.repository.list_conversation_messages(
                    agent_session_id=agent_id
                )
                prompts: list[ChannelMessageDAO] = [
                    row for row in conversation if row.message_type == "prompt"
                ]
                replies: list[ChannelMessageDAO] = [
                    row for row in conversation if row.message_type == "reply"
                ]
                assert len(prompts) == 1 and prompts[0].accepted_at is not None
                assert len(replies) == 1 and replies[0].in_reply_to_id == prompts[0].id
                assert replies[0].message_contents == "forced idle answer"
        finally:
            await gateway.close()


class TestQueueForceSlashCommandJourney:
    """F7: ``/queue force <n>`` forces a pending row; it applies at the next boundary."""

    async def test_queue_force_n_applies_the_row_at_the_next_boundary(self, tmp_path: Path) -> None:
        """F7: with rows 2 and 3 queued mid-run, ``/queue force 2`` joins row 3 into the current run.

        The running row is accepted before ``/queue`` positions are read, so
        position 2 deterministically names the second pending row. The forced
        row reaches the very next provider call exactly once, is accepted and
        recorded as steering (never a standalone turn or reply), and the other
        queued row still runs afterwards in FIFO order.
        """
        release_first_run: asyncio.Event = asyncio.Event()
        model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[
                AIMessage(content="answer one"),
                AIMessage(content="steered answer"),
                AIMessage(content="answer two"),
            ],
            first_call_release=release_first_run,
        )
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=model)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                try:
                    await pilot.pause()
                    prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                    poller = session.channel_poller
                    assert poller is not None
                    agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                    async def _conversation_prompts() -> list[ChannelMessageDAO]:
                        conversation: list[ChannelMessageDAO] = (
                            await gateway.repository.list_conversation_messages(agent_session_id=agent_id)
                        )
                        return [row for row in conversation if row.message_type == "prompt"]

                    prompt_input.text = "one"
                    await pilot.press("enter")
                    await pump_until(
                        pilot=pilot,
                        predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["one"],
                    )
                    # The running row is held inside its first provider call, so it
                    # is not accepted yet; it is running, never a numbered queue row.
                    assert [row.message_contents for row in await poller.pending_prompts()] == []

                    for text in ("two", "three"):
                        prompt_input.text = text
                        await pilot.press("enter")

                    async def _two_rows_pending() -> bool:
                        return [row.message_contents for row in await poller.pending_prompts()] == [
                            "two",
                            "three",
                        ]

                    await _wait_until_db(predicate=_two_rows_pending)

                    prompt_input.text = "/queue force 2"
                    await pilot.press("enter")
                    await pilot.pause()
                    assert any("row 2 forced" in content for content, _ in _transcript_lines(app=app))
                    prompts: list[ChannelMessageDAO] = await _conversation_prompts()
                    assert [(row.message_contents, row.forced_at is not None) for row in prompts] == [
                        ("one", False),
                        ("two", False),
                        ("three", True),
                    ]

                    # Release the held run: the boundary revives for the forced row,
                    # then the remaining normal row runs as its own turn.
                    release_first_run.set()

                    async def _all_settled() -> bool:
                        rows: list[ChannelMessageDAO] = await _conversation_prompts()
                        return all(row.accepted_at is not None for row in rows) and all(
                            [await gateway.find_reply(message_id=row.id) for row in (rows[0], rows[1])]
                        )

                    await _wait_until_db(predicate=_all_settled)
                    await pump_until(pilot=pilot, predicate=lambda: poller.busy is False)
                    echoes: list[str] = _user_echo_texts(app=app)
                    replies: list[Optional[ChannelMessageDAO]] = [
                        await gateway.find_reply(message_id=row.id) for row in await _conversation_prompts()
                    ]
                finally:
                    # Never unmount with the provider still held (unmount joins the run).
                    release_first_run.set()
        finally:
            release_first_run.set()
            await session.stop_channel_delivery(reason="test_done")
            await gateway.close()

        one, two, three = prompts
        assert echoes == ["one", "three", "two"]
        assert len(model.provider_calls) == 3
        assert all("three" not in call for call in model.provider_calls[:1])
        assert model.provider_calls[1].count("three") == 1
        assert "two" not in model.provider_calls[1]
        assert model.provider_calls[2].count("three") == 1 and "two" in model.provider_calls[2]
        assert [(reply.in_reply_to_id, reply.message_contents) if reply else None for reply in replies] == [
            (one.id, "steered answer"),
            (two.id, "answer two"),
            None,
        ]
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        user_turns: list[str] = [
            event.payload.content
            for event in events
            if event.kind == "user_message" and event.payload.content is not None
        ]
        steering = [
            event
            for event in events
            if event.kind == "steering_message"
            and event.payload.metadata.get("channel_message_id") == str(three.id)
        ]
        assert user_turns == ["one", "two"]
        assert len(steering) == 1


class SequencedGateFauxChatModel(FauxChatModel):
    """Provider-boundary double gating each model call on its own event.

    Call N waits on ``call_releases[N]`` before streaming, so a test can hold
    the run that is in flight at abort time and, separately, the run a
    ``/queue resume`` starts inside the abort grace window.
    """

    call_releases: list[asyncio.Event] = Field(
        description="One release event per scripted model call, consumed in order.",
    )
    _calls_served: int = PrivateAttr(default=0)

    def __init__(self, *, responses: Sequence[AIMessage], call_releases: list[asyncio.Event]) -> None:
        """Store the scripted responses and the per-call release events.

        Args:
            responses (Sequence[AIMessage]): Scripted responses consumed in order.
            call_releases (list[asyncio.Event]): One gate per model call.
        """
        super().__init__(responses=responses, call_releases=call_releases)

    def bind_tools(
        self,
        tools: Sequence[dict[str, object] | type | Callable[..., object] | BaseTool],
        *,
        tool_choice: Optional[str] = None,
        **kwargs: object,
    ) -> "SequencedGateFauxChatModel":
        """Clone sharing the gates and the served-call counter."""
        clone: SequencedGateFauxChatModel = SequencedGateFauxChatModel(
            responses=list(self.queue),
            call_releases=self.call_releases,
        )
        clone.bound_tools = list(tools)
        clone._calls_served = self._calls_served
        return clone

    async def _astream(
        self,
        messages: list,
        stop: Optional[list[str]] = None,
        run_manager: Optional[AsyncCallbackManagerForLLMRun] = None,
        **kwargs: object,
    ):
        """Hold call N until its release event, then stream the scripted chunks."""
        index: int = self._calls_served
        self._calls_served += 1
        if index < len(self.call_releases):
            await self.call_releases[index].wait()
        async for chunk in super()._astream(messages=messages, stop=stop, run_manager=run_manager, **kwargs):
            yield chunk


class TestAbortEscalationNeverKillsALaterRun:
    """EB5 (108.2 §6): the hard-cancel escalation is bound to its own run.

    Before the fix, ``/abort`` armed an unbound timer that cancelled whatever
    channel run was in flight when the grace expired — including a run a
    quick ``/queue resume`` started after the aborted one had wound down.
    """

    async def test_abort_grace_does_not_cancel_a_resumed_run(self, tmp_path: Path) -> None:
        """/abort during a held run; a resumed run held past the grace completes."""
        release_aborted_run: asyncio.Event = asyncio.Event()
        release_resumed_run: asyncio.Event = asyncio.Event()
        model: SequencedGateFauxChatModel = SequencedGateFauxChatModel(
            responses=[AIMessage(content="aborted run"), AIMessage(content="resumed answer")],
            call_releases=[release_aborted_run, release_resumed_run],
        )
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=model)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = session.channel_poller
                assert poller is not None
                agent_id: UUID = channel_participant_id_for_session(session_id=session.session_id)

                async def _conversation() -> list[ChannelMessageDAO]:
                    return await gateway.repository.list_conversation_messages(agent_session_id=agent_id)

                prompt_input.text = "first"
                await pilot.press("enter")
                await pump_until(pilot=pilot, predicate=lambda: poller.busy)
                prompt_input.text = "second"
                await pilot.press("enter")
                await pilot.pause()

                # /abort during the held run: the escalation binds to THIS run.
                prompt_input.text = "/abort"
                await pilot.press("enter")
                await pump_until(pilot=pilot, predicate=lambda: poller.paused == "aborted")

                release_aborted_run.set()
                await pump_until(pilot=pilot, predicate=lambda: not poller.busy)
                await pilot.pause()

                # A quick resume starts the next run inside the grace window;
                # hold it at the provider boundary past the grace.
                prompt_input.text = "/queue resume"
                await pilot.press("enter")
                await pump_until(pilot=pilot, predicate=lambda: poller.busy)
                await asyncio.sleep(2.6)

                release_resumed_run.set()
                await pump_until(pilot=pilot, predicate=lambda: not poller.busy)
                await pilot.pause()
                assert poller.paused is None

                async def _resumed_reply_completed() -> bool:
                    conversation: list[ChannelMessageDAO] = await _conversation()
                    resumed = next(
                        (
                            r
                            for r in conversation
                            if r.message_contents == "second" and r.accepted_at is not None
                        ),
                        None,
                    )
                    if resumed is None:
                        return False
                    replies = [
                        r
                        for r in conversation
                        if r.message_type == "reply" and r.in_reply_to_id == resumed.id
                    ]
                    return len(replies) == 1 and replies[0].message_contents == "resumed answer"

                await _wait_until_db(predicate=_resumed_reply_completed, timeout_seconds=10.0)
        finally:
            await gateway.close()


class TestNotesReachABusyTui:
    """Native half of O1: notes from a running orchestrator reach a busy TUI at once."""

    async def test_note_from_the_orchestrator_shows_as_a_star_line_while_the_tui_runs(
        self, tmp_path: Path
    ) -> None:
        release_first_run: asyncio.Event = asyncio.Event()
        model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[AIMessage(content="busy answer")],
            first_call_release=release_first_run,
        )
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[], model=model)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier

            orchestrator_session_id: str = str(uuid4())
            orchestrator: ParticipantDAO = await gateway.register_agent(
                session_id=UUID(orchestrator_session_id), name="orchestrator wf-x1a2"
            )
            notifier: WorkflowNotifier = WorkflowNotifier(
                gateway=gateway,
                target_session_id=session.session_id,
                orchestrator_session_id=orchestrator_session_id,
                workflow_id="wf-x1a2",
            )
            async with app.run_test() as pilot:
                await pilot.pause()
                prompt_input: PromptInputComponent = app.query_one(PromptInputComponent)
                poller = session.channel_poller
                assert poller is not None
                prompt_input.text = "long question"
                await pilot.press("enter")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: poller.busy and _user_echo_texts(app=app) == ["long question"],
                )
                # The orchestrator reports while the TUI run is still in flight.
                await notifier.started(brief_preview="bounded brief")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: any(
                        "⊛ orchestrator wf-x1a2:" in content
                        for content, _classes in _transcript_lines(app=app)
                    ),
                )
                assert poller.busy is True  # the run never stopped for the note
                assert release_first_run.is_set() is False
        finally:
            release_first_run.set()
        # A busy note never revives the run (O2): it entered context at a
        # boundary as steering, not via the idle record path.
        from uuid import NAMESPACE_URL, uuid5

        from src.agents.slo_agent.orchestrator.notifier import NS_WORKFLOW

        note_id: UUID = uuid5(NS_WORKFLOW, "wf-x1a2:started:0")
        assert session.history_store is not None
        events = await session.history_store.load_events(session_id=session.session_id)
        steering = [
            event
            for event in events
            if event.kind == "steering_message"
            and event.payload.metadata.get("channel_message_id") == str(note_id)
        ]
        assert len(steering) == 1
        assert [event for event in events if event.kind == "workflow_update"] == []

    async def test_notice_from_the_orchestrator_shows_and_never_enters_context(self, tmp_path: Path) -> None:
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[AIMessage(content="answer")])
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            orchestrator_session_id: str = str(uuid4())
            orchestrator: ParticipantDAO = await gateway.register_agent(
                session_id=UUID(orchestrator_session_id), name="orchestrator wf-x1a2"
            )
            recipient: UUID = channel_participant_id_for_session(session_id=session.session_id)
            await gateway.register_agent(session_id=recipient, name="slo tui-session")
            await gateway.send(
                new=NewMessageDAO(
                    sender_id=orchestrator.id,
                    recipient_id=recipient,
                    message_contents="fleet: 2 live",
                    message_type="notice",
                    coalesce_key="wf-x1a2:fleet",
                )
            )
            async with app.run_test() as pilot:
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: any(
                        "⊛ orchestrator wf-x1a2: fleet: 2 live" in content
                        for content, _classes in _transcript_lines(app=app)
                    ),
                )
            assert session.history_store is not None
            events = await session.history_store.load_events(session_id=session.session_id)
            assert [event for event in events if event.kind == "workflow_update"] == []
        finally:
            await gateway.close()


class TestOutboundRepliesFromOtherAgents:
    """Replies from other agents render in the TUI; own-session replies do not (108.3 §3)."""

    async def test_reply_from_another_agent_renders_and_own_reply_does_not(self, tmp_path: Path) -> None:
        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[AIMessage(content="answer")])
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        try:
            orchestrator_session_id: str = str(uuid4())
            orchestrator: ParticipantDAO = await gateway.register_agent(
                session_id=UUID(orchestrator_session_id), name="orchestrator wf-x1a2"
            )
            async with app.run_test() as pilot:
                await pump_until(pilot=pilot, predicate=lambda: app.channel_adapter is not None)
                adapter = app.channel_adapter
                assert adapter is not None
                own_agent: UUID = channel_participant_id_for_session(session_id=session.session_id)
                user: ParticipantDAO = adapter.user_participant
                request: ChannelMessageDAO = await gateway.send(
                    new=NewMessageDAO(
                        sender_id=user.id,
                        recipient_id=own_agent,
                        message_contents="what happened?",
                        channel_id=adapter.channel.id,
                    )
                )
                foreign_reply: ChannelMessageDAO = await gateway.send(
                    new=NewMessageDAO(
                        sender_id=orchestrator.id,
                        recipient_id=user.id,
                        message_contents="the workflow finished its phase",
                        message_type="reply",
                        in_reply_to_id=request.id,
                    )
                )
                own_reply: ChannelMessageDAO = await gateway.send(
                    new=NewMessageDAO(
                        sender_id=own_agent,
                        recipient_id=user.id,
                        message_contents="stream already showed this",
                        message_type="reply",
                        in_reply_to_id=request.id,
                    )
                )
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: any(
                        "↩ orchestrator wf-x1a2: the workflow finished its phase" in content
                        for content, _classes in _transcript_lines(app=app)
                    ),
                )
                assert all(
                    "stream already showed this" not in content
                    for content, _classes in _transcript_lines(app=app)
                )

                async def _both_accepted() -> bool:
                    foreign: Optional[ChannelMessageDAO] = await gateway.find_message(
                        message_id=foreign_reply.id
                    )
                    own: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=own_reply.id)
                    return (
                        foreign is not None
                        and foreign.accepted_at is not None
                        and own is not None
                        and own.accepted_at is not None
                    )

                await _wait_until_db(predicate=_both_accepted)
        finally:
            await gateway.close()


class _FailsOnceAfterDisplayObserver:
    """Row-observer seam (injected): the first observation of each row fails, later ones succeed."""

    def __init__(self) -> None:
        """Record no observations yet."""
        self.calls: list[UUID] = []
        self.observed: list[UUID] = []

    async def __call__(self, *, message: ChannelMessageDAO) -> None:
        """Fail the first observation of a row; record every later one as observed.

        Args:
            message (ChannelMessageDAO): The row the sink displayed.

        Raises:
            RuntimeError: On the first observation of ``message``.
        """
        first_call: bool = message.id not in self.calls
        self.calls.append(message.id)
        if first_call:
            raise RuntimeError("workflow reconcile unavailable")
        self.observed.append(message.id)


class _NeverRunsTurnRunner:
    """Turn-runner seam: ``auto_run=False`` never starts a poller-owned run."""

    async def run(self, *, message: ChannelMessageDAO, on_started: object) -> object:
        """Fail loudly if the poller ever starts a run."""
        raise AssertionError("auto_run=False never starts runs")


class TestObserverFailureNeverRepeatsADisplayedRow:
    """A row's ``⊛`` line is written once even when its observer fails after the display (108.3 §2)."""

    async def test_note_and_notice_display_once_and_their_observation_is_retried_until_it_succeeds(
        self, tmp_path: Path
    ) -> None:
        from src.tui.channel.adapter import TuiDisplaySink

        session: SloAgentSession = _build_session(tmp_path=tmp_path, responses=[AIMessage(content="answer")])
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        app: SloTUI = SloTUI(session=session, channel_gateway=gateway)
        observer: _FailsOnceAfterDisplayObserver = _FailsOnceAfterDisplayObserver()
        delivered: SloAgentSession = _build_session(
            tmp_path=tmp_path, responses=[AIMessage(content="unused")]
        )
        try:
            orchestrator: ParticipantDAO = await gateway.register_agent(
                session_id=uuid4(), name="orchestrator wf-r2"
            )
            async with app.run_test() as pilot:
                await pilot.pause()
                poller = await delivered.start_channel_delivery(
                    gateway=gateway,
                    runner=_NeverRunsTurnRunner(),  # type: ignore[arg-type]
                    interval=0.02,
                    display=TuiDisplaySink(
                        transcript=app.query_one(ChatTranscriptComponent), observer=observer
                    ),
                    auto_run=False,
                )
                try:
                    note: ChannelMessageDAO = await gateway.send(
                        new=NewMessageDAO(
                            sender_id=orchestrator.id,
                            recipient_id=poller.participant_id,
                            message_contents="[workflow wf-r2] phase done",
                            message_type="note",
                        )
                    )
                    notice: ChannelMessageDAO = await gateway.send(
                        new=NewMessageDAO(
                            sender_id=orchestrator.id,
                            recipient_id=poller.participant_id,
                            message_contents="fleet: 1 live",
                            message_type="notice",
                        )
                    )
                    await pump_until(
                        pilot=pilot,
                        predicate=lambda: sorted(observer.observed) == sorted([note.id, notice.id]),
                    )

                    async def _notice_accepted() -> bool:
                        stored: Optional[ChannelMessageDAO] = await gateway.find_message(message_id=notice.id)
                        return stored is not None and stored.accepted_at is not None

                    await _wait_until_db(predicate=_notice_accepted)
                    # Further ticks neither repeat a line nor re-observe a settled row.
                    for _ in range(10):
                        await pilot.pause(0.02)
                    lines: list[str] = [content for content, _classes in _transcript_lines(app=app)]
                    assert lines.count("⊛ orchestrator wf-r2: [workflow wf-r2] phase done") == 1
                    assert lines.count("⊛ orchestrator wf-r2: fleet: 1 live") == 1
                    assert sorted(observer.calls) == sorted([note.id, note.id, notice.id, notice.id])
                finally:
                    await delivered.stop_channel_delivery(reason="test_done")
        finally:
            await gateway.close()
