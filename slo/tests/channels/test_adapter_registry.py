"""Adapter registry and the custom-adapter round trip (108.5 §3 Registry, X5).

Level: ``AdapterRegistry`` loads a real ``module:Class`` reference; the X5
journey runs the loaded adapter in the real ``AdapterHost`` over a real SQLite
queue. The agent side answers with the real ``ReplyWriter``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

import pytest

from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.adapters.registry import AdapterRegistry
from src.channels.dao import ChannelMessageDAO, ParticipantDAO
from src.channels.errors import AdapterConfigError
from src.channels.gateway import ChannelGateway
from src.channels.host import AdapterHost
from src.channels.protocol import ChannelAdapter
from src.channels.repository import ChannelRepository
from tests.fixtures import EchoAdapter


class NotAnAdapter:
    """Importable class missing the adapter methods."""


class SyncAdapter:
    """Importable class whose methods are not coroutines."""

    kind: str = "http"
    name: str = "sync"

    def start(self, *, ctx: object) -> None:
        return None

    def deliver(self, *, message: object, user: object) -> bool:
        return True

    def stop(self) -> None:
        return None


class ExplodingAdapter:
    """Importable class whose constructor fails."""

    def __init__(self) -> None:
        raise RuntimeError("cannot build")


NOT_A_CLASS: int = 3


class TestLoadByReference:
    def test_loads_and_builds_a_protocol_adapter(self) -> None:
        adapter: ChannelAdapter = AdapterRegistry.load(reference="tests.fixtures:EchoAdapter")

        assert isinstance(adapter, EchoAdapter)
        assert isinstance(adapter, ChannelAdapter)
        assert (adapter.kind, adapter.name) == ("http", "echo")

    @pytest.mark.parametrize(
        ("reference", "fragment"),
        [
            ("tests.fixtures.EchoAdapter", "module:Class"),
            (":EchoAdapter", "module:Class"),
            ("tests.fixtures:", "module:Class"),
            ("no_such_module_for_slo:Thing", "cannot import"),
            ("tests.fixtures:Missing", "has no attribute"),
            ("tests.channels.test_adapter_registry:NOT_A_CLASS", "not a class"),
            ("tests.channels.test_adapter_registry:ExplodingAdapter", "could not be built"),
            ("tests.channels.test_adapter_registry:NotAnAdapter", "ChannelAdapter protocol"),
            ("tests.channels.test_adapter_registry:SyncAdapter", "async"),
        ],
    )
    def test_bad_references_are_config_errors(self, reference: str, fragment: str) -> None:
        with pytest.raises(AdapterConfigError) as raised:
            AdapterRegistry.load(reference=reference)

        assert fragment in str(raised.value)


class TestChoosingAnAdapter:
    def test_unknown_builtin_lists_the_known_ones(self) -> None:
        with pytest.raises(AdapterConfigError) as raised:
            AdapterRegistry.load(builtin="carrier-pigeon")

        assert "telegram" in str(raised.value)

    @pytest.mark.parametrize(
        ("builtin", "reference"),
        [(None, None), ("telegram", "tests.fixtures:EchoAdapter")],
    )
    def test_exactly_one_of_builtin_or_reference(
        self, builtin: Optional[str], reference: Optional[str]
    ) -> None:
        with pytest.raises(AdapterConfigError):
            AdapterRegistry.load(builtin=builtin, reference=reference)

    def test_config_path_is_only_for_builtins(self, tmp_path: Path) -> None:
        with pytest.raises(AdapterConfigError):
            AdapterRegistry.load(reference="tests.fixtures:EchoAdapter", config_path=tmp_path / "x.json")

    def test_builtin_names(self) -> None:
        assert AdapterRegistry.builtin_names() == ("telegram",)


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


def _outbox_records(*, path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TestX5CustomAdapterRoundTrip:
    async def test_x5_loaded_echo_adapter_round_trips_a_message(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """X5: ``tests.fixtures:EchoAdapter`` → attach → prompt row → agent reply → delivered + accepted."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        outbox: Path = tmp_path / "outbox.jsonl"
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo echo target")
            monkeypatch.setenv(
                "SLO_ECHO_ADAPTER_SCRIPT",
                json.dumps({"user_ref": "u-1", "texts": [f"/attach {str(agent.id)[:8]}", "ping"]}),
            )
            monkeypatch.setenv("SLO_ECHO_ADAPTER_OUTBOX", str(outbox))
            adapter: ChannelAdapter = AdapterRegistry.load(reference="tests.fixtures:EchoAdapter")
            host: AdapterHost = AdapterHost(adapter=adapter, gateway=gateway, poll_interval=0.05)
            running: asyncio.Task[int] = asyncio.create_task(host.run())

            async with asyncio.timeout(10.0):
                while not (pending := await gateway.list_pending_inbound_messages(recipient_id=agent.id)):
                    await asyncio.sleep(0.02)
            request: ChannelMessageDAO = pending[0]
            assert request.message_contents == "ping"
            await gateway.accept(message_id=request.id)
            await ReplyWriter(gateway=gateway).write(
                request=request, outcome=TurnOutcomeDAO(status="completed", final_text="pong")
            )
            async with asyncio.timeout(10.0):
                while not any(record["kind"] == "delivered" for record in _outbox_records(path=outbox)):
                    await asyncio.sleep(0.02)
            host.request_stop()
            assert await asyncio.wait_for(running, timeout=10.0) == 0

            records: list[dict[str, object]] = _outbox_records(path=outbox)
            answers: list[dict[str, object]] = [record for record in records if record["kind"] == "answer"]
            assert "Attached to slo echo target" in str(answers[0]["answer"])
            assert answers[1]["message_id"] == str(request.id)
            delivered: list[dict[str, object]] = [
                record for record in records if record["kind"] == "delivered"
            ]
            assert delivered == [
                {
                    "kind": "delivered",
                    "text": "pong",
                    "message_type": "reply",
                    "in_reply_to_id": str(request.id),
                    "user_ref": "u-1",
                }
            ]
            reply: Optional[ChannelMessageDAO] = await gateway.find_reply(message_id=request.id)
            assert reply is not None and reply.accepted_at is not None
            assert request.channel_id == ChannelGateway.stable_channel_id(kind="http", name="echo")
        finally:
            await gateway.close()
