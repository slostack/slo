"""Unit tests for ``ChannelBoundaryInbox`` (108.2).

The adapter binds one agent participant to the shared channel queue: the
poller refreshes its forced-row snapshot every tick, the agent takes the
pending forced prompt rows at a safe boundary, and confirms them (accepts)
after the history record is written. Real SQLite; no mocks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from src.agents.slo_agent.boundary_inbox import BoundaryDeliveryDAO
from src.agents.slo_agent.channel_delivery.boundary_inbox import ChannelBoundaryInbox
from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


async def _open_world(*, tmp_path: Path) -> tuple[ChannelGateway, ChannelDAO, ParticipantDAO, ParticipantDAO]:
    """Open one real gateway and register a TUI user and one agent."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    gateway: ChannelGateway = ChannelGateway(repository=repository)
    channel: ChannelDAO = await gateway.register_channel(kind="tui", name="tui@testhost")
    user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="tester (tui)")
    agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo abc12345")
    return gateway, channel, user, agent


async def _send(
    *,
    gateway: ChannelGateway,
    sender_id: UUID,
    recipient_id: UUID,
    text: str,
    force: bool = False,
    message_type: str = "prompt",
) -> ChannelMessageDAO:
    """Insert one row through the gateway."""
    return await gateway.send(
        new=NewMessageDAO(
            sender_id=sender_id,
            recipient_id=recipient_id,
            message_contents=text,
            force=force,
            message_type=message_type,  # type: ignore[arg-type]
        )
    )


class TestForcedSnapshot:
    async def test_refresh_reports_forced_only_after_a_forced_row_arrives(self, tmp_path: Path) -> None:
        """The snapshot flips to True only when a pending forced prompt row exists."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            await inbox.refresh()
            assert inbox.has_forced() is False
            await _send(gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="run tests")
            await inbox.refresh()
            assert inbox.has_forced() is False
            forced_row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="use pytest -x", force=True
            )
            await inbox.refresh()
            assert inbox.has_forced() is True
            await gateway.accept(message_id=forced_row.id)
            await inbox.refresh()
            assert inbox.has_forced() is False
        finally:
            await gateway.close()

    async def test_refresh_ignores_non_prompt_and_cancelled_rows(self, tmp_path: Path) -> None:
        """A forced ``note`` row or a cancelled forced row never sets the flag."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            await _send(
                gateway=gateway,
                sender_id=user.id,
                recipient_id=agent.id,
                text="fyi",
                force=True,
                message_type="note",
            )
            await inbox.refresh()
            assert inbox.has_forced() is False
        finally:
            await gateway.close()


class TestOperatorSenderIdentity:
    """The operator's own rows take the transcript label ``you`` (108.2 §4);
    rows from other senders keep their label so the transcript credits them."""

    async def test_operator_rows_take_the_you_label_and_external_rows_keep_theirs(
        self, tmp_path: Path
    ) -> None:
        """The inbox maps the operator participant to ``you``; others keep their label."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            external: ParticipantDAO = await gateway.register_user(
                channel_id=channel.id, name="orchestrator wf-12"
            )
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(
                gateway=gateway,
                agent_id=agent.id,
                operator_participant_id=user.id,
            )
            own_row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="run tests", force=True
            )
            external_row: ChannelMessageDAO = await _send(
                gateway=gateway,
                sender_id=external.id,
                recipient_id=agent.id,
                text="deploy to staging",
                force=True,
            )
            deliveries = await inbox.take(iteration=1)
            by_id: dict[UUID, BoundaryDeliveryDAO] = {
                delivery.message_id: delivery for delivery in deliveries
            }
            assert by_id[own_row.id].sender_name == "you"
            assert by_id[external_row.id].sender_name == "orchestrator wf-12"
        finally:
            await gateway.close()

    async def test_without_the_operator_identity_every_row_keeps_its_label(self, tmp_path: Path) -> None:
        """Agents that do not know the operator keep the raw sender labels."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            own_row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="run tests", force=True
            )
            deliveries = await inbox.take(iteration=1)
            assert deliveries[0].message_id == own_row.id
            assert deliveries[0].sender_name == "tester (tui)"
        finally:
            await gateway.close()


