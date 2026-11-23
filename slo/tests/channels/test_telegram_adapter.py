"""Telegram reference adapter (108.5 §4–§6; X2, X3, X4).

Level: the real ``TelegramAdapter`` + ``TelegramBotAPIClient`` run inside the
real ``AdapterHost`` over a real SQLite queue under ``tmp_path``. The only
double is the third-party Bot API itself: ``FakeBotAPI`` answers HTTP through
``httpx.MockTransport`` at the client's transport boundary. The token is a
made-up test value; nothing reaches Telegram.

Not proven here: the real Telegram service (live credentials are not used).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from uuid import uuid4

import httpx
import pytest

from src.agents.slo_agent.channel_delivery.reply_writer import ReplyWriter
from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.adapters.registry import AdapterRegistry
from src.channels.adapters.telegram.adapter import TelegramAdapter
from src.channels.adapters.telegram.api import TelegramAPIError, TelegramBotAPIClient, TelegramUpdateDAO
from src.channels.adapters.telegram.config import TelegramConfigDAO
from src.channels.dao import ChannelMessageDAO, ParticipantDAO
from src.channels.errors import AdapterConfigError
from src.channels.gateway import ChannelGateway
from src.channels.host import AdapterHost
from src.channels.repository import ChannelRepository

_TOKEN: str = "123456:FAKE-test_token-not-real"
_ALLOWED_USER: int = 1001
_STRANGER: int = 6666


class FakeBotAPI:
    """Third-party boundary double for the Telegram Bot API (getUpdates + sendMessage)."""

    def __init__(self) -> None:
        self._updates: list[dict[str, object]] = []
        self._next_update_id: int = 500
        self.sent: list[dict[str, object]] = []
        self.send_times: list[float] = []
        self.offsets: list[Optional[int]] = []
        self.send_failures: list[httpx.Response] = []
        self.update_failures: list[httpx.Response | Exception] = []
        self.fail_text_once: set[str] = set()
        self.failed_texts: list[str] = []
        self.paths: list[str] = []

    def push_text(
        self, *, user_id: int, text: str, chat_type: str = "private", update_id: Optional[int] = None
    ) -> int:
        """Queue one incoming text message; return its update id."""
        if update_id is None:
            update_id = self._next_update_id
            self._next_update_id += 1
        self._updates.append(
            {
                "update_id": update_id,
                "message": {
                    "message_id": update_id * 10,
                    "date": 0,
                    "chat": {"id": user_id if chat_type == "private" else -42, "type": chat_type},
                    "from": {"id": user_id, "is_bot": False, "first_name": f"user{user_id}"},
                    "text": text,
                },
            }
        )
        return update_id

    def texts_sent_to(self, *, chat_id: int) -> list[str]:
        return [str(body["text"]) for body in self.sent if body["chat_id"] == chat_id]

    async def handle(self, request: httpx.Request) -> httpx.Response:
        self.paths.append(request.url.path)
        prefix: str = f"/bot{_TOKEN}/"
        assert request.url.path.startswith(prefix)
        method: str = request.url.path.removeprefix(prefix)
        body: dict[str, object] = json.loads(request.content or b"{}")
        if method == "getUpdates":
            return await self._get_updates(body=body)
        if method == "sendMessage":
            if self.send_failures:
                return self.send_failures.pop(0)
            if body.get("text") in self.fail_text_once:
                self.fail_text_once.discard(str(body["text"]))
                self.failed_texts.append(str(body["text"]))
                return httpx.Response(502, json={"ok": False, "error_code": 502, "description": "Bad"})
            self.sent.append(body)
            self.send_times.append(asyncio.get_running_loop().time())
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.sent)}})
        return httpx.Response(404, json={"ok": False, "error_code": 404, "description": "Not Found"})

    async def _get_updates(self, *, body: dict[str, object]) -> httpx.Response:
        offset_value: object | None = body.get("offset")
        if offset_value is not None and not isinstance(offset_value, int):
            raise AssertionError(f"Telegram update offset must be an integer, got {offset_value!r}.")
        offset: Optional[int] = offset_value
        self.offsets.append(offset)
        if self.update_failures:
            failure: httpx.Response | Exception = self.update_failures.pop(0)
            if isinstance(failure, Exception):
                raise failure
            return failure
        pending: list[dict[str, object]] = [
            update for update in self._updates if offset is None or self._update_id(update=update) >= offset
        ]
        if not pending:
            await asyncio.sleep(0.05)  # a short long-poll
        return httpx.Response(200, json={"ok": True, "result": pending})

    @staticmethod
    def _update_id(*, update: dict[str, object]) -> int:
        """Return the integer update id from a scripted Telegram update."""
        update_id: object = update["update_id"]
        if not isinstance(update_id, int):
            raise AssertionError(f"Telegram update id must be an integer, got {update_id!r}.")
        return update_id


def _client(*, fake: FakeBotAPI) -> TelegramBotAPIClient:
    return TelegramBotAPIClient(token=_TOKEN, transport=httpx.MockTransport(fake.handle))


def _config(**overrides: object) -> TelegramConfigDAO:
    values: dict[str, object] = {"allowed_user_ids": [_ALLOWED_USER], "poll_timeout_s": 1}
    values.update(overrides)
    return TelegramConfigDAO.model_validate(values)


async def _open_gateway(*, tmp_path: Path) -> ChannelGateway:
    repository: ChannelRepository = ChannelRepository(db_path=tmp_path / "channels.db")
    await repository.open()
    return ChannelGateway(repository=repository)


async def _eventually(*, predicate: Callable[[], Awaitable[bool] | bool], timeout_s: float = 10.0) -> None:
    async with asyncio.timeout(timeout_s):
        while True:
            outcome: Awaitable[bool] | bool = predicate()
            if await outcome if not isinstance(outcome, bool) else outcome:
                return
            await asyncio.sleep(0.02)


class _RunningTelegram:
    """Runs one TelegramAdapter inside a real AdapterHost for one test."""

    def __init__(self, *, gateway: ChannelGateway, fake: FakeBotAPI, **host_options: float) -> None:
        self.adapter: TelegramAdapter = TelegramAdapter(config=_config(), client=_client(fake=fake))
        self.host: AdapterHost = AdapterHost(
            adapter=self.adapter, gateway=gateway, poll_interval=0.05, **host_options  # type: ignore[arg-type]
        )
        self.task: Optional[asyncio.Task[int]] = None

    async def __aenter__(self) -> "_RunningTelegram":
        self.task = asyncio.create_task(self.host.run())
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        self.host.request_stop()
        assert self.task is not None
        assert await asyncio.wait_for(self.task, timeout=10.0) == 0


async def _reply(*, gateway: ChannelGateway, request: ChannelMessageDAO, text: str) -> None:
    await gateway.accept(message_id=request.id)
    await ReplyWriter(gateway=gateway).write(
        request=request, outcome=TurnOutcomeDAO(status="completed", final_text=text)
    )


async def _first_pending(*, gateway: ChannelGateway, agent: ParticipantDAO) -> ChannelMessageDAO:
    async with asyncio.timeout(10.0):
        while not (pending := await gateway.pending_inbound(recipient_id=agent.id)):
            await asyncio.sleep(0.02)
    return pending[0]


class TestX2TelegramJourney:
    async def test_x2_attach_send_reply_delivered_and_accepted(self, tmp_path: Path) -> None:
        """X2: /attach → prompt row → agent reply → sendMessage to the chat → reply row accepted."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo refactor")
            async with _RunningTelegram(gateway=gateway, fake=fake):
                fake.push_text(user_id=_ALLOWED_USER, text=f"/attach {str(agent.id)[:4]}")
                await _eventually(predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)))
                fake.push_text(user_id=_ALLOWED_USER, text="status of the refactor?")
                request: ChannelMessageDAO = await _first_pending(gateway=gateway, agent=agent)
                await _reply(gateway=gateway, request=request, text="Today: 3 commits on worktree/channels")

                async def _accepted() -> bool:
                    reply: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                    return reply is not None and reply.accepted_at is not None

                await _eventually(predicate=_accepted)

            sent: list[str] = fake.texts_sent_to(chat_id=_ALLOWED_USER)
            assert "Attached to slo refactor" in sent[0]
            assert sent[1:] == ["Today: 3 commits on worktree/channels"]
            assert request.message_contents == "status of the refactor?"
            sender: Optional[ParticipantDAO] = await gateway.get_participant(participant_id=request.sender_id)
            assert sender is not None
            assert (sender.external_ref, sender.name) == (
                str(_ALLOWED_USER),
                f"user{_ALLOWED_USER} (telegram)",
            )
            assert request.channel_id == ChannelGateway.stable_channel_id(kind="telegram", name="telegram")
            # Every update was confirmed: a later getUpdates carried offset = last id + 1.
            assert 502 in fake.offsets
        finally:
            await gateway.close()

    async def test_a_redelivered_update_creates_one_row(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningTelegram(gateway=gateway, fake=fake) as running:
                fake.push_text(user_id=_ALLOWED_USER, text=f"/attach {agent.id}")
                await _eventually(predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)))
                fake.push_text(user_id=_ALLOWED_USER, text="only once", update_id=900)
                await _first_pending(gateway=gateway, agent=agent)
            # A restarted adapter (no stored offset) is handed the same update again.
            fake.push_text(user_id=_ALLOWED_USER, text="only once", update_id=900)
            async with _RunningTelegram(gateway=gateway, fake=fake):
                await _eventually(predicate=lambda: fake.offsets.count(None) >= 2 and len(fake.offsets) > 4)
                await asyncio.sleep(0.2)

            pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=agent.id)
            assert [row.message_contents for row in pending] == ["only once"]
            assert running.adapter.kind == "telegram"
        finally:
            await gateway.close()


