"""EchoAdapter — the custom-adapter fixture for 108.5 X5.

Loaded by reference (``slo channel run --adapter tests.fixtures:EchoAdapter``)
and built with no arguments, like any custom adapter. It reads its script from
the environment, so the same class works in-process and in a subprocess:

- ``SLO_ECHO_ADAPTER_SCRIPT``: JSON ``{"user_ref": "...", "texts": ["...", ...]}``.
  Each text is handed to ``ctx.inbound`` in order once the adapter starts.
- ``SLO_ECHO_ADAPTER_OUTBOX``: JSONL file. Every ``inbound`` answer
  (``{"kind": "answer", ...}``) and every delivered row
  (``{"kind": "delivered", ...}``) is appended, so the test can read the round
  trip back.
- ``SLO_ECHO_ADAPTER_NAME``: optional instance name (default ``echo``).
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Optional

from src.channels.dao import ChannelMessageDAO, InboundTextDAO, ParticipantDAO
from src.channels.protocol import AdapterContext

__all__ = ["EchoAdapter"]


class EchoAdapter:
    """A minimal platform: scripted user input in, delivered rows out to a file."""

    def __init__(self) -> None:
        """Read the script, outbox and name from the environment."""
        script: dict[str, object] = json.loads(os.environ.get("SLO_ECHO_ADAPTER_SCRIPT", "{}"))
        self._user_ref: str = str(script.get("user_ref", "echo-user"))
        self._texts: list[str] = [str(text) for text in script.get("texts", [])]  # type: ignore[attr-defined]
        outbox: Optional[str] = os.environ.get("SLO_ECHO_ADAPTER_OUTBOX")
        self._outbox: Optional[Path] = Path(outbox) if outbox else None
        self._name: str = os.environ.get("SLO_ECHO_ADAPTER_NAME", "echo")
        self._reader: Optional[asyncio.Task[None]] = None
        self.delivered: list[ChannelMessageDAO] = []

    @property
    def kind(self) -> str:
        """Return the channel kind this fixture registers as."""
        return "http"

    @property
    def name(self) -> str:
        """Return the adapter instance name."""
        return self._name

    async def start(self, *, ctx: AdapterContext) -> None:
        """Start handing the scripted texts to the host.

        Args:
            ctx (AdapterContext): The host context.
        """
        self._reader = asyncio.create_task(self._send_script(ctx=ctx))

    async def deliver(self, *, message: ChannelMessageDAO, user: ParticipantDAO) -> bool:
        """Record one delivered row in memory and in the outbox.

        Args:
            message (ChannelMessageDAO): The outbound row.
            user (ParticipantDAO): Its recipient.

        Returns:
            bool: Always ``True``.
        """
        self.delivered.append(message)
        self._append(
            record={
                "kind": "delivered",
                "text": message.message_contents,
                "message_type": message.message_type,
                "in_reply_to_id": str(message.in_reply_to_id) if message.in_reply_to_id else None,
                "user_ref": user.external_ref,
            }
        )
        return True

    async def stop(self) -> None:
        """Cancel the script task."""
        if self._reader is not None:
            self._reader.cancel()
            await asyncio.gather(self._reader, return_exceptions=True)

    async def _send_script(self, *, ctx: AdapterContext) -> None:
        """Hand each scripted text to ``ctx.inbound`` and record its answer.

        Args:
            ctx (AdapterContext): The host context.
        """
        for text in self._texts:
            answer: ChannelMessageDAO | str = await ctx.inbound(
                item=InboundTextDAO(external_user_ref=self._user_ref, display_name="echo user", text=text)
            )
            self._append(
                record={
                    "kind": "answer",
                    "text": text,
                    "answer": answer if isinstance(answer, str) else None,
                    "message_id": str(answer.id) if isinstance(answer, ChannelMessageDAO) else None,
                }
            )

    def _append(self, *, record: dict[str, object]) -> None:
        """Append one JSON line to the outbox, when one is configured.

        Args:
            record (dict[str, object]): The line to write.
        """
        if self._outbox is None:
            return
        with self._outbox.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