class TestTakeAndConfirm:
    async def test_take_returns_pending_forced_prompt_rows_fifo(self, tmp_path: Path) -> None:
        """``take`` returns every pending forced prompt row in index order."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            first: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="first forced", force=True
            )
            second: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="second forced", force=True
            )
            deliveries = await inbox.take(iteration=4)
            assert [delivery.message_id for delivery in deliveries] == [first.id, second.id]
            assert [delivery.text for delivery in deliveries] == ["first forced", "second forced"]
            assert [delivery.sender_name for delivery in deliveries] == ["tester (tui)", "tester (tui)"]
            assert [delivery.iteration for delivery in deliveries] == [4, 4]
        finally:
            await gateway.close()

    async def test_take_takes_notes_before_forced_prompts_but_never_normal_rows(self, tmp_path: Path) -> None:
        """Notes join the boundary first (108.3), forced prompts next; normal prompts wait."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            await _send(gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="normal")
            note_row: ChannelMessageDAO = await _send(
                gateway=gateway,
                sender_id=user.id,
                recipient_id=agent.id,
                text="note",
                message_type="note",
            )
            forced_row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="forced", force=True
            )
            deliveries = await inbox.take(iteration=1)
            assert [delivery.message_id for delivery in deliveries] == [note_row.id, forced_row.id]
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            # The taken-but-not-yet confirmed note and forced prompt, and the
            # normal prompt, remain pending until they are confirmed.
            assert {row.message_contents for row in pending} == {"note", "forced", "normal"}
        finally:
            await gateway.close()

    async def test_confirm_accepts_each_delivery_exactly_once(self, tmp_path: Path) -> None:
        """``confirm`` accepts every taken row; they leave the pending set."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="forced", force=True
            )
            deliveries = await inbox.take(iteration=1)
            await inbox.confirm(deliveries=deliveries)
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row.id)
            assert stored is not None and stored.accepted_at is not None
            assert await gateway.pending_inbound(recipient_id=agent.id) == []
        finally:
            await gateway.close()

    async def test_unconfirmed_deliveries_stay_pending_after_take(self, tmp_path: Path) -> None:
        """A crash between ``take`` and ``confirm`` leaves the row pending (108.2 F4)."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="forced", force=True
            )
            deliveries = await inbox.take(iteration=1)
            assert deliveries
            stored: Optional[ChannelMessageDAO] = await gateway.get(message_id=row.id)
            assert stored is not None and stored.accepted_at is None
            assert stored.forced_at is not None
        finally:
            await gateway.close()


class TestInFlightSnapshotExclusion:
    """A refresh between ``take`` and ``confirm`` must not reinsert taken ids
    into the snapshot, and a cancelled cached row must not falsely revive the
    run (108.2 B3)."""

    async def test_refresh_between_take_and_confirm_does_not_reinsert_taken_ids(self, tmp_path: Path) -> None:
        """A mid-boundary refresh keeps taken rows out of the revive snapshot."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="forced", force=True
            )
            await inbox.refresh()
            assert inbox.has_forced() is True
            deliveries = await inbox.take(iteration=2)
            assert [delivery.message_id for delivery in deliveries] == [row.id]
            # The row is still pending in the queue (not confirmed yet), so a
            # refresh re-reads it — but it is in flight and must not revive.
            await inbox.refresh()
            assert inbox.has_forced() is False
            await inbox.confirm(deliveries=deliveries)
            await inbox.refresh()
            assert inbox.has_forced() is False
        finally:
            await gateway.close()

    async def test_cancelled_cached_row_does_not_falsely_revive(self, tmp_path: Path) -> None:
        """A cancelled row leaves the snapshot; the boundary take is empty."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="forced", force=True
            )
            await inbox.refresh()
            assert inbox.has_forced() is True
            await gateway.cancel(message_id=row.id, reason="operator")
            # The stale snapshot still reports the row until it is reconciled.
            await inbox.refresh()
            assert inbox.has_forced() is False
            deliveries = await inbox.take(iteration=1)
            assert deliveries == []
            assert inbox.has_forced() is False
        finally:
            await gateway.close()

    async def test_take_with_a_stale_snapshot_reconciles_and_reports_empty(self, tmp_path: Path) -> None:
        """A stale snapshot between cancel and take reconciles to an empty take."""
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            row: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="forced", force=True
            )
            await inbox.refresh()
            assert inbox.has_forced() is True
            await gateway.cancel(message_id=row.id, reason="operator")
            # No refresh runs: the snapshot is stale and still reports the row.
            deliveries = await inbox.take(iteration=1)
            assert deliveries == []
            # The fresh read reconciled the snapshot, so the revive decision
            # after this boundary sees no forced row and stops the run.
            assert inbox.has_forced() is False
        finally:
            await gateway.close()


