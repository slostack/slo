"""AdapterHost journeys (108.5 §5 host, §6 edge cases, X4).

Level: the real ``AdapterHost`` over a real ``ChannelGateway`` and SQLite WAL
file under ``tmp_path``. The only stand-in is the platform adapter itself,
``ScriptedAdapter``: a protocol implementation injected through the host's
constructor whose ``deliver`` results the test scripts. Agents are real
participants; replies are written by the real ``ReplyWriter``.
"""

from __future__ import annotations

import asyncio
import os
import signal
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.dao import (
    ChannelDAO,
    ChannelKind,
    ChannelMessageDAO,
    InboundTextDAO,
    ParticipantDAO,
)
from src.channels.errors import AdapterConfigError
from src.channels.gateway import ChannelGateway
from src.channels.host import AGENT_FINISHED_TEXT, NOT_ATTACHED_TEXT, AdapterHost, DeliveryBackoff
from src.channels.protocol import AdapterContext, ChannelAdapter
from src.channels.repository import ChannelRepository


class ScriptedAdapter:
    """Platform stand-in: records deliveries and returns scripted results.

    ``deliver_results`` is consumed one entry per delivery attempt; an entry
    that is an exception is raised instead. When the script is empty every
    delivery succeeds.
    """

    def __init__(
        self,
        *,
        kind: ChannelKind = "http",
        name: str = "scripted",
        deliver_results: Optional[list[bool | Exception]] = None,
        start_error: Optional[Exception] = None,
    ) -> None:
        self._kind: ChannelKind = kind
        self._name: str = name
        self.deliver_results: list[bool | Exception] = list(deliver_results or [])
        self.start_error: Optional[Exception] = start_error
        self.ctx: Optional[AdapterContext] = None
        self.started: asyncio.Event = asyncio.Event()
        self.attempts: list[tuple[float, ChannelMessageDAO, ParticipantDAO]] = []
        self.delivered: list[ChannelMessageDAO] = []
        self.stopped: bool = False

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def name(self) -> str:
        return self._name

    async def start(self, *, ctx: AdapterContext) -> None:
        if self.start_error is not None:
            raise self.start_error
        self.ctx = ctx
        self.started.set()

    async def deliver(self, *, message: ChannelMessageDAO, user: ParticipantDAO) -> bool:
        self.attempts.append((asyncio.get_running_loop().time(), message, user))
        outcome: bool | Exception = self.deliver_results.pop(0) if self.deliver_results else True
        if isinstance(outcome, Exception):
            raise outcome
        if outcome:
            self.delivered.append(message)
        return outcome

    async def stop(self) -> None:
        self.stopped = True


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


async def _eventually(*, predicate: Callable[[], Awaitable[bool]], timeout_s: float = 10.0) -> None:
    async with asyncio.timeout(timeout_s):
        while not await predicate():
            await asyncio.sleep(0.02)


class _RunningHost:
    """Runs one host in a task for the duration of a test."""

    def __init__(self, *, host: AdapterHost, adapter: ScriptedAdapter) -> None:
        self.host: AdapterHost = host
        self.adapter: ScriptedAdapter = adapter
        self.task: Optional[asyncio.Task[int]] = None

    async def __aenter__(self) -> "_RunningHost":
        self.task = asyncio.create_task(self.host.run())
        async with asyncio.timeout(10.0):
            await self.adapter.started.wait()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.host.request_stop()
        assert self.task is not None
        assert await asyncio.wait_for(self.task, timeout=10.0) == 0

    @property
    def ctx(self) -> AdapterContext:
        assert self.adapter.ctx is not None
        return self.adapter.ctx


def _host(*, adapter: ScriptedAdapter, gateway: ChannelGateway, **options: float) -> AdapterHost:
    return AdapterHost(adapter=adapter, gateway=gateway, poll_interval=0.05, **options)  # type: ignore[arg-type]


def _text(text: str, *, user_ref: str = "42", force: bool = False) -> InboundTextDAO:
    return InboundTextDAO(
        external_user_ref=user_ref, display_name=f"user{user_ref} (scripted)", text=text, force=force
    )


