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
from typing import TYPE_CHECKING, Optional, TextIO
from uuid import UUID

from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.dao import ChannelMessageDAO

if TYPE_CHECKING:
    from src.cli.headless import HeadlessRunner

__all__ = ["HeadlessTurnRunner", "followup_turn_cap"]

_DEFAULT_FOLLOWUP_TURNS: int = 10
_MAX_ERROR_CHARS: int = 500
"""Bound on the error line a failed follow-up turn reports in its reply."""


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

    Delegates to ``HeadlessRunner.run_channel_turn`` so a follow-up turn
    honours the same supervision (abort funnel, watchdog) as the main run.
    The stdout JSONL stream receives a ``channel_turn`` marker line before the
    turn's own events so capture pipelines can attribute the events that
    follow. Acceptance happens on the turn's first event, after the
    ``user_message`` history record carrying the row id is written.
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

        Args:
            message (ChannelMessageDAO): The pending prompt row to run.
            on_started (Callable[[], Awaitable[None]]): Acceptance callback,
                awaited once after the first session event.

        Returns:
            TurnOutcomeDAO: ``not_started`` (and ``on_started`` never called)
                when the session yielded no event; otherwise how the turn
                ended and its final text.
        """
        generation_before: int = self._runner.terminal_generation
        started: list[bool] = [False]

        async def _accept_on_first_event() -> None:
            """Record that the turn started, then stamp the row accepted."""
            started[0] = True
            await on_started()

        try:
            await self._runner.run_channel_turn(message=message, on_started=_accept_on_first_event)
        except Exception as exc:  # noqa: BLE001 — a turn failure becomes its outcome
            if not started[0]:
                return TurnOutcomeDAO(status="not_started", error=str(exc)[:_MAX_ERROR_CHARS])
            return TurnOutcomeDAO(
                status="failed",
                error=(self._runner.terminal_content or str(exc))[:_MAX_ERROR_CHARS],
            )
        if not started[0]:
            return TurnOutcomeDAO(status="not_started", error="run produced no event")
        if self._runner.terminal_generation == generation_before:
            return TurnOutcomeDAO(status="failed", error="run produced no terminal event")
        return self._outcome_for_terminal(
            terminal_kind=self._runner.terminal_kind,
            terminal_content=self._runner.terminal_content,
        )

    @staticmethod
    def _outcome_for_terminal(*, terminal_kind: str, terminal_content: str) -> TurnOutcomeDAO:
        """Map the turn's terminal event to its outcome.

        Args:
            terminal_kind (str): e.g. ``run_completed``.
            terminal_content (str): The terminal event's text.

        Returns:
            TurnOutcomeDAO: The mapped outcome.
        """
        if terminal_kind == "run_completed":
            return TurnOutcomeDAO(status="completed", final_text=terminal_content)
        if terminal_kind == "run_aborted":
            return TurnOutcomeDAO(status="aborted", final_text=terminal_content)
        return TurnOutcomeDAO(status="failed", error=(terminal_content or terminal_kind)[:_MAX_ERROR_CHARS])


def emit_channel_turn_marker(*, output_stream: Optional[TextIO], message_id: UUID) -> None:
    """Write one raw ``channel_turn`` marker line to the JSONL stream.

    The marker is a plain JSON object (not an ``AgentStreamEventDAO``) because
    it is transport bookkeeping, not a session event.

    Args:
        output_stream (Optional[TextIO]): Borrowed text stream, never closed;
            ``None`` writes to the current ``sys.stdout``.
        message_id (UUID): Id of the channel row being run.
    """
    stream: TextIO = output_stream if output_stream is not None else sys.stdout
    stream.write(json.dumps({"kind": "channel_turn", "message_id": str(message_id)}) + "\n")
    stream.flush()
