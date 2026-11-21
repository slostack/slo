"""TuiTurnRunner — runs one accepted channel prompt row as one TUI run (108.1).

The body is what ``SloTUI._run_prompt`` used to do for one prompt: begin a
transcript run, echo the user's text, mount the spinner, drain
``session.invoke`` (carrying the channel message id), render failures, and
refresh the usage surfaces. The terminal event maps to a ``TurnOutcomeDAO``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Optional, TYPE_CHECKING

from src.agents.slo_agent.channel_delivery.turn_runner import TurnOutcomeDAO
from src.channels.dao import ChannelMessageDAO
from src.tui.components.chat_transcript.commands import (
    BeginTranscriptRunDAO,
    EchoUserDAO,
    TranscriptNoticeDAO,
)

if TYPE_CHECKING:
    from src.tui.app import SloTUI

__all__ = ["TuiTurnRunner"]


class TuiTurnRunner:
    """Runs channel prompt rows through the mounted TUI's transcript."""

    def __init__(self, *, app: "SloTUI") -> None:
        """Bind the runner to the app it renders into.

        Args:
            app (SloTUI): The mounted TUI app.
        """
        self._app: "SloTUI" = app

    async def run(
        self,
        *,
        message: ChannelMessageDAO,
        on_started: Callable[[], Awaitable[None]],
    ) -> TurnOutcomeDAO:
        """Run one accepted prompt row to its terminal event.

        Echoes the text at run start (so the transcript order matches the
        model's context order), drains ``session.invoke`` carrying the
        channel message id, calls ``on_started`` after the first yielded
        event, and maps the terminal event to a ``TurnOutcomeDAO``.

        Args:
            message (ChannelMessageDAO): The accepted prompt row.
            on_started (Callable[[], Awaitable[None]]): First-event callback
                the poller uses to stamp ``accepted_at``.

        Returns:
            TurnOutcomeDAO: How the run ended and its final text.
        """
        app: "SloTUI" = self._app
        transcript = app._chat_transcript
        if transcript is None:
            return TurnOutcomeDAO(status="not_started", error="transcript unavailable")
        await transcript.handle(command=BeginTranscriptRunDAO())
        await transcript.handle(command=EchoUserDAO(text=message.message_contents))
        app._reset_escape_sequence()
        await app._mount_spinner()
        started: bool = False
        saw_failed_event: bool = False
        status: str = "not_started"
        final_text: str = ""
        error: Optional[str] = None
        stream = self._session_invoke_stream(message=message)
        try:
            async for event in stream:
                if not started:
                    started = True
                    await on_started()
                if event.kind == "run_completed":
                    status = "completed"
                    final_text = event.content or ""
                elif event.kind == "run_aborted":
                    status = "aborted"
                elif event.kind in {"run_failed", "recovery_exhausted"}:
                    status = "failed"
                    saw_failed_event = True
                    error = event.content or "run failed"
        except asyncio.CancelledError:
            status = "aborted"
            await transcript.handle(
                command=TranscriptNoticeDAO(content="(aborted)", classes="assistant-aborted")
            )
        except ValueError as exc:
            status = "failed" if started else "not_started"
            error = f"configuration error: {exc}"
            await transcript.handle(
                command=TranscriptNoticeDAO(content=f"(configuration error: {exc})", classes="tool-result")
            )
        except Exception as exc:  # noqa: BLE001 — surface every failure to the user
            status = "failed" if started else "not_started"
            error = app._format_exception_for_transcript(exc=exc)
            if not saw_failed_event:
                await transcript.handle(
                    command=TranscriptNoticeDAO(content=f"(error: {error})", classes="assistant-aborted")
                )
        finally:
            app._reset_escape_sequence()
            await app._refresh_context_window_after_prompt()
            app._session.refresh_usage_snapshot()
            app._refresh_usage_status_bar()
            await app._unmount_spinner()
            await app._cleanup_sub_agent_state()
        return TurnOutcomeDAO(
            status=status,  # type: ignore[arg-type]
            final_text=final_text,
            error=error,
        )

    def _session_invoke_stream(self, *, message: ChannelMessageDAO):
        """Open the session stream carrying the row's channel message id.

        ``channel_message_id`` is always passed (108.1 §5.4): the A7 history
        link must exist for every production run, so no caller shape changes
        what the history records.

        Args:
            message (ChannelMessageDAO): The accepted prompt row to run.

        Returns:
            AsyncGenerator: The session's event stream for the row's text.
        """
        return self._app._session.invoke(
            text=message.message_contents,
            channel_message_id=message.id,
        )
