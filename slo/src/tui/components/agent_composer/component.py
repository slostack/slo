"""AgentComposerComponent — message a running agent from the workflow modal (108.3 §5, 108.4).

The component owns the composer presentation: a ``to: <label>`` header, the
input (Enter sends a normal prompt; Ctrl+Enter / Alt+Enter send a forced one;
for a child every send is forced by default), the notes other agents sent to
the viewed agent, and the last five ``SentMessageRowDAO`` rows refreshed every
500 ms. Once the target participant is ``closed`` (or a send hits
``RecipientClosedError``) the input is disabled and ``agent finished`` is
shown, while the final delivery rows (acks, replies, cancellations) stay
visible and keep refreshing. Queue reads and sends run in Textual workers so
the modal never blocks on SQLite. Delivery itself belongs to the injected
``TuiChannelAdapter``; the component decides nothing about the queue.
"""

from __future__ import annotations

from importlib.resources import files
from typing import ClassVar, Optional
from uuid import UUID

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Static
from textual.worker import Worker

from config.logger import log_warning
from src.channels.dao import ChannelMessageDAO, SentMessageRowDAO
from src.channels.errors import RecipientClosedError
from src.tui.channel.adapter import TuiChannelAdapter

__all__ = ["AgentComposerComponent", "AGENT_FINISHED_NOTICE"]

AGENT_FINISHED_NOTICE: str = "agent finished"
"""Shown, with the input disabled, once the target agent can no longer listen."""

_CLOSED_STATUS: str = "closed"
_REFRESH_SECONDS: float = 0.5
_MAX_ROWS: int = 5
_MAX_NOTES: int = 3
_PREVIEW_CHARS: int = 80
_FORCED_KEYS: frozenset[str] = frozenset({"ctrl+enter", "alt+enter"})
_REFRESH_WORKER_GROUP: str = "agent-composer-refresh"
_SEND_WORKER_GROUP: str = "agent-composer-send"
_STATE_MARKERS: dict[str, str] = {"queued": "…", "accepted": "✓", "cancelled": "✗"}


