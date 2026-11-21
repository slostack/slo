"""AgentComposerComponent — message a running orchestrator from the workflow modal (108.3 §5).

The component owns the composer presentation: a ``to: <label>`` header, the
input (Enter sends a normal prompt; Ctrl+Enter / Alt+Enter send a forced one),
and the last five ``SentMessageRowDAO`` rows refreshed every 500 ms. It is
disabled showing ``agent finished`` once the target participant's status is
``closed`` or a send hits ``RecipientClosedError``. Delivery itself belongs to
the injected ``TuiChannelAdapter``; the component decides nothing about the
queue.
"""

from __future__ import annotations

from uuid import UUID

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static
from textual.message import Message

from src.channels.dao import SentMessageRowDAO
from src.channels.errors import RecipientClosedError
from src.tui.channel.adapter import TuiChannelAdapter

__all__ = ["AgentComposerComponent", "AGENT_FINISHED_NOTICE"]

AGENT_FINISHED_NOTICE: str = "agent finished"
"""Shown, with the input disabled, once the target agent can no longer listen."""

_CLOSED_STATUS: str = "closed"
_REFRESH_SECONDS: float = 0.5
_MAX_ROWS: int = 5
_PREVIEW_CHARS: int = 80


class AgentComposerComponent(Vertical):
    """Compose one prompt for the orchestrator and show its delivery state."""

    DEFAULT_CSS = """
    AgentComposerComponent {
        height: auto;
        max-height: 10;
        border-top: solid $primary;
        padding: 0 1;
        & .agent-composer-header {
            color: $accent;
            height: 1;
        }
        & .agent-composer-rows {
            color: $text-muted;
            height: auto;
            max-height: 4;
        }
        & Input {
            height: 1;
        }
    }

    """

    class Forced(Message):
        """Internal marker for the forced-delivery submit path."""

    def __init__(
        self,
        *,
        target_agent_id: UUID,
        target_label: str,
        adapter: TuiChannelAdapter,
    ) -> None:
        """Bind the composer to its target agent and the sending adapter.

        Args:
            target_agent_id (UUID): Participant id of the agent being messaged.
            target_label (str): Label rendered in the ``to:`` header.
            adapter (TuiChannelAdapter): The TUI channel adapter that owns the
                sends and the row queries.
        """
        super().__init__()
        self._target_agent_id: UUID = target_agent_id
        self._target_label: str = target_label
        self._adapter: TuiChannelAdapter = adapter
        self._finished: bool = False

    @property
    def target_agent_id(self) -> UUID:
        """Return the participant id the composer sends to.

        Returns:
            UUID: The target agent participant.
        """
        return self._target_agent_id

    def compose(self) -> ComposeResult:
        """Build the header, the input and the delivery-state rows."""
        yield Static(
            content=f"to: {self._target_label} · ⏎ send · Ctrl+⏎ force",
            markup=False,
            classes="agent-composer-header",
        )
        yield Input(placeholder="message the orchestrator…", id="agent-composer-input")
        yield Static(content="", markup=False, classes="agent-composer-rows")

    def on_mount(self) -> None:
        """Start the 500 ms row refresh."""
        self.set_interval(_REFRESH_SECONDS, self._refresh_rows)

    async def _refresh_rows(self) -> None:
        """Refresh the delivery rows and the finished state from the queue."""
        if self._adapter.agent_participant_status is None:  # pragma: no cover - always set
            return
        try:
            status: str | None = await self._adapter.agent_participant_status(
                session_id=str(self._target_agent_id),
            )
        except Exception:  # noqa: BLE001 — a broken queue must not kill the modal
            return
        if status == _CLOSED_STATUS:
            self._mark_finished()
        else:
            try:
                rows: list[SentMessageRowDAO] = await self._adapter.sent_to_agent(
                    session_id=str(self._target_agent_id),
                    limit=_MAX_ROWS,
                )
            except Exception:  # noqa: BLE001 — a broken queue must not kill the modal
                return
            rows_static: Static = self.query_one(".agent-composer-rows", Static)
            rows_static.update(content="\n".join(self._render_row(row=row) for row in rows))

    @staticmethod
    def _render_row(*, row: SentMessageRowDAO) -> str:
        """Render one sent-message row.

        Args:
            row (SentMessageRowDAO): The composer row.

        Returns:
            str: One line with the state marker, forced marker, preview and
                reply preview.
        """
        marker: str = {
            "queued": "…",
            "accepted": "✓",
            "cancelled": "✗",
        }[row.state]
        forced: str = " (forced)" if row.forced else ""
        line: str = f"{marker}{forced} {row.preview}"
        if row.reply_preview is not None:
            line += f" ↩ {row.reply_preview}"
        return line

    @on(Input.Submitted, "#agent-composer-input")
    async def _submit(self, event: Input.Submitted) -> None:
        """Send the current text as a normal prompt (Enter)."""
        await self._send(force=False)

    async def _on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        """Intercept Ctrl+Enter and Alt+Enter before the input sees them.

        Args:
            event (events.Key): The key event bubbling from the input.
        """
        if event.key in ("ctrl+enter", "alt+enter"):
            event.stop()
            event.prevent_default()
            await self._send(force=True)

    async def _send(self, *, force: bool) -> None:
        """Send the composer's text through the adapter.

        A ``RecipientClosedError`` marks the composer finished (108.3 §6).

        Args:
            force (bool): True sends the row forced.
        """
        if self._finished:
            return
        input_widget: Input = self.query_one("#agent-composer-input", Input)
        text: str = input_widget.value.strip()
        if not text:
            return
        try:
            await self._adapter.send_prompt_to_agent(
                session_id=str(self._target_agent_id),
                text=text,
                force=force,
            )
        except RecipientClosedError:
            self._mark_finished()
            return
        input_widget.value = ""
        await self._refresh_rows()

    def _mark_finished(self) -> None:
        """Disable the input and show the fixed finished notice."""
        if self._finished:
            return
        self._finished = True
        self.add_class("-agent-finished")
        input_widget: Input = self.query_one("#agent-composer-input", Input)
        input_widget.disabled = True
        input_widget.placeholder = AGENT_FINISHED_NOTICE
        rows_static: Static = self.query_one(".agent-composer-rows", Static)
        rows_static.update(content=AGENT_FINISHED_NOTICE)

    @property
    def is_finished(self) -> bool:
        """Return whether the composer is disabled because the agent finished.

        Returns:
            bool: True once the target closed or refused a send.
        """
        return self._finished
