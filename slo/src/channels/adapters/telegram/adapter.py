"""TelegramAdapter — the reference external channel (108.5 §1, §5, §6).

```text
 Telegram ──getUpdates (long poll, HTTPS out)──► TelegramAdapter ──ctx.inbound──► AdapterHost ──► queue
 Telegram ◄──sendMessage──────────────────────── TelegramAdapter ◄──deliver────── AdapterHost ◄── queue
```

Security rules:

- Only users on ``allowed_user_ids`` are heard. Anything else is dropped and
  logged (user id only, never the text); nothing is sent back. Anyone can
  find a Telegram bot, so the allow-list is required.
- Only private chats are heard, so an agent's replies never land in a group.
- Rows for a user who was removed from the allow-list are not delivered.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional
from uuid import UUID

from src.channels.adapters.telegram.api import (
    TelegramAPIError,
    TelegramBotAPIClient,
    TelegramMessageDAO,
    TelegramUpdateDAO,
)
from src.channels.adapters.telegram.config import TelegramConfigDAO
from src.channels.dao import ChannelMessageDAO, InboundTextDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.host import DeliveryBackoff
from src.channels.protocol import AdapterContext

__all__ = ["TelegramAdapter"]

_PRIVATE_CHAT: str = "private"
_READ_BACKOFF: DeliveryBackoff = DeliveryBackoff(initial_s=1.0, max_s=60.0)
"""getUpdates retry schedule after errors without ``retry_after`` (1 s → 60 s)."""


class TelegramAdapter:
    """Connects one Telegram bot to the channel queue (httpx; getUpdates + sendMessage)."""

    def __init__(
        self,
        *,
        config: TelegramConfigDAO,
        name: str = "telegram",
        client: Optional[TelegramBotAPIClient] = None,
    ) -> None:
        """Prepare the adapter; nothing touches the network until ``start``.

        Args:
            config (TelegramConfigDAO): Allow-list, token variable and limits.
            name (str): Instance name; with the kind it fixes the channel row.
                Defaults to ``telegram``.
            client (Optional[TelegramBotAPIClient]): Bot API client. ``None``
                builds one in ``start`` from the token in ``config.bot_token_env``.
        """
        self._config: TelegramConfigDAO = config
        self._name: str = name
        self._client: Optional[TelegramBotAPIClient] = client
        self._allowed: frozenset[int] = frozenset(config.allowed_user_ids)
        self._reader: Optional[asyncio.Task[None]] = None
        self._ctx: Optional[AdapterContext] = None
        self._sent_parts: dict[UUID, int] = {}
        self._send_not_before: float = 0.0

    @classmethod
    def from_config_file(cls, *, config_path: Optional[Path] = None) -> "TelegramAdapter":
        """Build the adapter from a config file and the token in its env var.

        The instance name is the file's stem, so ``work-telegram.json`` gets
        its own channel row next to ``telegram.json``.

        Args:
            config_path (Optional[Path]): Config file; defaults to
                ``$SLO_HOME/channels/telegram.json``.

        Returns:
            TelegramAdapter: The configured adapter.

        Raises:
            AdapterConfigError: The file or the token is missing or invalid.
        """
        path: Path = config_path or ChannelGateway.default_channels_dir() / "telegram.json"
        config: TelegramConfigDAO = TelegramConfigDAO.load(path=path)
        return cls(
            config=config, name=path.stem, client=TelegramBotAPIClient(token=config.resolve_bot_token())
        )

    @property
    def kind(self) -> str:
        """Return ``telegram``."""
        return "telegram"

    @property
    def name(self) -> str:
        """Return the adapter instance name."""
        return self._name

    async def start(self, *, ctx: AdapterContext) -> None:
        """Start the getUpdates reader task.

        Args:
            ctx (AdapterContext): The host context.

        Raises:
            AdapterConfigError: No client was given and the token is missing.
        """
        if self._client is None:
            self._client = TelegramBotAPIClient(token=self._config.resolve_bot_token())
        self._ctx = ctx
        self._reader = asyncio.create_task(self._read_updates(ctx=ctx, client=self._client))

    async def stop(self) -> None:
        """Cancel the reader and close the HTTP client."""
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)
            self._reader = None
        if self._client is not None:
            await self._client.aclose()

    async def deliver(self, *, message: ChannelMessageDAO, user: ParticipantDAO) -> bool:
        """Send one row to the user's private chat, split into ``max_reply_chars`` parts.

        Parts already sent for this row are not sent again after a failure.
        After a 429 nothing is sent until ``retry_after`` has passed.

        Args:
            message (ChannelMessageDAO): Pending row for ``user``.
            user (ParticipantDAO): The Telegram user (``external_ref`` = user id).

        Returns:
            bool: ``True`` when every part was sent; ``False`` leaves the row
                pending for the host to retry.
        """
        chat_id: Optional[int] = self._allowed_chat_id(user=user)
        if chat_id is None or self._client is None:
            return False
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        if loop.time() < self._send_not_before:
            return False
        parts: list[str] = self._split(text=self._render(message=message))
        for index in range(self._sent_parts.get(message.id, 0), len(parts)):
            try:
                await self._client.send_message(chat_id=chat_id, text=parts[index])
            except TelegramAPIError as exc:
                self._sent_parts[message.id] = index
                self._note_send_failure(error=exc, loop=loop)
                return False
        self._sent_parts.pop(message.id, None)
        return True

    async def _read_updates(self, *, ctx: AdapterContext, client: TelegramBotAPIClient) -> None:
        """Long-poll getUpdates forever, confirming each batch through the next offset.

        Errors wait ``retry_after`` when Telegram gives one, otherwise back off
        1 s → 60 s. Runs until ``stop`` cancels it.

        Args:
            ctx (AdapterContext): The host context.
            client (TelegramBotAPIClient): The Bot API client.
        """
        offset: Optional[int] = None
        failures: int = 0
        while True:
            try:
                updates: list[TelegramUpdateDAO] = await client.get_updates(
                    offset=offset, timeout_s=self._config.poll_timeout_s
                )
            except TelegramAPIError as exc:
                failures += 1
                delay: float = exc.retry_after or _READ_BACKOFF.delay_after(failures=failures)
                ctx.log(msg="getUpdates failed", status=exc.status_code or "network", retry_in_s=f"{delay:g}")
                await asyncio.sleep(delay)
                continue
            failures = 0
            for update in updates:
                offset = update.update_id + 1
                await self._handle_update(ctx=ctx, client=client, update=update)

    async def _handle_update(
        self, *, ctx: AdapterContext, client: TelegramBotAPIClient, update: TelegramUpdateDAO
    ) -> None:
        """Hand one allowed private text message to the host; answer short texts.

        Args:
            ctx (AdapterContext): The host context.
            client (TelegramBotAPIClient): The Bot API client.
            update (TelegramUpdateDAO): One getUpdates entry.
        """
        message: Optional[TelegramMessageDAO] = update.message
        if message is None or message.from_user is None:
            return
        user_id: int = message.from_user.id
        if user_id not in self._allowed:
            ctx.log(msg="dropped a message from a user not on the allow-list", user_id=user_id)
            return
        if message.chat.type != _PRIVATE_CHAT or not message.text:
            ctx.log(
                msg="ignored a non-private or non-text message", user_id=user_id, chat_type=message.chat.type
            )
            return
        try:
            answer: ChannelMessageDAO | str = await ctx.inbound(
                item=InboundTextDAO(
                    external_user_ref=str(user_id),
                    display_name=f"{message.from_user.first_name or message.from_user.username or user_id} (telegram)",
                    text=message.text,
                    external_message_ref=str(update.update_id),
                )
            )
        except Exception as exc:  # noqa: BLE001 — one bad message must not stop reading
            ctx.log(msg="inbound failed", user_id=user_id, error=type(exc).__name__)
            return
        if isinstance(answer, str):
            await self._answer(ctx=ctx, client=client, chat_id=message.chat.id, text=answer)

    async def _answer(
        self, *, ctx: AdapterContext, client: TelegramBotAPIClient, chat_id: int, text: str
    ) -> None:
        """Send a short host answer (help, command result); failures are only logged.

        Args:
            ctx (AdapterContext): The host context.
            client (TelegramBotAPIClient): The Bot API client.
            chat_id (int): The private chat.
            text (str): The answer.
        """
        for part in self._split(text=text):
            try:
                await client.send_message(chat_id=chat_id, text=part)
            except TelegramAPIError as exc:
                ctx.log(msg="answer not sent", status=exc.status_code or "network")
                return

    def _allowed_chat_id(self, *, user: ParticipantDAO) -> Optional[int]:
        """Return the user's private chat id, or ``None`` when they must not get messages.

        Args:
            user (ParticipantDAO): The row's recipient.

        Returns:
            Optional[int]: The chat id, when ``external_ref`` is an allowed user id.
        """
        try:
            user_id: int = int(user.external_ref or "")
        except ValueError:
            return None
        if user_id not in self._allowed:
            if self._ctx is not None:
                self._ctx.log(msg="not delivering to a user no longer on the allow-list", user_id=user_id)
            return None
        return user_id

    def _note_send_failure(self, *, error: TelegramAPIError, loop: asyncio.AbstractEventLoop) -> None:
        """Record a failed send; a 429 blocks all sends until ``retry_after`` passes.

        Args:
            error (TelegramAPIError): The failure.
            loop (asyncio.AbstractEventLoop): The running loop (its clock).
        """
        if error.retry_after:
            self._send_not_before = loop.time() + error.retry_after
        if self._ctx is not None:
            self._ctx.log(
                msg="sendMessage failed",
                status=error.status_code or "network",
                retry_after_s=error.retry_after if error.retry_after else "-",
            )

    def _render(self, *, message: ChannelMessageDAO) -> str:
        """Return the text a row becomes in Telegram.

        Replies are sent as they are; other rows (notices, notes) name their sender.

        Args:
            message (ChannelMessageDAO): The row.

        Returns:
            str: The message text.
        """
        if message.message_type == "reply":
            return message.message_contents
        return f"[{message.sender_name}] {message.message_contents}"

    def _split(self, *, text: str) -> list[str]:
        """Split ``text`` into parts of at most ``max_reply_chars`` characters.

        Args:
            text (str): The full text.

        Returns:
            list[str]: The parts, in order (at least one).
        """
        size: int = self._config.max_reply_chars
        return [text[start : start + size] for start in range(0, len(text), size)] or [text]