class TestNotesAtTheBoundary:
    """Notes join the next boundary before forced prompts and never revive a run (1083 O2)."""

    async def test_take_returns_notes_before_forced_prompts_and_confirms_both(self, tmp_path: Path) -> None:
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            forced: ChannelMessageDAO = await _send(
                gateway=gateway, sender_id=user.id, recipient_id=agent.id, text="use pytest -x", force=True
            )
            note: ChannelMessageDAO = await _send(
                gateway=gateway,
                sender_id=user.id,
                recipient_id=agent.id,
                text="note while busy",
                message_type="note",
            )
            deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=3)
            assert [delivery.message_id for delivery in deliveries] == [note.id, forced.id]
            assert deliveries[0].text == "note while busy"
            assert deliveries[0].sender_name == "tester (tui)"
            await inbox.confirm(deliveries=deliveries)
            stored_note: Optional[ChannelMessageDAO] = await gateway.get(message_id=note.id)
            stored_forced: Optional[ChannelMessageDAO] = await gateway.get(message_id=forced.id)
            assert stored_note is not None and stored_note.accepted_at is not None
            assert stored_forced is not None and stored_forced.accepted_at is not None
        finally:
            await gateway.close()

    async def test_notes_never_set_has_forced_so_they_cannot_revive_a_run(self, tmp_path: Path) -> None:
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            await _send(
                gateway=gateway,
                sender_id=user.id,
                recipient_id=agent.id,
                text="fyi",
                message_type="note",
            )
            await inbox.refresh()
            assert inbox.has_forced() is False
            deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=1)
            assert len(deliveries) == 1
            # A note taken but not yet confirmed still never reads as forced.
            assert inbox.has_forced() is False
        finally:
            await gateway.close()

    async def test_a_taken_note_is_never_taken_twice_before_confirm(self, tmp_path: Path) -> None:
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            await _send(
                gateway=gateway,
                sender_id=user.id,
                recipient_id=agent.id,
                text="fyi",
                message_type="note",
            )
            first: list[BoundaryDeliveryDAO] = await inbox.take(iteration=1)
            second: list[BoundaryDeliveryDAO] = await inbox.take(iteration=2)
            assert len(first) == 1
            assert second == []
            await inbox.confirm(deliveries=first)
        finally:
            await gateway.close()

    async def test_reserved_rows_are_never_taken(self, tmp_path: Path) -> None:
        gateway, channel, user, agent = await _open_world(tmp_path=tmp_path)
        try:
            inbox: ChannelBoundaryInbox = ChannelBoundaryInbox(gateway=gateway, agent_id=agent.id)
            note: ChannelMessageDAO = await _send(
                gateway=gateway,
                sender_id=user.id,
                recipient_id=agent.id,
                text="fyi",
                message_type="note",
            )
            inbox.reserve(message_id=note.id)
            deliveries: list[BoundaryDeliveryDAO] = await inbox.take(iteration=1)
            assert deliveries == []
            inbox.release(message_id=note.id)
            deliveries_after: list[BoundaryDeliveryDAO] = await inbox.take(iteration=2)
            assert [delivery.message_id for delivery in deliveries_after] == [note.id]
        finally:
            await gateway.close()
