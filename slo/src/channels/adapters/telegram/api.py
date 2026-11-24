"""Telegram Bot API client: ``getUpdates`` long-poll and ``sendMessage`` (108.5 §5).

Outbound HTTPS only; nothing listens for inbound connections. The bot token
is part of every request URL (``/bot<token>/<method>``), so this module keeps
it out of everything it reports: errors carry a redacted URL, and a logging
filter redacts the token from ``httpx``'s own request log lines.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

__all__ = [
    "TelegramAPIError",
    "TelegramBotAPIClient",
    "TelegramChatDAO",
    "TelegramMessageDAO",
    "TelegramUpdateDAO",
    "TelegramUserDAO",
]

DEFAULT_BASE_URL: str = "https://api.telegram.org"
"""The public Bot API endpoint."""

_REQUEST_TIMEOUT_S: float = 15.0
"""HTTP timeout for ordinary calls; getUpdates adds its long-poll timeout."""

_TOKEN_IN_URL: re.Pattern[str] = re.compile(r"/bot[^/\s]+")
"""The ``/bot<token>`` URL segment."""


class TelegramAPIError(Exception):
    """A Bot API call failed (HTTP error, ``ok: false``, bad response, or network error)."""

    def __init__(
        self,
        *,
        method: str,
        description: str,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        """Record the failure. ``description`` must already be token-free.

        Args:
            method (str): Bot API method, e.g. ``sendMessage``.
            description (str): What went wrong (redacted).
            status_code (Optional[int]): HTTP / Bot API error code; ``None``
                for network errors.
            retry_after (Optional[float]): Seconds Telegram asked us to wait (429).
        """
        self.method: str = method
        self.description: str = description
        self.status_code: Optional[int] = status_code
        self.retry_after: Optional[float] = retry_after
        super().__init__(f"Telegram {method} failed ({status_code or 'network'}): {description}")


class TelegramUserDAO(BaseModel):
    """The ``from`` user of a Telegram message (only the fields Slo reads)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int = Field(description="Telegram user id; the allow-list is checked against it.")
    first_name: str = Field(default="", description="User's first name, used as the display name.")
    username: Optional[str] = Field(default=None, description="User's @username, if any.")


class TelegramChatDAO(BaseModel):
    """The chat a Telegram message belongs to."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: int = Field(description="Chat id; equals the user id in a private chat.")
    type: str = Field(description="'private', 'group', 'supergroup' or 'channel'.")


class TelegramMessageDAO(BaseModel):
    """One incoming Telegram message (only the fields Slo reads)."""

    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    message_id: int = Field(description="Message id within its chat.")
    chat: TelegramChatDAO = Field(description="Chat the message was sent in.")
    from_user: Optional[TelegramUserDAO] = Field(
        default=None, alias="from", description="Sender; absent for channel posts."
    )
    text: Optional[str] = Field(default=None, description="Message text; None for stickers, photos, …")


class TelegramUpdateDAO(BaseModel):
    """One ``getUpdates`` result entry."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    update_id: int = Field(description="Increasing update id; the next offset is this + 1.")
    message: Optional[TelegramMessageDAO] = Field(default=None, description="New message, if this is one.")


class _ResponseParametersDAO(BaseModel):
    """``parameters`` of a failed Bot API response."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    retry_after: Optional[float] = Field(default=None, description="Seconds to wait before retrying (429).")


class _BotAPIResponseDAO(BaseModel):
    """The envelope of every Bot API response."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    ok: bool = Field(description="Whether the call succeeded.")
    result: object = Field(default=None, description="Method-specific result when ok.")
    error_code: Optional[int] = Field(default=None, description="Error code when not ok.")
    description: Optional[str] = Field(default=None, description="Human-readable error when not ok.")
    parameters: Optional[_ResponseParametersDAO] = Field(default=None, description="Retry hints when not ok.")


_UPDATES: TypeAdapter[list[TelegramUpdateDAO]] = TypeAdapter(list[TelegramUpdateDAO])


class _BotTokenRedactingFilter(logging.Filter):
    """Redacts ``/bot<token>`` from ``httpx`` request log lines."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record's message with the token segment redacted.

        Args:
            record (logging.LogRecord): The log record.

        Returns:
            bool: Always ``True`` (the record is kept).
        """
        message: str = record.getMessage()
        if "/bot" in message:
            record.msg = _redact(text=message)
            record.args = None
        return True


def _install_log_redaction() -> None:
    """Attach the redacting filter to the ``httpx`` logger once per process."""
    httpx_logger: logging.Logger = logging.getLogger("httpx")
    if not any(isinstance(existing, _BotTokenRedactingFilter) for existing in httpx_logger.filters):
        httpx_logger.addFilter(_BotTokenRedactingFilter())