class AgentComposerComponent(Vertical):
    """Compose prompts for one running agent and show their delivery state."""

    DEFAULT_CSS: ClassVar[str] = (
        files("src.tui.components.agent_composer").joinpath("css.tcss").read_text(encoding="utf-8")
    )

    def __init__(
        self,
        *,
        target_agent_id: UUID,
        target_label: str,
        adapter: TuiChannelAdapter,
        default_force: bool = False,
    ) -> None:
        """Bind the composer to its target agent and the sending adapter.

        Args:
            target_agent_id (UUID): Participant id of the agent being messaged.
            target_label (str): Label rendered in the ``to:`` header.
            adapter (TuiChannelAdapter): The TUI channel adapter that owns the
                sends and the row queries.
            default_force (bool): ``True`` for a child, which runs one task
                without follow-up turns: Enter also sends forced (108.4 §2).
        """
        super().__init__()
        self._target_agent_id: UUID = target_agent_id
        self._target_label: str = target_label
        self._adapter: TuiChannelAdapter = adapter
        self._default_force: bool = default_force
        self._finished: bool = False

    @property
    def target_agent_id(self) -> UUID:
        """Return the participant id the composer sends to.

        Returns:
            UUID: The target agent participant.
        """
        return self._target_agent_id

    @property
    def default_force(self) -> bool:
        """Return whether Enter sends forced (child targets).

        Returns:
            bool: ``True`` when every send is forced.
        """
        return self._default_force

    @property
    def is_finished(self) -> bool:
        """Return whether the composer is disabled because the agent finished.

        Returns:
            bool: True once the target closed or refused a send.
        """
        return self._finished

    def compose(self) -> ComposeResult:
        """Build the header, the input, the incoming notes and the delivery rows."""
        enter_hint: str = "⏎ send (forced)" if self._default_force else "⏎ send · Ctrl+⏎ force"
        yield Static(
            content=f"to: {self._target_label} · {enter_hint}",
            markup=False,
            classes="agent-composer-header",
        )
        yield Input(placeholder=f"message {self._target_label}…", id="agent-composer-input")
        yield Static(content="", markup=False, classes="agent-composer-status")
        yield Static(content="", markup=False, classes="agent-composer-notes")
        yield Static(content="", markup=False, classes="agent-composer-rows")

    def on_mount(self) -> None:
        """Refresh once now, then every 500 ms, in an exclusive worker."""
        self._start_refresh_worker()
        self.set_interval(_REFRESH_SECONDS, self._start_refresh_worker)

    def _start_refresh_worker(self) -> Worker[None]:
        """Start (replacing any running one) the queue refresh worker.

        Returns:
            Worker[None]: The started worker.
        """
        return self.run_worker(
            self.refresh_delivery_state(),
            group=_REFRESH_WORKER_GROUP,
            exclusive=True,
            exit_on_error=False,
        )

    async def refresh_delivery_state(self) -> None:
        """Re-read the target's status, its incoming notes and the sent rows.

        A closed target disables the input; the rows are rendered either way
        so the final acks, replies and cancellations remain visible. Queue
        failures are logged and leave the last rendering in place.
        """
        try:
            status: Optional[str] = await self._adapter.agent_participant_status(
                session_id=str(self._target_agent_id),
            )
            notes: list[ChannelMessageDAO] = await self._adapter.notes_to_agent(
                session_id=str(self._target_agent_id),
                limit=_MAX_NOTES,
            )
            rows: list[SentMessageRowDAO] = await self._adapter.sent_to_agent(
                session_id=str(self._target_agent_id),
                limit=_MAX_ROWS,
            )
        except Exception as exc:  # noqa: BLE001 — a broken queue must not kill the modal
            log_warning(msg=f"agent composer refresh failed: {exc}")
            return
        if not self.is_attached:
            return
        if status == _CLOSED_STATUS:
            self._mark_finished()
        self.query_one(".agent-composer-notes", Static).update(
            content="\n".join(self._render_note(note=note) for note in notes)
        )
        self.query_one(".agent-composer-rows", Static).update(
            content="\n".join(self._render_row(row=row) for row in rows)
        )

    @staticmethod
    def _render_note(*, note: ChannelMessageDAO) -> str:
        """Render one incoming note line (``⊛ sender: text``).

        Args:
            note (ChannelMessageDAO): A note addressed to the viewed agent.

        Returns:
            str: One display line.
        """
        return f"⊛ {note.sender_name}: {note.message_contents[:_PREVIEW_CHARS]}"

    @staticmethod
    def _render_row(*, row: SentMessageRowDAO) -> str:
        """Render one sent-message row.

        Args:
            row (SentMessageRowDAO): The composer row.

        Returns:
            str: One line with the state marker, forced marker, preview,
                cancel reason and reply preview.
        """
        forced: str = " (forced)" if row.forced else ""
        line: str = f"{_STATE_MARKERS[row.state]}{forced} {row.preview}"
        if row.cancel_reason is not None:
            line += f" [{row.cancel_reason}]"
        if row.reply_preview is not None:
            line += f" ↩ {row.reply_preview}"
        return line

    @on(Input.Submitted, "#agent-composer-input")
    def _send_on_enter(self, event: Input.Submitted) -> None:
        """Send the draft (Enter): normal, or forced for a child target.

        Args:
            event (Input.Submitted): The input's submit message.
        """
        event.stop()
        self._start_send_worker(force=self._default_force)

    def on_key(self, event: events.Key) -> None:
        """Send the draft forced on Ctrl+Enter or Alt+Enter.

        Args:
            event (events.Key): The key event bubbling from the input.
        """
        if event.key not in _FORCED_KEYS:
            return
        event.stop()
        event.prevent_default()
        self._start_send_worker(force=True)

    def _start_send_worker(self, *, force: bool) -> Worker[None]:
        """Run one send in a worker so the modal never waits on the queue.

        Args:
            force (bool): True sends the row forced.

        Returns:
            Worker[None]: The started worker.
        """
        return self.run_worker(self.send_draft(force=force), group=_SEND_WORKER_GROUP, exit_on_error=False)

    async def send_draft(self, *, force: bool) -> None:
        """Send the input's text to the target through the adapter.

        A ``RecipientClosedError`` marks the composer finished (108.3 §6); any
        other queue failure is logged and keeps the draft for a retry.

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
        except Exception as exc:  # noqa: BLE001 — a broken queue must not kill the modal
            log_warning(msg=f"agent composer send failed: {exc}")
            return
        input_widget.value = ""
        await self.refresh_delivery_state()

    def _mark_finished(self) -> None:
        """Disable the input and show the fixed finished notice; rows stay visible."""
        if self._finished:
            return
        self._finished = True
        self.add_class("-agent-finished")
        input_widget: Input = self.query_one("#agent-composer-input", Input)
        input_widget.disabled = True
        input_widget.placeholder = AGENT_FINISHED_NOTICE
        self.query_one(".agent-composer-status", Static).update(content=AGENT_FINISHED_NOTICE)
