"""Gateway additions for external channels (108.5 §3 Gateway row).

Level: application service → repository → real SQLite WAL file under
``tmp_path``. No mocks: agents, users and replies are real rows.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from src.channels.dao import ChannelDAO, ChannelMessageDAO, NewMessageDAO, ParticipantDAO
from src.channels.errors import (
    AmbiguousAgentError,
    MessageCancelledError,
    ReplyTimeoutError,
    UnknownAgentError,
    UnknownMessageError,
)
from src.channels.gateway import ChannelGateway
from src.channels.repository import ChannelRepository


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    """Open one gateway over a fresh temp database."""
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


def _uuid_with_prefix(*, prefix: str) -> UUID:
    """Return a fresh UUID whose text starts with ``prefix``."""
    tail: str = uuid4().hex
    text: str = (prefix + tail)[:32]
    return UUID(hex=text)


class TestListAgents:
    async def test_open_only_lists_open_agents_newest_seen_first(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            first: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo first")
            second: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo second")
            closed: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo done")
            await gateway.close_agent(session_id=closed.id, reason="session_closed")
            channel: ChannelDAO = await gateway.register_channel(kind="cli", name="cli@host")
            await gateway.register_user(channel_id=channel.id, name="me (cli)", external_ref="me")
            await gateway.heartbeat(participant_id=first.id)

            open_agents: list[ParticipantDAO] = await gateway.list_agents(open_only=True)
            every_agent: list[ParticipantDAO] = await gateway.list_agents(open_only=False)

            assert [agent.id for agent in open_agents] == [first.id, second.id]
            assert {agent.id for agent in every_agent} == {first.id, second.id, closed.id}
            assert all(agent.kind == "agent" for agent in every_agent)
        finally:
            await gateway.close()


class TestResolveAgent:
    async def test_unique_prefix_resolves_case_insensitively(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            target: ParticipantDAO = await gateway.register_agent(
                session_id=_uuid_with_prefix(prefix="9b1e"), name="slo target"
            )
            await gateway.register_agent(session_id=_uuid_with_prefix(prefix="77d0"), name="slo other")

            resolved: ParticipantDAO = await gateway.resolve_agent(prefix=" 9B1E ")

            assert resolved.id == target.id
        finally:
            await gateway.close()

    async def test_open_match_wins_over_a_closed_match(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            stale: ParticipantDAO = await gateway.register_agent(
                session_id=_uuid_with_prefix(prefix="abcd1"), name="slo stale"
            )
            await gateway.close_agent(session_id=stale.id, reason="session_closed")
            live: ParticipantDAO = await gateway.register_agent(
                session_id=_uuid_with_prefix(prefix="abcd2"), name="slo live"
            )

            assert (await gateway.resolve_agent(prefix="abcd")).id == live.id
        finally:
            await gateway.close()

    async def test_only_closed_match_is_returned_so_callers_report_closed(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            done: ParticipantDAO = await gateway.register_agent(
                session_id=_uuid_with_prefix(prefix="c0ffee"), name="slo done"
            )
            await gateway.close_agent(session_id=done.id, reason="session_closed")

            resolved: ParticipantDAO = await gateway.resolve_agent(prefix="c0ffee")

            assert resolved.id == done.id
            assert resolved.status == "closed"
        finally:
            await gateway.close()

    async def test_two_open_matches_are_ambiguous(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await gateway.register_agent(session_id=_uuid_with_prefix(prefix="aaaa1"), name="slo one")
            await gateway.register_agent(session_id=_uuid_with_prefix(prefix="aaaa2"), name="slo two")

            with pytest.raises(AmbiguousAgentError) as raised:
                await gateway.resolve_agent(prefix="aaaa")
            assert raised.value.match_count == 2
        finally:
            await gateway.close()

    @pytest.mark.parametrize("prefix", ["", "   ", "zz", "9b1e%", "_"])
    async def test_no_match_or_invalid_prefix_is_unknown(self, tmp_path: Path, prefix: str) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            await gateway.register_agent(session_id=_uuid_with_prefix(prefix="9b1e"), name="slo target")

            with pytest.raises(UnknownAgentError):
                await gateway.resolve_agent(prefix=prefix)
        finally:
            await gateway.close()

    async def test_users_never_resolve_as_agents(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="cli", name="cli@host")
            user: ParticipantDAO = await gateway.register_user(channel_id=channel.id, name="me (cli)")

            with pytest.raises(UnknownAgentError):
                await gateway.resolve_agent(prefix=str(user.id)[:8])
        finally:
            await gateway.close()


async def _user_and_agent(*, gateway: ChannelGateway) -> tuple[ChannelDAO, ParticipantDAO, ParticipantDAO]:
    """Register one CLI channel, its user and one open agent."""
    channel: ChannelDAO = await gateway.register_channel(kind="cli", name="cli@host")
    user: ParticipantDAO = await gateway.register_user(
        channel_id=channel.id, name="me (cli)", external_ref="me"
    )
    agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
    return channel, user, agent


class TestWaitForReply:
    async def test_returns_the_reply_written_later_by_another_connection(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        agent_side: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel, user, agent = await _user_and_agent(gateway=gateway)
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id,
                    recipient_id=agent.id,
                    message_contents="status?",
                    channel_id=channel.id,
                )
            )

            async def _answer_later() -> None:
                await asyncio.sleep(0.3)
                await agent_side.accept(message_id=request.id)
                await agent_side.send(
                    new=NewMessageDAO(
                        sender_id=agent.id,
                        recipient_id=user.id,
                        message_contents="all green",
                        message_type="reply",
                        in_reply_to_id=request.id,
                        channel_id=channel.id,
                    )
                )

            answering: asyncio.Task[None] = asyncio.create_task(_answer_later())
            reply: ChannelMessageDAO = await gateway.wait_for_reply(message_id=request.id, timeout=5.0)
            await answering

            assert reply.message_contents == "all green"
            assert reply.in_reply_to_id == request.id
            assert reply.accepted_at is None  # delivering (and accepting) is the caller's job
        finally:
            await agent_side.close()
            await gateway.close()

    async def test_times_out_without_a_reply(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel, user, agent = await _user_and_agent(gateway=gateway)
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(sender_id=user.id, recipient_id=agent.id, message_contents="hello?")
            )
            started: float = asyncio.get_running_loop().time()

            with pytest.raises(ReplyTimeoutError):
                await gateway.wait_for_reply(message_id=request.id, timeout=0.4)

            assert asyncio.get_running_loop().time() - started < 2.0
        finally:
            await gateway.close()

    async def test_a_request_cancelled_by_the_closing_agent_stops_the_wait(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel, user, agent = await _user_and_agent(gateway=gateway)
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(sender_id=user.id, recipient_id=agent.id, message_contents="hello?")
            )
            await gateway.close_agent(session_id=agent.id, reason="recipient_closed")

            with pytest.raises(MessageCancelledError) as raised:
                await gateway.wait_for_reply(message_id=request.id, timeout=5.0)
            assert raised.value.reason == "recipient_closed"
        finally:
            await gateway.close()

    async def test_unknown_message_is_refused(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            with pytest.raises(UnknownMessageError):
                await gateway.wait_for_reply(message_id=uuid4(), timeout=0.5)
        finally:
            await gateway.close()


class TestWaitForAcceptance:
    async def test_returns_the_row_once_accepted(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel, user, agent = await _user_and_agent(gateway=gateway)
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="now", force=True
                )
            )

            async def _accept_later() -> None:
                await asyncio.sleep(0.2)
                await gateway.accept(message_id=request.id)

            accepting: asyncio.Task[None] = asyncio.create_task(_accept_later())
            accepted: ChannelMessageDAO = await gateway.wait_for_acceptance(
                message_id=request.id, timeout=5.0
            )
            await accepting

            assert accepted.id == request.id
            assert accepted.accepted_at is not None
        finally:
            await gateway.close()

    async def test_times_out_while_still_pending(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel, user, agent = await _user_and_agent(gateway=gateway)
            request: ChannelMessageDAO = await gateway.send(
                new=NewMessageDAO(
                    sender_id=user.id, recipient_id=agent.id, message_contents="now", force=True
                )
            )

            with pytest.raises(ReplyTimeoutError):
                await gateway.wait_for_acceptance(message_id=request.id, timeout=0.3)
        finally:
            await gateway.close()


class TestChannelUsersAndHeartbeat:
    async def test_channel_users_lists_only_that_channels_users(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            telegram: ChannelDAO = await gateway.register_channel(kind="telegram", name="telegram")
            other: ChannelDAO = await gateway.register_channel(kind="telegram", name="work-telegram")
            alice: ParticipantDAO = await gateway.register_user(
                channel_id=telegram.id, name="alice (telegram)", external_ref="1"
            )
            bob: ParticipantDAO = await gateway.register_user(
                channel_id=telegram.id, name="bob (telegram)", external_ref="2"
            )
            await gateway.register_user(channel_id=other.id, name="alice (work)", external_ref="1")
            await gateway.register_agent(session_id=uuid4(), name="slo agent")

            users: list[ParticipantDAO] = await gateway.channel_users(channel_id=telegram.id)

            assert {user.id for user in users} == {alice.id, bob.id}
        finally:
            await gateway.close()

    async def test_channel_heartbeat_moves_last_seen_forward(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            channel: ChannelDAO = await gateway.register_channel(kind="telegram", name="telegram")
            await asyncio.sleep(0.01)

            await gateway.heartbeat_channel(channel_id=channel.id)

            stored: ChannelDAO | None = await gateway.get_channel(channel_id=channel.id)
            assert stored is not None
            assert stored.last_seen_at > channel.last_seen_at
        finally:
            await gateway.close()

    def test_stable_channel_id_is_deterministic_per_kind_and_name(self) -> None:
        first: UUID = ChannelGateway.stable_channel_id(kind="telegram", name="telegram")
        again: UUID = ChannelGateway.stable_channel_id(kind="telegram", name="telegram")
        other_name: UUID = ChannelGateway.stable_channel_id(kind="telegram", name="work-telegram")
        other_kind: UUID = ChannelGateway.stable_channel_id(kind="cli", name="telegram")

        assert first == again
        assert len({first, other_name, other_kind}) == 3