def _redact(*, text: str) -> str:
    """Replace every ``/bot<token>`` segment with ``/bot<redacted>``.

    Args:
        text (str): Text that may contain a request URL.

    Returns:
        str: The text without the token.
    """
    return _TOKEN_IN_URL.sub("/bot<redacted>", text)


class TelegramBotAPIClient:
    """Async client for the two Bot API methods the adapter needs."""

    def __init__(
        self,
        *,
        token: str,
        base_url: str = DEFAULT_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        """Prepare the client; the HTTP connection pool opens on the first call.

        Args:
            token (str): The bot token.
            base_url (str): Bot API endpoint. Defaults to ``https://api.telegram.org``.
            transport (Optional[httpx.AsyncBaseTransport]): HTTP transport
                override (tests pass a fake Bot API). Defaults to real HTTPS.
        """
        self._token: str = token
        self._base_url: str = base_url.rstrip("/")
        self._transport: Optional[httpx.AsyncBaseTransport] = transport
        self._http: Optional[httpx.AsyncClient] = None
        _install_log_redaction()

    async def get_updates(self, *, offset: Optional[int], timeout_s: int) -> list[TelegramUpdateDAO]:
        """Long-poll for new messages.

        Args:
            offset (Optional[int]): First update id wanted; passing ``last + 1``
                confirms (and drops) everything before it. ``None`` on start.
            timeout_s (int): Long-poll seconds Telegram may hold the request.

        Returns:
            list[TelegramUpdateDAO]: New updates, oldest first.

        Raises:
            TelegramAPIError: The call failed.
        """
        payload: dict[str, object] = {"timeout": timeout_s, "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        result: object = await self._call(
            method="getUpdates", payload=payload, timeout_s=timeout_s + _REQUEST_TIMEOUT_S
        )
        try:
            return _UPDATES.validate_python(result)
        except ValidationError:
            raise TelegramAPIError(method="getUpdates", description="unexpected result shape") from None

    async def send_message(self, *, chat_id: int, text: str) -> None:
        """Send one text message to one chat.

        Args:
            chat_id (int): Target chat (the user id for a private chat).
            text (str): Message text, at most 4096 characters.

        Raises:
            TelegramAPIError: The call failed; ``retry_after`` is set for 429.
        """
        await self._call(
            method="sendMessage", payload={"chat_id": chat_id, "text": text}, timeout_s=_REQUEST_TIMEOUT_S
        )

    async def aclose(self) -> None:
        """Close the HTTP connection pool (idempotent)."""
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    async def _call(self, *, method: str, payload: dict[str, object], timeout_s: float) -> object:
        """POST one Bot API method and unwrap its ``result``.

        Args:
            method (str): Bot API method name.
            payload (dict[str, object]): JSON body.
            timeout_s (float): HTTP timeout for this call.

        Returns:
            object: The response's ``result``.

        Raises:
            TelegramAPIError: Network error, non-JSON body, HTTP error or ``ok: false``.
        """
        if self._http is None:
            self._http = httpx.AsyncClient(transport=self._transport)
        try:
            response: httpx.Response = await self._http.post(
                url=f"{self._base_url}/bot{self._token}/{method}", json=payload, timeout=timeout_s
            )
        except httpx.HTTPError as exc:
            raise TelegramAPIError(
                method=method, description=self._scrub(text=f"{type(exc).__name__}: {exc}")
            ) from None
        envelope: Optional[_BotAPIResponseDAO] = self._parse_envelope(response=response)
        if envelope is None:
            raise TelegramAPIError(
                method=method, description="response is not Bot API JSON", status_code=response.status_code
            )
        if not envelope.ok or response.is_error:
            raise TelegramAPIError(
                method=method,
                description=self._scrub(text=envelope.description or "request refused"),
                status_code=envelope.error_code or response.status_code,
                retry_after=envelope.parameters.retry_after if envelope.parameters is not None else None,
            )
        return envelope.result

    @staticmethod
    def _parse_envelope(*, response: httpx.Response) -> Optional[_BotAPIResponseDAO]:
        """Parse the Bot API envelope, or ``None`` when the body is not one.

        Args:
            response (httpx.Response): The HTTP response.

        Returns:
            Optional[_BotAPIResponseDAO]: The parsed envelope.
        """
        try:
            return _BotAPIResponseDAO.model_validate_json(response.content)
        except ValidationError:
            return None

    def _scrub(self, *, text: str) -> str:
        """Remove the token from ``text`` (URL segments and bare occurrences).

        Args:
            text (str): Text that may contain the token.

        Returns:
            str: The redacted text.
        """
        return _redact(text=text).replace(self._token, "<redacted>")
