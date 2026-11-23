"""Telegram adapter configuration (108.5 §4 ``TelegramConfigDAO``).

The config file (default ``$SLO_HOME/channels/telegram.json``) must be private
to its owner (mode 0600): it holds the allow-list that decides who may talk to
your agents. It never holds the bot token. The token stays in an environment
variable named by ``bot_token_env``.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.channels.errors import AdapterConfigError

__all__ = ["TelegramConfigDAO"]

_TELEGRAM_MESSAGE_LIMIT: int = 4096
"""Telegram's hard limit for one message's text."""

_TELEGRAM_LONG_POLL_LIMIT_S: int = 50
"""The longest getUpdates long-poll Telegram allows."""


class TelegramConfigDAO(BaseModel):
    """Settings for one Telegram bot adapter (``~/.slo/channels/telegram.json``, 0600)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bot_token_env: str = Field(
        default="SLO_TELEGRAM_BOT_TOKEN",
        pattern=r"^[A-Za-z_][A-Za-z0-9_]*$",
        description="Name of the env var holding the bot token; the token itself is never stored.",
    )
    allowed_user_ids: list[int] = Field(
        min_length=1,
        description="Telegram user ids allowed to talk to Slo; required.",
    )
    poll_timeout_s: int = Field(
        default=30,
        ge=0,
        le=_TELEGRAM_LONG_POLL_LIMIT_S,
        description="Long-poll timeout for getUpdates, in seconds.",
    )
    max_reply_chars: int = Field(
        default=4000,
        ge=1,
        le=_TELEGRAM_MESSAGE_LIMIT,
        description="Maximum characters per Telegram message; longer replies are split.",
    )

    @classmethod
    def load(cls, *, path: Path) -> "TelegramConfigDAO":
        """Read and validate one config file.

        Args:
            path (Path): The config file.

        Returns:
            TelegramConfigDAO: The validated settings.

        Raises:
            AdapterConfigError: The file is missing, readable or writable by
                other users, not JSON, or not a valid config. Messages name
                fields, never their values.
        """
        try:
            mode: int = path.stat().st_mode
        except FileNotFoundError:
            raise AdapterConfigError(
                f"Telegram config not found: {path}. Create it (mode 0600) with "
                '{"allowed_user_ids": [<your Telegram user id>]}.'
            ) from None
        if stat.S_IMODE(mode) & 0o077:
            raise AdapterConfigError(f"{path} must be private to you: chmod 600 {path}")
        try:
            data: object = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise AdapterConfigError(f"{path} is not valid JSON") from None
        try:
            return cls.model_validate(data)
        except ValidationError as exc:
            raise AdapterConfigError(f"{path}: {_describe_validation_error(error=exc)}") from None

    def resolve_bot_token(self) -> str:
        """Return the bot token from the configured environment variable.

        Returns:
            str: The token.

        Raises:
            AdapterConfigError: The variable is unset or empty; the message
                names the variable only.
        """
        token: str = os.environ.get(self.bot_token_env, "").strip()
        if not token:
            raise AdapterConfigError(f"Telegram bot token missing: set {self.bot_token_env}")
        return token


def _describe_validation_error(*, error: ValidationError) -> str:
    """Summarise a validation error by field and problem, without input values.

    Args:
        error (ValidationError): The pydantic error.

    Returns:
        str: e.g. ``allowed_user_ids: List should have at least 1 item``.
    """
    problems: list[str] = []
    for detail in error.errors(include_input=False, include_url=False):
        field: str = ".".join(str(part) for part in detail["loc"]) or "config"
        message: str = str(detail["msg"])
        if detail["type"] == "extra_forbidden" and field.startswith("bot_token"):
            message = "not allowed — the token is never stored; put it in the env var named by bot_token_env"
        problems.append(f"{field}: {message}")
    return "; ".join(problems)
