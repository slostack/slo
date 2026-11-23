"""Regression journeys for TUI channel-queue operator controls."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage
from textual.widgets import Static

from tests.conftest import GatedFauxChatModel
from tests.tui._scroll_settle import pump_until
from src.agents.slo_agent.agent import SloAgent
from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.sessions.service import SloAgentSession
from src.channels.dao import ChannelMessageDAO, NewMessageDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository
from src.tui.app import SloTUI
from src.tui.components.chat_transcript.component import ChatTranscriptComponent
from src.tui.components.prompt_input.component import PromptInputComponent


class ControlledQueueGateway(ChannelGateway):
    """Real SQLite gateway with deterministic failures at its operator boundary."""

    def __init__(self, *, repository: ChannelRepository) -> None:
        """Bind a real repository and leave the failure controls disabled."""
        super().__init__(repository=repository)
        self.fail_queue_reads: bool = False
        self.fail_cancellations: bool = False
        self.fail_after_cancel_commit: bool = False
        self.blocked_message_id: Optional[UUID] = None
        self.block_next_lookup: bool = False
        self.lookup_blocked: asyncio.Event = asyncio.Event()
        self.release_lookup: asyncio.Event = asyncio.Event()

    async def pending_inbound(self, *, recipient_id: UUID) -> list[ChannelMessageDAO]:
        """Raise an injected database-read failure or query the real repository."""
        if self.fail_queue_reads:
            raise OSError("queue read unavailable")
        return await super().pending_inbound(recipient_id=recipient_id)

    async def cancel(self, *, message_id: UUID, by: Optional[UUID] = None, reason: str = "operator") -> bool:
        """Inject a cancellation failure before or after a real SQLite commit."""
        if self.fail_cancellations:
            raise OSError("queue mutation unavailable")
        cancelled: bool = await super().cancel(message_id=message_id, by=by, reason=reason)
        if cancelled and self.fail_after_cancel_commit:
            self.fail_after_cancel_commit = False
            raise OSError("queue cancellation result unknown")
        return cancelled

    async def get(self, *, message_id: UUID) -> Optional[ChannelMessageDAO]:
        """Hold one row lookup so a Pilot can change the draft during `/queue edit`."""
        if self.blocked_message_id == message_id and self.block_next_lookup:
            self.block_next_lookup = False
            self.lookup_blocked.set()
            await self.release_lookup.wait()
        return await super().get(message_id=message_id)


class QueueTuiScenario:
    """Mounted TUI over a real session and a disposable SQLite queue."""

    def __init__(self, *, tmp_path: Path) -> None:
        """Build the scripted provider, real session, gateway and app."""
        self.release_model: asyncio.Event = asyncio.Event()
        self.model: GatedFauxChatModel = GatedFauxChatModel(
            responses=[AIMessage(content="unused")],
            first_call_release=self.release_model,
        )
        self.session: SloAgentSession = SloAgentSession(
            agent=SloAgent(llm=self.model, cwd=str(tmp_path), tools=[]),
            workdir=tmp_path,
            session_id=str(uuid4()),
            history_store=FilesystemSessionHistoryStore(root=tmp_path / "history"),
            enable_history=True,
        )
        repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
        self.gateway: ControlledQueueGateway = ControlledQueueGateway(repository=repository)
        self.app: SloTUI = SloTUI(session=self.session, channel_gateway=self.gateway)

    async def close(self) -> None:
        """Release any provider gate, stop session delivery, and close SQLite."""
        self.release_model.set()
        await self.session.stop_channel_delivery(reason="test_done")
        await self.gateway.close()


async def _wait_until(*, predicate: Callable[[], Awaitable[bool]], timeout_seconds: float = 5.0) -> None:
    """Poll an async condition with a bounded wait."""
    async with asyncio.timeout(timeout_seconds):
        while not await predicate():
            await asyncio.sleep(0.01)


def _transcript_lines(*, app: SloTUI) -> list[tuple[str, str]]:
    """Read rendered transcript lines from the real mounted presentation adapter."""
    transcript: ChatTranscriptComponent = app.query_one(ChatTranscriptComponent)
    assert transcript._adapter is not None
    return transcript._adapter.lines


async def _submit(*, pilot, prompt_input: PromptInputComponent, text: str) -> None:
    """Submit text through Textual Pilot's real prompt component."""
    prompt_input.text = text
    await pilot.press("enter")