class TestX3AllowList:
    async def test_x3_user_not_on_the_allow_list_is_ignored(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """X3: dropped and logged; nothing is sent back and nothing is queued."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningTelegram(gateway=gateway, fake=fake):
                fake.push_text(user_id=_STRANGER, text=f"/attach {agent.id}")
                fake.push_text(user_id=_STRANGER, text="give me your secrets")
                fake.push_text(user_id=_ALLOWED_USER, text="/agents")
                await _eventually(predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)))

            assert fake.texts_sent_to(chat_id=_STRANGER) == []
            assert await gateway.pending_inbound(recipient_id=agent.id) == []
            channel_id = ChannelGateway.stable_channel_id(kind="telegram", name="telegram")
            users: list[ParticipantDAO] = await gateway.channel_users(channel_id=channel_id)
            assert [user.external_ref for user in users] == [str(_ALLOWED_USER)]
            err: str = capsys.readouterr().err
            assert "not on the allow-list" in err and f"user_id={_STRANGER}" in err
            assert "give me your secrets" not in err
        finally:
            await gateway.close()

    async def test_group_chat_messages_are_ignored_even_from_allowed_users(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        try:
            async with _RunningTelegram(gateway=gateway, fake=fake):
                fake.push_text(user_id=_ALLOWED_USER, text="/agents", chat_type="group")
                fake.push_text(user_id=_ALLOWED_USER, text="/help")
                await _eventually(predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)))

            assert fake.texts_sent_to(chat_id=-42) == []
            assert len(fake.texts_sent_to(chat_id=_ALLOWED_USER)) == 1
        finally:
            await gateway.close()


class TestDeliveryFailures:
    async def test_x4_send_failure_keeps_the_row_pending_then_delivers(self, tmp_path: Path) -> None:
        """X4 (Telegram): sendMessage 500 → row stays pending → delivered after the API recovers."""
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningTelegram(gateway=gateway, fake=fake, initial_backoff_s=0.3, max_backoff_s=0.3):
                fake.push_text(user_id=_ALLOWED_USER, text=f"/attach {agent.id}")
                await _eventually(predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)))
                fake.push_text(user_id=_ALLOWED_USER, text="status?")
                request: ChannelMessageDAO = await _first_pending(gateway=gateway, agent=agent)
                fake.send_failures.append(
                    httpx.Response(500, json={"ok": False, "error_code": 500, "description": "Internal"})
                )
                await _reply(gateway=gateway, request=request, text="recovered")
                await _eventually(predicate=lambda: not fake.send_failures)
                pending_reply: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                assert pending_reply is not None and pending_reply.accepted_at is None

                async def _accepted() -> bool:
                    reply: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                    return reply is not None and reply.accepted_at is not None

                await _eventually(predicate=_accepted)

            assert fake.texts_sent_to(chat_id=_ALLOWED_USER)[1:] == ["recovered"]
        finally:
            await gateway.close()

    async def test_429_retry_after_is_honoured_before_the_next_send(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            async with _RunningTelegram(
                gateway=gateway, fake=fake, initial_backoff_s=0.05, max_backoff_s=0.05
            ):
                fake.push_text(user_id=_ALLOWED_USER, text=f"/attach {agent.id}")
                await _eventually(predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)))
                fake.push_text(user_id=_ALLOWED_USER, text="status?")
                request: ChannelMessageDAO = await _first_pending(gateway=gateway, agent=agent)
                fake.send_failures.append(
                    httpx.Response(
                        429,
                        json={
                            "ok": False,
                            "error_code": 429,
                            "description": "Too Many Requests: retry after 1",
                            "parameters": {"retry_after": 1},
                        },
                    )
                )
                await _reply(gateway=gateway, request=request, text="after the limit")
                await _eventually(predicate=lambda: not fake.send_failures)
                limited_at: float = asyncio.get_running_loop().time()
                await _eventually(predicate=lambda: len(fake.texts_sent_to(chat_id=_ALLOWED_USER)) == 2)

            assert fake.send_times[-1] - limited_at >= 0.9
        finally:
            await gateway.close()

    async def test_get_updates_errors_back_off_and_reading_resumes(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        fake.update_failures.extend(
            [
                httpx.Response(502, text="<html>bad gateway</html>"),
                httpx.ConnectError("connection refused"),
            ]
        )
        try:
            async with _RunningTelegram(gateway=gateway, fake=fake):
                fake.push_text(user_id=_ALLOWED_USER, text="/help")
                await _eventually(
                    predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)), timeout_s=15.0
                )

            assert len(fake.offsets) >= 3
        finally:
            await gateway.close()

    async def test_long_replies_are_split_and_a_failed_part_is_not_resent(self, tmp_path: Path) -> None:
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        fake: FakeBotAPI = FakeBotAPI()
        try:
            agent: ParticipantDAO = await gateway.register_agent(session_id=uuid4(), name="slo agent")
            running: _RunningTelegram = _RunningTelegram(
                gateway=gateway, fake=fake, initial_backoff_s=0.05, max_backoff_s=0.05
            )
            running.adapter = TelegramAdapter(config=_config(max_reply_chars=10), client=_client(fake=fake))
            running.host = AdapterHost(
                adapter=running.adapter,
                gateway=gateway,
                poll_interval=0.05,
                initial_backoff_s=0.05,
                max_backoff_s=0.05,
            )
            async with running:
                fake.push_text(user_id=_ALLOWED_USER, text=f"/attach {agent.id}")
                await _eventually(predicate=lambda: bool(fake.texts_sent_to(chat_id=_ALLOWED_USER)))
                fake.push_text(user_id=_ALLOWED_USER, text="long please")
                request: ChannelMessageDAO = await _first_pending(gateway=gateway, agent=agent)
                attach_answers: int = len(fake.texts_sent_to(chat_id=_ALLOWED_USER))
                # Part 1 succeeds, part 2 fails once, then everything succeeds.
                fake.fail_text_once.add("b" * 10)
                await _reply(gateway=gateway, request=request, text="a" * 10 + "b" * 10 + "c" * 5)

                async def _accepted() -> bool:
                    reply: Optional[ChannelMessageDAO] = await gateway.reply_for(message_id=request.id)
                    return reply is not None and reply.accepted_at is not None

                await _eventually(predicate=_accepted)

            parts: list[str] = fake.texts_sent_to(chat_id=_ALLOWED_USER)[attach_answers:]
            assert parts == ["a" * 10, "b" * 10, "c" * 5]
            assert fake.failed_texts == ["b" * 10]
        finally:
            await gateway.close()


class TestBotAPIClient:
    async def test_get_updates_parses_messages_and_send_message_posts_json(self) -> None:
        fake: FakeBotAPI = FakeBotAPI()
        fake.push_text(user_id=_ALLOWED_USER, text="hello")
        client: TelegramBotAPIClient = _client(fake=fake)
        try:
            updates: list[TelegramUpdateDAO] = await client.get_updates(offset=None, timeout_s=1)
            await client.send_message(chat_id=_ALLOWED_USER, text="hi back")
        finally:
            await client.aclose()

        assert len(updates) == 1
        assert updates[0].message is not None
        assert updates[0].message.text == "hello"
        assert updates[0].message.from_user is not None and updates[0].message.from_user.id == _ALLOWED_USER
        assert fake.sent == [{"chat_id": _ALLOWED_USER, "text": "hi back"}]

    @pytest.mark.parametrize(
        ("response", "status", "retry_after"),
        [
            (
                httpx.Response(
                    429,
                    json={
                        "ok": False,
                        "error_code": 429,
                        "description": "slow",
                        "parameters": {"retry_after": 7},
                    },
                ),
                429,
                7.0,
            ),
            (
                httpx.Response(
                    403, json={"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked"}
                ),
                403,
                None,
            ),
            (httpx.Response(502, text="<html>gateway</html>"), 502, None),
        ],
    )
    async def test_api_errors_carry_status_and_retry_after_but_never_the_token(
        self, response: httpx.Response, status: int, retry_after: Optional[float]
    ) -> None:
        fake: FakeBotAPI = FakeBotAPI()
        fake.send_failures.append(response)
        client: TelegramBotAPIClient = _client(fake=fake)
        try:
            with pytest.raises(TelegramAPIError) as raised:
                await client.send_message(chat_id=_ALLOWED_USER, text="x")
        finally:
            await client.aclose()

        assert raised.value.status_code == status
        assert raised.value.retry_after == retry_after
        assert _TOKEN not in str(raised.value)

    async def test_network_errors_are_api_errors_without_the_token(self) -> None:
        def _refuse(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"cannot reach {request.url}")

        client: TelegramBotAPIClient = TelegramBotAPIClient(
            token=_TOKEN, transport=httpx.MockTransport(_refuse)
        )
        try:
            with pytest.raises(TelegramAPIError) as raised:
                await client.get_updates(offset=5, timeout_s=1)
        finally:
            await client.aclose()

        assert raised.value.status_code is None
        assert _TOKEN not in str(raised.value)
        assert "<redacted>" in str(raised.value)

    async def test_http_request_logs_never_contain_the_token(self, caplog: pytest.LogCaptureFixture) -> None:
        fake: FakeBotAPI = FakeBotAPI()
        client: TelegramBotAPIClient = _client(fake=fake)
        caplog.set_level(logging.INFO, logger="httpx")
        try:
            await client.send_message(chat_id=_ALLOWED_USER, text="x")
        finally:
            await client.aclose()

        assert "sendMessage" in caplog.text
        assert _TOKEN not in caplog.text


def _write_config(*, path: Path, payload: object, mode: int = 0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
    os.chmod(path, mode)
    return path


class TestTelegramConfig:
    def test_valid_file_loads_with_defaults(self, tmp_path: Path) -> None:
        path: Path = _write_config(path=tmp_path / "telegram.json", payload={"allowed_user_ids": [1, 2]})

        config: TelegramConfigDAO = TelegramConfigDAO.load(path=path)

        assert config.allowed_user_ids == [1, 2]
        assert (config.bot_token_env, config.poll_timeout_s, config.max_reply_chars) == (
            "SLO_TELEGRAM_BOT_TOKEN",
            30,
            4000,
        )

    @pytest.mark.parametrize(
        ("payload", "mode", "fragment"),
        [
            ("{not json", 0o600, "not valid"),
            ({"allowed_user_ids": []}, 0o600, "allowed_user_ids"),
            ({}, 0o600, "allowed_user_ids"),
            ({"allowed_user_ids": [1], "bot_token": "123:abc"}, 0o600, "bot_token"),
            ({"allowed_user_ids": [1], "max_reply_chars": 5000}, 0o600, "max_reply_chars"),
            ({"allowed_user_ids": [1]}, 0o644, "chmod 600"),
            ({"allowed_user_ids": [1]}, 0o620, "chmod 600"),
        ],
    )
    def test_invalid_files_are_config_errors(
        self, tmp_path: Path, payload: object, mode: int, fragment: str
    ) -> None:
        path: Path = _write_config(path=tmp_path / "telegram.json", payload=payload, mode=mode)

        with pytest.raises(AdapterConfigError) as raised:
            TelegramConfigDAO.load(path=path)

        assert fragment in str(raised.value)
        assert "123:abc" not in str(raised.value)

    def test_missing_file_names_the_path(self, tmp_path: Path) -> None:
        with pytest.raises(AdapterConfigError) as raised:
            TelegramConfigDAO.load(path=tmp_path / "telegram.json")

        assert str(tmp_path / "telegram.json") in str(raised.value)

    def test_token_comes_from_the_named_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_BOT_TOKEN", _TOKEN)
        config: TelegramConfigDAO = _config(bot_token_env="MY_BOT_TOKEN")

        assert config.resolve_bot_token() == _TOKEN

    def test_missing_token_names_the_variable_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SLO_TELEGRAM_BOT_TOKEN", raising=False)

        with pytest.raises(AdapterConfigError) as raised:
            _config().resolve_bot_token()

        assert "SLO_TELEGRAM_BOT_TOKEN" in str(raised.value)


class TestTelegramFromRegistry:
    def test_builtin_telegram_builds_from_its_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SLO_TELEGRAM_BOT_TOKEN", _TOKEN)
        path: Path = _write_config(path=tmp_path / "work-telegram.json", payload={"allowed_user_ids": [7]})

        adapter = AdapterRegistry.load(builtin="telegram", config_path=path)

        assert isinstance(adapter, TelegramAdapter)
        assert (adapter.kind, adapter.name) == ("telegram", "work-telegram")

    def test_default_config_path_is_under_slo_home(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SLO_TELEGRAM_BOT_TOKEN", _TOKEN)
        _write_config(
            path=ChannelGateway.default_channels_dir() / "telegram.json", payload={"allowed_user_ids": [7]}
        )

        adapter = AdapterRegistry.load(builtin="telegram")

        assert isinstance(adapter, TelegramAdapter) and adapter.name == "telegram"

    def test_missing_token_fails_before_the_host_starts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_TELEGRAM_BOT_TOKEN", raising=False)
        path: Path = _write_config(path=tmp_path / "telegram.json", payload={"allowed_user_ids": [7]})

        with pytest.raises(AdapterConfigError):
            AdapterRegistry.load(builtin="telegram", config_path=path)

    async def test_adapter_without_client_or_token_makes_the_host_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SLO_TELEGRAM_BOT_TOKEN", raising=False)
        gateway: ChannelGateway = await _open_gateway(tmp_path=tmp_path)
        try:
            host: AdapterHost = AdapterHost(adapter=TelegramAdapter(config=_config()), gateway=gateway)

            assert await asyncio.wait_for(host.run(), timeout=10.0) == 1
        finally:
            await gateway.close()