async def _reply(*, gateway: ChannelGateway, request: ChannelMessageDAO, text: str) -> None:
    """Answer one request the way an agent's poller does (real ReplyWriter)."""
    await gateway.accept(message_id=request.id)
    await ReplyWriter(gateway=gateway).write(
        request=request, outcome=TurnOutcomeDAO(status="completed", final_text=text)
    )


class TestInboundCommands:
    async def test_attach_then_send_creates_a_row_for_the_attached_agent(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo refactor")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                before: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("status?"))
                attached: ChannelMessageDAO | str = await running.ctx.inbound(
                    item=_text(f"/attach {str(agent.id)[:6]}")
                )
                sent: ChannelMessageDAO | str = await running.ctx.inbound(
                    item=_text("status of the refactor?")
                )
                forced: ChannelMessageDAO | str = await running.ctx.inbound(
                    item=_text("/force stop and summarise")
                )
                flagged: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("use -x", force=True))

            assert before == NOT_ATTACHED_TEXT
            assert isinstance(attached, str) and "slo refactor" in attached
            assert isinstance(sent, ChannelMessageDAO)
            assert sent.recipient_id == agent.id
            assert sent.message_contents == "status of the refactor?"
            assert sent.forced_at is None
            assert sent.channel_id == running.ctx.channel.id
            sender: Optional[ParticipantDAO] = await gateway.get_participant(participant_id=sent.sender_id)
            assert sender is not None
            assert (sender.kind, sender.external_ref, sender.name) == ("user", "42", "user42 (scripted)")
            assert isinstance(forced, ChannelMessageDAO)
            assert forced.message_contents == "stop and summarise"
            assert forced.forced_at is not None
            assert isinstance(flagged, ChannelMessageDAO) and flagged.forced_at is not None
            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            assert len(pending) == 3
        finally:
            await gateway.close()

    async def test_agents_lists_open_agents_and_detach_stops_sending(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            live: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo live")
            done: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo done")
            await gateway.close_agent(session_id=done.id, reason="session_closed")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                listing: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("/agents"))
                await running.ctx.inbound(item=_text(f"/attach {live.id}"))
                detached: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("/detach"))
                after: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("still there?"))

            assert isinstance(listing, str)
            assert str(live.id)[:8] in listing and "slo live" in listing
            assert "slo done" not in listing
            assert isinstance(detached, str) and "Detached" in detached
            assert after == NOT_ATTACHED_TEXT
            assert await gateway.pending_inbound(recipient_id=live.id) == []
        finally:
            await gateway.close()

    async def test_attach_failures_explain_themselves(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            await gateway.register_agent(
                session_id=UUID("aaaa1111-0000-4000-8000-000000000001"), name="slo a"
            )
            await gateway.register_agent(
                session_id=UUID("aaaa2222-0000-4000-8000-000000000002"), name="slo b"
            )
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                unknown: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("/attach ffff"))
                ambiguous: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("/attach aaaa"))
                bare: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("/attach"))
                empty_force: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("/force"))
                unknown_command: ChannelMessageDAO | str = await running.ctx.inbound(
                    item=_text("/bogus thing")
                )

            assert isinstance(unknown, str) and "No agent matches" in unknown
            assert isinstance(ambiguous, str) and "2 agents match" in ambiguous
            assert isinstance(bare, str) and "Usage: /attach" in bare
            assert isinstance(empty_force, str) and "Usage: /force" in empty_force
            assert isinstance(unknown_command, str) and "/attach" in unknown_command
        finally:
            await gateway.close()

    async def test_path_like_text_is_a_prompt_and_bot_suffix_is_a_command(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                attached = await running.ctx.inbound(item=_text(f"/attach@slo_bot {agent.id}"))
                path_text = await running.ctx.inbound(item=_text("/tmp/x is broken"))

            assert isinstance(attached, str) and attached.startswith("Attached to")
            assert isinstance(path_text, ChannelMessageDAO)
            assert path_text.message_contents == "/tmp/x is broken"
        finally:
            await gateway.close()

    async def test_attached_agent_closed_clears_the_attachment(self, tmp_path: Path) -> None:
        """108.5 §6: 'agent finished — /agents to pick another' and the attachment is cleared."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo short-lived")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                await running.ctx.inbound(item=_text(f"/attach {agent.id}"))
                await gateway.close_agent(session_id=agent.id, reason="session_closed")

                finished: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("are you there?"))
                afterwards: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("hello?"))

            assert finished == AGENT_FINISHED_TEXT
            assert afterwards == NOT_ATTACHED_TEXT
            assert await gateway.pending_inbound(recipient_id=agent.id) == []
        finally:
            await gateway.close()

    async def test_attaching_to_a_closed_agent_is_refused(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo gone")
            await gateway.close_agent(session_id=agent.id, reason="session_closed")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                refused: ChannelMessageDAO | str = await running.ctx.inbound(
                    item=_text(f"/attach {agent.id}")
                )
                after: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("hi"))

            assert refused == AGENT_FINISHED_TEXT
            assert after == NOT_ATTACHED_TEXT
        finally:
            await gateway.close()

    async def test_a_redelivered_platform_message_creates_one_row(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                await running.ctx.inbound(item=_text(f"/attach {agent.id}"))
                item: InboundTextDAO = InboundTextDAO(
                    external_user_ref="42", display_name="u", text="once", external_message_ref="update-7"
                )
                first: ChannelMessageDAO | str = await running.ctx.inbound(item=item)
                again: ChannelMessageDAO | str = await running.ctx.inbound(item=item)

            assert isinstance(first, ChannelMessageDAO) and isinstance(again, ChannelMessageDAO)
            assert first.id == again.id
            assert len(await gateway.pending_inbound(recipient_id=agent.id)) == 1
        finally:
            await gateway.close()

    async def test_an_oversized_message_is_refused_without_a_row(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                await running.ctx.inbound(item=_text(f"/attach {agent.id}"))
                refused: ChannelMessageDAO | str = await running.ctx.inbound(item=_text("x" * 70_000))

            assert isinstance(refused, str) and "too long" in refused
            assert await gateway.pending_inbound(recipient_id=agent.id) == []
        finally:
            await gateway.close()


class TestOutboundDelivery:
    async def test_reply_is_delivered_to_the_user_and_accepted(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningHost(host=_host(adapter=adapter, gateway=gateway), adapter=adapter) as running:
                await running.ctx.inbound(item=_text(f"/attach {agent.id}"))
                request = await running.ctx.inbound(item=_text("status?"))
                assert isinstance(request, ChannelMessageDAO)
                await _reply(gateway=gateway, request=request, text="all green")

                async def _accepted() -> bool:
                    reply: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                    return reply is not None and reply.accepted_at is not None

                await _eventually(predicate=_accepted)

            assert [row.message_contents for row in adapter.delivered] == ["all green"]
            _at, _message, user = adapter.attempts[0]
            assert user.id == request.sender_id and user.external_ref == "42"
        finally:
            await gateway.close()

    async def test_x4_failed_delivery_stays_pending_then_delivers_after_recovery(
        self, tmp_path: Path
    ) -> None:
        """X4: deliver failure → row stays pending (with backoff) → delivered once the platform recovers."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter(
            deliver_results=[False, RuntimeError("platform down"), True]
        )
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            host: AdapterHost = _host(
                adapter=adapter, gateway=gateway, initial_backoff_s=0.3, max_backoff_s=0.6
            )
            async with _RunningHost(host=host, adapter=adapter) as running:
                await running.ctx.inbound(item=_text(f"/attach {agent.id}"))
                request = await running.ctx.inbound(item=_text("status?"))
                assert isinstance(request, ChannelMessageDAO)
                await _reply(gateway=gateway, request=request, text="eventually")

                await _eventually(predicate=_async_true(lambda: len(adapter.attempts) >= 2))
                still_pending: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                assert still_pending is not None and still_pending.accepted_at is None

                async def _accepted() -> bool:
                    reply: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                    return reply is not None and reply.accepted_at is not None

                await _eventually(predicate=_accepted)

            times: list[float] = [at for at, _message, _user in adapter.attempts]
            assert len(times) == 3
            assert times[1] - times[0] >= 0.28  # first backoff: initial
            assert times[2] - times[1] >= 0.55  # second backoff: doubled (capped at max)
            assert [row.message_contents for row in adapter.delivered] == ["eventually"]
        finally:
            await gateway.close()

    async def test_one_users_failure_keeps_their_order_and_spares_other_users(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter(deliver_results=[False])
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            host: AdapterHost = _host(
                adapter=adapter, gateway=gateway, initial_backoff_s=0.4, max_backoff_s=0.4
            )
            async with _RunningHost(host=host, adapter=adapter) as running:
                await running.ctx.inbound(item=_text(f"/attach {agent.id}", user_ref="1"))
                await running.ctx.inbound(item=_text(f"/attach {agent.id}", user_ref="2"))
                first = await running.ctx.inbound(item=_text("one", user_ref="1"))
                second = await running.ctx.inbound(item=_text("two", user_ref="1"))
                other = await running.ctx.inbound(item=_text("three", user_ref="2"))
                assert isinstance(first, ChannelMessageDAO)
                assert isinstance(second, ChannelMessageDAO)
                assert isinstance(other, ChannelMessageDAO)
                for request, answer in ((first, "r1"), (second, "r2"), (other, "r3")):
                    await _reply(gateway=gateway, request=request, text=answer)

                await _eventually(predicate=_async_true(lambda: len(adapter.delivered) == 3))

            delivered_texts: list[str] = [row.message_contents for row in adapter.delivered]
            assert delivered_texts.index("r1") < delivered_texts.index("r2")
            assert delivered_texts[0] == "r3"  # user 2 was not held back by user 1's backoff
        finally:
            await gateway.close()

    async def test_rows_written_while_offline_are_delivered_on_the_next_run(self, tmp_path: Path) -> None:
        """108.5 §6: adapter offline when the reply is written → delivered when it runs again."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            first_adapter: ScriptedAdapter = ScriptedAdapter(name="restartable")
            async with _RunningHost(
                host=_host(adapter=first_adapter, gateway=gateway), adapter=first_adapter
            ) as running:
                await running.ctx.inbound(item=_text(f"/attach {agent.id}"))
                request = await running.ctx.inbound(item=_text("long job"))
                assert isinstance(request, ChannelMessageDAO)
            assert first_adapter.stopped
            await _reply(gateway=gateway, request=request, text="done while you were away")

            second_adapter: ScriptedAdapter = ScriptedAdapter(name="restartable")
            async with _RunningHost(
                host=_host(adapter=second_adapter, gateway=gateway), adapter=second_adapter
            ):

                async def _accepted() -> bool:
                    reply: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                    return reply is not None and reply.accepted_at is not None

                await _eventually(predicate=_accepted)
                still_attached = await second_adapter.ctx.inbound(item=_text("and now?"))  # type: ignore[union-attr]

            assert [row.message_contents for row in second_adapter.delivered] == ["done while you were away"]
            assert isinstance(still_attached, ChannelMessageDAO)  # the attachment survived the restart
        finally:
            await gateway.close()

    async def test_two_adapters_of_one_kind_have_separate_channels_and_users(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            home: ScriptedAdapter = ScriptedAdapter(kind="telegram", name="telegram")
            work: ScriptedAdapter = ScriptedAdapter(kind="telegram", name="work-telegram")
            async with _RunningHost(host=_host(adapter=home, gateway=gateway), adapter=home) as home_running:
                async with _RunningHost(
                    host=_host(adapter=work, gateway=gateway), adapter=work
                ) as work_running:
                    await home_running.ctx.inbound(item=_text("/agents"))
                    await work_running.ctx.inbound(item=_text("/agents"))
                    home_channel: ChannelDAO = home_running.ctx.channel
                    work_channel: ChannelDAO = work_running.ctx.channel

            assert home_channel.id != work_channel.id
            assert home_channel.kind == work_channel.kind == "telegram"
            home_users: list[ParticipantDAO] = await gateway.channel_users(channel_id=home_channel.id)
            work_users: list[ParticipantDAO] = await gateway.channel_users(channel_id=work_channel.id)
            assert len(home_users) == len(work_users) == 1
            assert home_users[0].id != work_users[0].id
        finally:
            await gateway.close()


class TestHostLifecycle:
    async def test_heartbeat_refreshes_the_channel_while_running(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        try:
            host: AdapterHost = _host(adapter=adapter, gateway=gateway, heartbeat_interval_s=0.1)
            async with _RunningHost(host=host, adapter=adapter) as running:
                registered: ChannelDAO = running.ctx.channel

                async def _seen_later() -> bool:
                    stored: Optional[ChannelDAO] = await gateway.get_channel(channel_id=registered.id)
                    return stored is not None and stored.last_seen_at > registered.last_seen_at

                await _eventually(predicate=_seen_later, timeout_s=5.0)
            assert adapter.stopped
        finally:
            await gateway.close()

    async def test_adapter_config_error_at_start_exits_1_and_still_stops_the_adapter(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter(start_error=AdapterConfigError("missing bot token"))
        try:
            exit_code: int = await asyncio.wait_for(
                _host(adapter=adapter, gateway=gateway).run(), timeout=10.0
            )

            assert exit_code == 1
            assert adapter.stopped
            assert "missing bot token" in capsys.readouterr().err
        finally:
            await gateway.close()

    async def test_unexpected_start_failure_exits_1(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter(start_error=RuntimeError("boom"))
        try:
            assert await asyncio.wait_for(_host(adapter=adapter, gateway=gateway).run(), timeout=10.0) == 1
            assert adapter.stopped
        finally:
            await gateway.close()

    async def test_unknown_channel_kind_is_a_config_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter(kind="carrier-pigeon")  # type: ignore[arg-type]
        try:
            assert await asyncio.wait_for(_host(adapter=adapter, gateway=gateway).run(), timeout=10.0) == 1
            assert adapter.ctx is None
            assert "carrier-pigeon" in capsys.readouterr().err
        finally:
            await gateway.close()

    @pytest.mark.skipif(
        threading.current_thread() is not threading.main_thread(), reason="signals need the main thread"
    )
    async def test_sigterm_stops_the_host_cleanly(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        adapter: ScriptedAdapter = ScriptedAdapter()
        previous: object = signal.getsignal(signal.SIGTERM)
        try:
            task: asyncio.Task[int] = asyncio.create_task(_host(adapter=adapter, gateway=gateway).run())
            async with asyncio.timeout(10.0):
                await adapter.started.wait()
            # Guard: only signal once the host's handler replaced the default
            # disposition, so a failure can never terminate the test process.
            assert signal.getsignal(signal.SIGTERM) is not signal.SIG_DFL
            os.kill(os.getpid(), signal.SIGTERM)

            assert await asyncio.wait_for(task, timeout=10.0) == 0
            assert adapter.stopped
            assert signal.getsignal(signal.SIGTERM) == previous  # handler removed on exit
        finally:
            await gateway.close()


class TestDeliveryBackoff:
    def test_delay_doubles_from_one_second_and_caps_at_sixty(self) -> None:
        backoff: DeliveryBackoff = DeliveryBackoff(initial_s=1.0, max_s=60.0)
        delays: list[float] = [backoff.delay_after(failures=count) for count in range(1, 9)]

        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0]

    def test_success_resets_and_keys_are_independent(self) -> None:
        backoff: DeliveryBackoff = DeliveryBackoff(initial_s=1.0, max_s=60.0)
        alice: UUID = uuid4()
        bob: UUID = uuid4()

        assert backoff.record_failure(key=alice, now=100.0) == 1.0
        assert backoff.record_failure(key=alice, now=101.0) == 2.0
        assert not backoff.is_ready(key=alice, now=102.5)
        assert backoff.is_ready(key=alice, now=103.0)
        assert backoff.is_ready(key=bob, now=100.0)
        backoff.record_success(key=alice)
        assert backoff.record_failure(key=alice, now=200.0) == 1.0


class TestProtocolConformance:
    def test_scripted_adapter_satisfies_the_runtime_protocol(self) -> None:
        assert isinstance(ScriptedAdapter(), ChannelAdapter)


def _async_true(check: Callable[[], bool]) -> Callable[[], Awaitable[bool]]:
    async def _probe() -> bool:
        return check()

    return _probe
