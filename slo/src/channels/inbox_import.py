"""One-time import of a session's retired file inbox into the channel queue (108.6).

Temporary migration module: remove it one release after 108.6. It reads the
old ``<history>/<session>/inbox/{pending,claimed}/*.json`` files with a
private copy of the retired field names, sends each item through the public
``ChannelGateway`` under its original ``message_id`` (so a crash part-way
through and a re-run create no duplicates), and renames the whole directory to
``inbox.migrated-<ts>`` once everything readable is in the queue. ``done``
items are history: they stay in the renamed directory and are never
re-delivered.

Mapping (108.6 §4):

| Inbox ``delivery_mode``           | Channel ``message_type`` |
|-----------------------------------|--------------------------|
| ``chat_turn``                     | ``prompt``               |
| ``context_note``                  | ``note``                 |
| ``ui_notice``, ``transcript_note``| ``notice``               |

Sender: the workflow's orchestrator agent when the payload names one
(``payload.orchestrator_session_id``), otherwise ``scheduler <schedule name>``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from config.logger import log_info, log_warning
from src.channels.dao import MessageType, NewMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway

__all__ = ["InboxImportReportDAO", "InboxImporter"]

_IMPORTED_LANES: tuple[str, ...] = ("claimed", "pending")
"""Lanes whose items are still owed to the session; ``claimed`` re-runs as pending, as the inbox re-claimed it."""

_MAX_CONTENTS_CHARS: int = 65_536
"""Channel ``message_contents`` limit (overview §3.1)."""

_NS_INBOX_IMPORT: UUID = uuid5(NAMESPACE_URL, "slo:channels:inbox-import")
"""Namespace for ids derived by the importer (non-UUID legacy ids, the unreadable notice)."""

_MESSAGE_TYPE_BY_DELIVERY_MODE: dict[str, MessageType] = {
    "chat_turn": "prompt",
    "context_note": "note",
    "ui_notice": "notice",
    "transcript_note": "notice",
}

_NOTICE_LABEL_BY_DELIVERY_MODE: dict[str, str] = {
    "ui_notice": "scheduled notice",
    "transcript_note": "scheduled update",
}
"""The transcript labels the retired TUI inbox handler rendered, kept for imported notices."""


class InboxImportReportDAO(BaseModel):
    """Outcome of one import run over a session's legacy inbox."""

    model_config = ConfigDict(frozen=True)

    imported: int = Field(description="Inbox items written to the channel queue.")
    duplicates: int = Field(description="Items skipped because their id was already in the queue.")
    unreadable: list[str] = Field(
        description="File names that could not be parsed; left in place and shown once as a notice."
    )


class _LegacyWorkflowIdentityDAO(BaseModel):
    """Workflow identity pair the retired notifier stored in every workflow payload."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str = Field(min_length=1, description="Workflow id, e.g. 'wf-12'.")
    orchestrator_session_id: str = Field(
        min_length=1, description="Session id of the orchestrator that sent it."
    )


class _LegacyInboxItemDAO(BaseModel):
    """Private copy of the retired ``SessionInboxMessageDAO`` fields the import needs."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    message_id: str = Field(min_length=1, description="Stable inbox message id; kept as the channel row id.")
    schedule_id: str = Field(description="Producing schedule, or 'workflow:<id>' for workflow items.")
    kind: str = Field(description="Retired inbox message kind, e.g. 'scheduled_prompt'.")
    delivery_mode: Literal["ui_notice", "transcript_note", "chat_turn", "context_note"] = Field(
        description="How the retired TUI surfaced the item; selects the channel message type."
    )
    coalesce_key: Optional[str] = Field(
        default=None, description="Key a newer pending item replaced older ones by."
    )
    created_at: datetime = Field(description="UTC time the item was written; orders the import.")
    title: Optional[str] = Field(default=None, description="Display title; the schedule name for schedules.")
    text: str = Field(min_length=1, description="Prompt or display text.")
    payload: dict[str, object] = Field(default_factory=dict, description="Opaque producer payload.")

    @property
    def channel_message_id(self) -> UUID:
        """Return the channel row id: the inbox id itself, or a stable derivation of it.

        Returns:
            UUID: The id every import run uses for this item.
        """
        try:
            return UUID(self.message_id)
        except ValueError:
            return uuid5(_NS_INBOX_IMPORT, f"message:{self.message_id}")

    @property
    def message_type(self) -> MessageType:
        """Return the channel message type for this item's delivery mode (108.6 §4).

        Returns:
            MessageType: ``prompt``, ``note`` or ``notice``.
        """
        return _MESSAGE_TYPE_BY_DELIVERY_MODE[self.delivery_mode]

    @property
    def workflow_identity(self) -> Optional[_LegacyWorkflowIdentityDAO]:
        """Return the workflow identity when the payload carries a valid pair.

        Returns:
            Optional[_LegacyWorkflowIdentityDAO]: The pair, or ``None`` for
                scheduler items and malformed workflow payloads.
        """
        try:
            return _LegacyWorkflowIdentityDAO.model_validate(self.payload)
        except ValidationError:
            return None

    @property
    def display_title(self) -> str:
        """Return the item's title, falling back to its kind as the retired handler did.

        Returns:
            str: Human-readable title.
        """
        return self.title or self.kind.replace("_", " ")

    def channel_contents(self) -> str:
        """Return the row contents, keeping each type's established presentation.

        Prompts run verbatim; notices keep the ``[scheduled notice|update]``
        transcript prefix; workflow notes keep the ``[workflow <id>]`` marker
        the receiving poller reads the workflow id from.

        Returns:
            str: Contents trimmed to the channel limit.
        """
        contents: str = self.text
        if self.message_type == "notice":
            contents = (
                f"[{_NOTICE_LABEL_BY_DELIVERY_MODE[self.delivery_mode]}] {self.display_title}: {self.text}"
            )
        identity: Optional[_LegacyWorkflowIdentityDAO] = self.workflow_identity
        if self.message_type == "note" and identity is not None and "[workflow " not in contents:
            contents = f"[workflow {identity.workflow_id}] {contents}"
        return contents[:_MAX_CONTENTS_CHARS]