async def _one_pending_prompt(*, scenario: QueueTuiScenario) -> bool:
    """Return whether the session poller sees exactly one pending prompt."""
    poller = scenario.session.channel_poller
    assert poller is not None
    return len(await poller.pending_prompts()) == 1


class TestQueueOperatorRegressionJourneys:
    async def test_database_recovery_notice_names_the_preserved_copy(self, tmp_path: Path) -> None:
        """Mounted startup reports that corrupt queue data was preserved for inspection."""
        channels_directory: Path = tmp_path / "channels"
        channels_directory.mkdir()
        queue_path: Path = channels_directory / "channels.db"
        queue_path.write_bytes(b"truncated channel database")
        scenario: QueueTuiScenario = QueueTuiScenario(tmp_path=tmp_path)
        scenario.gateway = ControlledQueueGateway(repository=ChannelRepository(db_path=queue_path))
        scenario.app = SloTUI(session=scenario.session, channel_gateway=scenario.gateway)
        try:
            async with scenario.app.run_test() as pilot:
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: any(
                        "channel queue database was corrupt" in content
                        for content, _classes in _transcript_lines(app=scenario.app)
                    ),
                )
                recovery_copy: Optional[Path] = scenario.gateway.recovery_path
                assert recovery_copy is not None
                assert recovery_copy.is_file()
                assert recovery_copy.read_bytes() == b"truncated channel database"
                assert any(
                    recovery_copy.name in content for content, _classes in _transcript_lines(app=scenario.app)
                )
        finally:
            await scenario.close()

    async def test_recipient_operator_cancels_prompt_from_another_sender(self, tmp_path: Path) -> None:
        """Queue cancellation is recipient authority, not a sender-only right."""
        scenario: QueueTuiScenario = QueueTuiScenario(tmp_path=tmp_path)
        try:
            async with scenario.app.run_test() as pilot:
                await pilot.pause()
                poller = scenario.session.channel_poller
                assert poller is not None
                poller.pause(reason="held")
                remote_channel = await scenario.gateway.register_channel(kind="telegram", name="remote")
                remote_user = await scenario.gateway.register_user(
                    channel_id=remote_channel.id, name="remote sender"
                )
                prompt: ChannelMessageDAO = await scenario.gateway.send(
                    new=NewMessageDAO(
                        sender_id=remote_user.id,
                        recipient_id=channel_participant_id_for_session(
                            session_id=scenario.session.session_id
                        ),
                        message_contents="remote prompt",
                        channel_id=remote_channel.id,
                    )
                )
                await _submit(
                    pilot=pilot,
                    prompt_input=scenario.app.query_one(PromptInputComponent),
                    text="/queue cancel 1",
                )
                stored: Optional[ChannelMessageDAO] = await scenario.gateway.get(message_id=prompt.id)
                assert stored is not None
                assert (stored.cancel_reason, stored.accepted_at) == ("operator", None)
                assert all("remote prompt" not in call for call in scenario.model.provider_calls)
        finally:
            await scenario.close()

    async def test_committed_cancel_with_lost_result_does_not_leave_stale_queue_row(
        self, tmp_path: Path
    ) -> None:
        """An uncertain SQLite cancellation result reports safely and refreshes committed state."""
        scenario: QueueTuiScenario = QueueTuiScenario(tmp_path=tmp_path)
        try:
            async with scenario.app.run_test() as pilot:
                await pilot.pause()
                poller = scenario.session.channel_poller
                assert poller is not None
                poller.pause(reason="held")
                prompt_input: PromptInputComponent = scenario.app.query_one(PromptInputComponent)
                await _submit(pilot=pilot, prompt_input=prompt_input, text="cancel once")
                await _wait_until(predicate=lambda: _one_pending_prompt(scenario=scenario))
                prompt_rows: list[ChannelMessageDAO] = await scenario.gateway.repository.conversation(
                    agent_session_id=poller.participant_id
                )
                prompt: ChannelMessageDAO = next(
                    message for message in prompt_rows if message.message_contents == "cancel once"
                )
                scenario.gateway.fail_after_cancel_commit = True
                await _submit(pilot=pilot, prompt_input=prompt_input, text="/queue cancel 1")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: any(
                        "Queue update failed" in content
                        for content, _classes in _transcript_lines(app=scenario.app)
                    ),
                )
                stored: Optional[ChannelMessageDAO] = await scenario.gateway.get(message_id=prompt.id)
                assert stored is not None and stored.cancel_reason == "operator"
                assert await poller.pending_prompts() == []
                assert any(
                    "Queue update failed" in str(widget.render()) for widget in scenario.app.query(Static)
                )
        finally:
            scenario.gateway.fail_after_cancel_commit = False
            await scenario.close()

    async def test_queue_read_failure_after_send_does_not_restore_or_report_send_failure(
        self, tmp_path: Path
    ) -> None:
        """Refresh failure after an inserted prompt is not reported as a failed send."""
        scenario: QueueTuiScenario = QueueTuiScenario(tmp_path=tmp_path)
        try:
            async with scenario.app.run_test() as pilot:
                await pilot.pause()
                poller = scenario.session.channel_poller
                assert poller is not None
                poller.pause(reason="held")
                scenario.gateway.fail_queue_reads = True
                prompt_input: PromptInputComponent = scenario.app.query_one(PromptInputComponent)
                await _submit(pilot=pilot, prompt_input=prompt_input, text="insert once")
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: any(
                        "could not be refreshed" in content
                        for content, _classes in _transcript_lines(app=scenario.app)
                    ),
                )
                rows: list[ChannelMessageDAO] = await scenario.gateway.repository.conversation(
                    agent_session_id=poller.participant_id
                )
                prompts: list[ChannelMessageDAO] = [
                    message for message in rows if message.message_contents == "insert once"
                ]
                assert len(prompts) == 1
                assert prompt_input.text == ""
                assert all(
                    "channel send failed" not in content
                    for content, _classes in _transcript_lines(app=scenario.app)
                )
        finally:
            scenario.gateway.fail_queue_reads = False
            await scenario.close()

    async def test_queue_edit_preserves_a_draft_typed_while_cancellation_waits(self, tmp_path: Path) -> None:
        """An in-flight edit command never replaces a newer unsaved prompt draft."""
        scenario: QueueTuiScenario = QueueTuiScenario(tmp_path=tmp_path)
        try:
            async with scenario.app.run_test() as pilot:
                await pilot.pause()
                poller = scenario.session.channel_poller
                assert poller is not None
                poller.pause(reason="held")
                prompt_input: PromptInputComponent = scenario.app.query_one(PromptInputComponent)
                await _submit(pilot=pilot, prompt_input=prompt_input, text="one")
                await _submit(pilot=pilot, prompt_input=prompt_input, text="two")

                async def _both_prompts_pending() -> bool:
                    pending: list[ChannelMessageDAO] = await poller.pending_prompts()
                    return [message.message_contents for message in pending] == ["one", "two"]

                await _wait_until(predicate=_both_prompts_pending)
                queue_rows: list[ChannelMessageDAO] = await scenario.gateway.repository.conversation(
                    agent_session_id=poller.participant_id
                )
                queued_prompt: ChannelMessageDAO = next(
                    message for message in queue_rows if message.message_contents == "two"
                )
                scenario.gateway.blocked_message_id = queued_prompt.id
                scenario.gateway.block_next_lookup = True
                slash_dispatch: asyncio.Task[None] = asyncio.create_task(
                    _submit(pilot=pilot, prompt_input=prompt_input, text="/queue edit 2")
                )
                await asyncio.wait_for(scenario.gateway.lookup_blocked.wait(), timeout=5.0)
                prompt_input.text = "newer draft"
                scenario.gateway.release_lookup.set()
                await slash_dispatch
                await pump_until(
                    pilot=pilot,
                    predicate=lambda: (
                        prompt_input.text == "newer draft"
                        and any(
                            "Copy this text to recover" in content and "two" in content
                            for content, _classes in _transcript_lines(app=scenario.app)
                        )
                    ),
                )
                stored: Optional[ChannelMessageDAO] = await scenario.gateway.get(message_id=queued_prompt.id)
                assert prompt_input.text == "newer draft"
                assert stored is not None and stored.cancel_reason == "operator"
        finally:
            await scenario.close()
