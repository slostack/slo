"""Headless channel wiring (108.3 §5): the follow-up turn runner and its cap.

``HeadlessTurnRunner`` runs one channel prompt row as one headless turn by
reusing ``HeadlessRunner``'s abort-aware stream drain, and reports the
outcome the poller's reply writer answers. The follow-up turn cap is read
from ``SLO_HEADLESS_FOLLOWUP_TURNS`` (default 10).
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.dao import ChannelMessageDAO

if TYPE_CHECKING:
    from src.cli.headless import HeadlessRunner

__all__ = ["HeadlessTurnRunner", "followup_turn_cap"]

_DEFAULT_FOLLOWUP_TURNS: int = 10


def followup_turn_cap() -> int:
    """Return the workflow follow-up turn cap.

    ``SLO_HEADLESS_FOLLOWUP_TURNS`` accepts any non-negative integer; invalid
    or negative values fall back to the 10-turn default (108.3 §5). ``0``
    disables follow-ups entirely.

    Returns:
        int: Maximum number of follow-up turns after the main run.
    """
    raw: str | None = os.environ.get("SLO_HEADLESS_FOLLOWUP_TURNS")
    if raw is None:
        return _DEFAULT_FOLLOWUP_TURNS
    try:
        value: int = int(raw)
    except ValueError:
        return _DEFAULT_FOLLOWUP_TURNS
    return value if value >= 0 else _DEFAULT_FOLLOWUP_TURNS


class HeadlessTurnRunner:
    """Runs one channel prompt row as one headless turn (108.3 §5).

    Reuses ``HeadlessRunner._drain_session_stream_until_abort`` so a follow-up
    turn honours the same cooperative-abort funnel as the main run. The stdout
    JSONL stream receives a ``channel_turn`` marker line before the turn's own
    events so capture pipelines can attribute the events that follow.
    """

    def __init__(self, *, runner: "HeadlessRunner") -> None:
        """Bind the turn runner to its owning headless runner.

        Args:
            runner (HeadlessRunner): The runner whose session and drain funnel
                execute the turn.
        """
        self._runner: "HeadlessRunner" = runner

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Run the row's text through the session and report the outcome.

        Emits the ``channel_turn`` stdout marker, stamps acceptance through
        ``on_started``, drains the session stream under the abort funnel, and
        maps the terminal event to a ``TurnOutcomeDAO``. A turn that never
        yielded a terminal event reports ``not_started``.

        Args:
            message (ChannelMessageDAO): The accepted prompt row.
            on_started (Callable[[], Awaitable[None]]): Acceptance callback.

        Returns:
            TurnOutcomeDAO: How the turn ended and its final text.
        """
        generation_before: int = self._runner.terminal_generation
        self._runner.emit_channel_turn(message_id=message.id)
        await on_started()
        session = self._runner.wired_session
        if session is None:
            return TurnOutcomeDAO(status="not_started", error="session unavailable")
        await self._runner._drain_session_stream_until_abort(
            session=session, prompt=message.message_contents
        )
        if self._runner.terminal_generation == generation_before:
            return TurnOutcomeDAO(status="not_started", error="run produced no terminal event")
        kind: str = self._runner.terminal_kind
        status: str = {
            "run_completed": "completed",
            "run_aborted": "aborted",
        }.get(kind, "failed")
        return TurnOutcomeDAO(
            status=status,  # type: ignore[arg-type]
            final_text=self._runner.terminal_content,
        )


def emit_channel_turn_marker(*, output_stream, message_id: object) -> None:
    """Write one raw ``channel_turn`` marker line to the JSONL stream.

    The marker is a plain JSON object (not an ``AgentStreamEventDAO``) because
    it is transport bookkeeping, not a session event.

    Args:
        output_stream: Borrowed text stream, never closed.
        message_id (object): Id of the channel row being run.
    """
    stream = output_stream if output_stream is not None else sys.stdout
    stream.write(
        json.dumps({"kind": "channel_turn", "message_id": str(message_id)}) + "\n"
    )
    stream.flush()