class _LegacyInboxScanDAO(BaseModel):
    """Readable items and unreadable file names found in one inbox directory."""

    model_config = ConfigDict(frozen=True)

    items: list[_LegacyInboxItemDAO] = Field(description="Readable pending and claimed items, oldest first.")
    unreadable: list[str] = Field(description="File names that could not be parsed.")


class InboxImporter:
    """Imports one session's legacy file inbox into the channel queue, once.

    WHAT: Sends every readable ``pending`` and ``claimed`` item to the
        session's agent under its inbox id, then renames ``inbox/`` to
        ``inbox.migrated-<ts>/``. Unreadable files are left in place (the
        directory is then not renamed) and announced by one notice row.
    WHO: ``ChannelPoller.start`` for every session that has an on-disk
        history directory.
    WHEN: Before the poller's first poll; re-running is safe at any time.
    """

    def __init__(self, *, session_dir: Path, gateway: ChannelGateway, agent_id: UUID) -> None:
        """Bind the importer to one session directory and its agent participant.

        Args:
            session_dir (Path): ``<history root>/<session id>``.
            gateway (ChannelGateway): Open shared gateway; the caller owns it.
            agent_id (UUID): The receiving agent participant (already registered).
        """
        self._session_dir: Path = session_dir
        self._inbox_dir: Path = session_dir / "inbox"
        self._gateway: ChannelGateway = gateway
        self._agent_id: UUID = agent_id

    async def run(self) -> InboxImportReportDAO:
        """Import every owed inbox item, then retire the directory when nothing is left behind.

        Returns:
            InboxImportReportDAO: Counts of imported and duplicate items, and
                the unreadable file names.
        """
        if not self._inbox_dir.is_dir():
            return InboxImportReportDAO(imported=0, duplicates=0, unreadable=[])
        scan: _LegacyInboxScanDAO = await asyncio.to_thread(self._scan_inbox)
        imported: int = 0
        for item in scan.items:
            imported += 1 if await self._import_item(item=item) else 0
        report: InboxImportReportDAO = InboxImportReportDAO(
            imported=imported,
            duplicates=len(scan.items) - imported,
            unreadable=scan.unreadable,
        )
        if scan.unreadable:
            await self._notice_unreadable(unreadable=scan.unreadable)
        else:
            await asyncio.to_thread(self._retire_inbox_dir)
        log_info(
            msg="legacy_inbox_imported",
            imported=report.imported,
            duplicates=report.duplicates,
            unreadable=len(report.unreadable),
        )
        return report

    def _scan_inbox(self) -> _LegacyInboxScanDAO:
        """Read the owed lanes, oldest first, separating unreadable files.

        Returns:
            _LegacyInboxScanDAO: Readable items and unreadable file names.
        """
        items: list[tuple[datetime, str, _LegacyInboxItemDAO]] = []
        unreadable: list[str] = []
        for lane in _IMPORTED_LANES:
            for path in sorted((self._inbox_dir / lane).glob("*.json")):
                item: Optional[_LegacyInboxItemDAO] = self._read_item(path=path)
                if item is None:
                    unreadable.append(path.name)
                    continue
                items.append((item.created_at, path.name, item))
        items.sort(key=lambda entry: (entry[0], entry[1]))
        return _LegacyInboxScanDAO(items=[entry[2] for entry in items], unreadable=sorted(unreadable))

    @staticmethod
    def _read_item(*, path: Path) -> Optional[_LegacyInboxItemDAO]:
        """Parse one legacy inbox file.

        Args:
            path (Path): The JSON file.

        Returns:
            Optional[_LegacyInboxItemDAO]: The item, or ``None`` when the file
                cannot be read or does not have the retired shape.
        """
        try:
            return _LegacyInboxItemDAO.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, ValidationError):
            return None

    async def _import_item(self, *, item: _LegacyInboxItemDAO) -> bool:
        """Send one item unless its id is already in the queue.

        Args:
            item (_LegacyInboxItemDAO): Readable legacy item.

        Returns:
            bool: ``True`` when a row was written, ``False`` for a duplicate.
        """
        if await self._gateway.get(message_id=item.channel_message_id) is not None:
            return False
        identity: Optional[_LegacyWorkflowIdentityDAO] = item.workflow_identity
        if identity is None:
            await self._send_as_schedule(item=item)
            return True
        sender: ParticipantDAO = await self._registered_orchestrator(identity=identity)
        await self._gateway.send(
            new=NewMessageDAO(
                id=item.channel_message_id,
                sender_id=sender.id,
                recipient_id=self._agent_id,
                message_contents=item.channel_contents(),
                message_type=item.message_type,
                coalesce_key=item.coalesce_key,
            )
        )
        return True

    async def _send_as_schedule(self, *, item: _LegacyInboxItemDAO) -> None:
        """Send a scheduler item as its schedule's own sender, as a live fire would.

        Args:
            item (_LegacyInboxItemDAO): Scheduler-produced legacy item.
        """
        # Imported lazily: the scheduling runtime package imports the channel
        # poller, whose start hook imports this module.
        from src.scheduling.runtime.channel_sender import ScheduleChannelSender  # noqa: PLC0415

        await ScheduleChannelSender(gateway=self._gateway).send(
            schedule_id=item.schedule_id,
            schedule_name=item.title or item.schedule_id,
            target_session_id=str(self._agent_id),
            contents=item.channel_contents(),
            message_type=item.message_type,
            coalesce_key=item.coalesce_key,
            message_id=item.channel_message_id,
        )

    async def _registered_orchestrator(self, *, identity: _LegacyWorkflowIdentityDAO) -> ParticipantDAO:
        """Return the workflow's orchestrator participant, registering a finished one when unknown.

        A known participant is used as it is (a live orchestrator keeps its
        state). An unknown one belongs to a run from before channels: it is
        registered with the notifier's label and closed at once, so nobody can
        send to an orchestrator that no longer listens.

        Args:
            identity (_LegacyWorkflowIdentityDAO): Workflow id and orchestrator session id.

        Returns:
            ParticipantDAO: The orchestrator agent participant.
        """
        from src.agents.slo_agent.channel_delivery.poller import (
            channel_participant_id_for_session,
        )  # noqa: PLC0415

        orchestrator_id: UUID = channel_participant_id_for_session(
            session_id=identity.orchestrator_session_id
        )
        known: Optional[ParticipantDAO] = await self._gateway.get_participant(participant_id=orchestrator_id)
        if known is not None:
            return known
        registered: ParticipantDAO = await self._gateway.register_agent(
            session_id=orchestrator_id,
            name=f"orchestrator {identity.workflow_id}",
        )
        await self._gateway.close_agent(session_id=orchestrator_id, reason="recipient_closed")
        return registered

    async def _notice_unreadable(self, *, unreadable: list[str]) -> None:
        """Show the unreadable file names once, as a notice to the session's agent.

        The notice id is fixed per agent, so later runs never repeat it.

        Args:
            unreadable (list[str]): File names left in place.
        """
        log_warning(msg=f"legacy inbox import left {len(unreadable)} unreadable file(s) in {self._inbox_dir}")
        await self._gateway.send(
            new=NewMessageDAO(
                id=uuid5(_NS_INBOX_IMPORT, f"unreadable:{self._agent_id}"),
                sender_id=self._agent_id,
                recipient_id=self._agent_id,
                message_contents=(
                    f"Legacy inbox: {len(unreadable)} file(s) could not be imported and were left in "
                    f"{self._inbox_dir}: {', '.join(unreadable)}"
                )[:_MAX_CONTENTS_CHARS],
                message_type="notice",
            )
        )

    def _retire_inbox_dir(self) -> None:
        """Rename ``inbox/`` to a unique ``inbox.migrated-<ts>/`` once everything is imported.

        A failed rename is logged and left for the next run, which is safe
        because every item is then a duplicate.
        """
        stamp: str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        target: Path = self._session_dir / f"inbox.migrated-{stamp}"
        suffix: int = 1
        while target.exists():
            target = self._session_dir / f"inbox.migrated-{stamp}-{suffix}"
            suffix += 1
        try:
            self._inbox_dir.rename(target)
        except OSError as exc:
            log_warning(msg=f"legacy inbox rename failed; it will be retried: {exc}")
