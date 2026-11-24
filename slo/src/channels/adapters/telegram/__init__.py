"""Telegram reference adapter: ``slo channel run telegram`` (108.5)."""

from src.channels.adapters.telegram.adapter import TelegramAdapter
from src.channels.adapters.telegram.config import TelegramConfigDAO

__all__ = ["TelegramAdapter", "TelegramConfigDAO"]
