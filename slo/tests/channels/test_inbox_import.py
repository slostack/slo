"""Unit/integration tests for the one-time legacy inbox import (108.6 I3).

The fixtures are raw JSON files in the retired ``inbox/{pending,claimed,done}``
layout (the old package is deleted in this slice), imported into a real
SQLite-WAL ``channels.db`` through the real ``ChannelGateway``. No internal
collaborator is patched.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import UUID, uuid4

from src.agents.slo_agent.channel_delivery.poller import channel_participant_id_for_session
from src.channels.dao import ChannelMessageDAO, ParticipantDAO
from src.channels.gateway import ChannelGateway
from src.channels.inbox_import import InboxImporter, InboxImportReportDAO
from src.channels.repository import ChannelRepository

_SESSION_ID: str = "5a4b3c2d-1e0f-4a9b-8c7d-6e5f4a3b2c1d"
_ORCHESTRATOR_SESSION_ID: str = "9e8d7c6b-5a4f-4e3d-9c2b-1a0f9e8d7c6b"
_BASE_TIME: datetime = datetime(year=2026, month=11, day=20, hour=9, tzinfo=timezone.utc)


def _legacy_item(
    *,
    minute: int,
    kind: str,
    delivery_mode: str,
    text: str,
    schedule_id: str = "sched-repo-watch",
    title: Optional[str] = "Repo Watch",
    coalesce_key: Optional[str] = None,
    payload: Optional[dict[str, object]] = None,
) -> dict[str, object]:
    """Build one inbox message in the retired ``SessionInboxMessageDAO`` JSON shape.

    Args:
        minute (int): Minutes after the base time; orders the files.
        kind (str): Legacy inbox kind.
        delivery_mode (str): Legacy delivery mode.
        text (str): Display or prompt text.
        schedule_id (str): Producing schedule (``workflow:<id>`` for workflows).
        title (Optional[str]): Display title (the schedule name for schedules).
        coalesce_key (Optional[str]): Legacy coalescing key.
        payload (Optional[dict[str, object]]): Opaque legacy payload.

    Returns:
        dict[str, object]: JSON-ready legacy message.
    """
    return {
        "message_id": str(uuid4()),
        "session_id": _SESSION_ID,
        "schedule_id": schedule_id,
        "run_id": str(uuid4()),
        "kind": kind,
        "priority": "normal",
        "delivery_mode": delivery_mode,
        "coalesce_key": coalesce_key,
        "created_at": (_BASE_TIME + timedelta(minutes=minute)).isoformat(),
        "title": title,
        "text": text,
        "payload": payload or {},
    }


def _write_lane_file(*, session_dir: Path, lane: str, item: dict[str, object]) -> Path:
    """Write one legacy item into ``inbox/<lane>/`` with the old sortable filename.

    Args:
        session_dir (Path): ``<history>/<session id>``.
        lane (str): ``pending``, ``claimed`` or ``done``.
        item (dict[str, object]): Legacy message JSON.

    Returns:
        Path: The written file.
    """
    created_at: datetime = datetime.fromisoformat(str(item["created_at"]))
    lane_dir: Path = session_dir / "inbox" / lane
    lane_dir.mkdir(parents=True, exist_ok=True)
    path: Path = lane_dir / f"{created_at.strftime('%Y%m%dT%H%M%S.%fZ')}-{item['message_id']}.json"
    path.write_text(json.dumps(item, indent=2), encoding="utf-8")
    return path


def _workflow_payload() -> dict[str, object]:
    """Return the identity pair the retired workflow notifier stored in every payload."""
    return {"workflow_id": "wf-12", "orchestrator_session_id": _ORCHESTRATOR_SESSION_ID}


async def _open_gateway_with_agent(*, tmp_path: Path) -> ChannelGateway:
    """Open a real gateway and register the receiving session's agent (as its poller does).

    Args:
        tmp_path (Path): Test-owned directory holding ``channels.db``.

    Returns:
        ChannelGateway: Open gateway with the agent participant open.
    """
    gateway: ChannelGateway = ChannelGateway(repository=ChannelRepository(db_path=tmp_path / "channels.db"))
    await gateway.open()
    await gateway.register_agent(session_id=UUID(_SESSION_ID), name="slo 5a4b3c2d", durable_inbox=True)
    return gateway


def _migrated_dirs(*, session_dir: Path) -> list[Path]:
    """Return the renamed ``inbox.migrated-<ts>`` directories.

    Args:
        session_dir (Path): ``<history>/<session id>``.

    Returns:
        list[Path]: Renamed inbox directories.
    """
    return sorted(session_dir.glob("inbox.migrated-*"))


class TestInboxImporter:
    """Pending and claimed items become channel rows once; done items stay history."""

    async def test_pending_claimed_and_done_fixtures_import_with_mapped_types_and_senders(
        self, tmp_path: Path
    ) -> None:
        """I3: every delivery mode maps to its channel type and sender; done is not re-delivered."""
        session_dir: Path = tmp_path / "history" / _SESSION_ID
        scheduled_prompt = _legacy_item(
            minute=1,
            kind="scheduled_prompt",
            delivery_mode="chat_turn",
            text="Check CI and summarise new failures.",
            coalesce_key="repo-watch",
        )
        scheduled_notice = _legacy_item(
            minute=2, kind="system_notice", delivery_mode="ui_notice", text="disk 91%"
        )
        scheduled_note = _legacy_item(
            minute=3, kind="monitor_update", delivery_mode="transcript_note", text="build green"
        )
        workflow_note = _legacy_item(
            minute=0,
            kind="workflow_phase_update",
            delivery_mode="context_note",
            text="[workflow wf-12] phase 1: review done",
            schedule_id="workflow:wf-12",
            title="wf-12 phase 1",
            payload=_workflow_payload(),
        )
        workflow_completed = _legacy_item(
            minute=4,
            kind="workflow_completed",
            delivery_mode="chat_turn",
            text="Workflow wf-12 completed. Present this synthesis to the user.",
            schedule_id="workflow:wf-12",
            title="wf-12 completed",
            payload=_workflow_payload(),
        )
        already_done = _legacy_item(
            minute=-5, kind="scheduled_prompt", delivery_mode="chat_turn", text="old run"
        )
        for item in (scheduled_prompt, scheduled_notice, scheduled_note):
            _write_lane_file(session_dir=session_dir, lane="pending", item=item)
        for item in (workflow_note, workflow_completed):
            _write_lane_file(session_dir=session_dir, lane="claimed", item=item)
        done_file: Path = _write_lane_file(session_dir=session_dir, lane="done", item=already_done)
        gateway: ChannelGateway = await _open_gateway_with_agent(tmp_path=tmp_path)

        report: InboxImportReportDAO = await InboxImporter(
            session_dir=session_dir, gateway=gateway, agent_id=UUID(_SESSION_ID)
        ).run()
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
        done_row: Optional[ChannelMessageDAO] = await gateway.get(
            message_id=UUID(str(already_done["message_id"]))
        )
        orchestrator: Optional[ParticipantDAO] = await gateway.get_participant(
            participant_id=channel_participant_id_for_session(session_id=_ORCHESTRATOR_SESSION_ID)
        )
        schedule_sender: Optional[ParticipantDAO] = await gateway.get_participant(
            participant_id=next(
                row.sender_id for row in pending if str(row.id) == str(scheduled_prompt["message_id"])
            )
        )
        await gateway.close()

        assert report == InboxImportReportDAO(imported=5, duplicates=0, unreadable=[])
        by_id: dict[str, ChannelMessageDAO] = {str(row.id): row for row in pending}
        assert set(by_id) == {
            str(item["message_id"])
            for item in (
                scheduled_prompt,
                scheduled_notice,
                scheduled_note,
                workflow_note,
                workflow_completed,
            )
        }
        assert [str(row.id) for row in sorted(pending, key=lambda row: row.message_index)] == [
            str(item["message_id"])
            for item in (
                workflow_note,
                scheduled_prompt,
                scheduled_notice,
                scheduled_note,
                workflow_completed,
            )
        ]
        prompt_row: ChannelMessageDAO = by_id[str(scheduled_prompt["message_id"])]
        assert prompt_row.message_type == "prompt"
        assert prompt_row.message_contents == "Check CI and summarise new failures."
        assert prompt_row.sender_name == "scheduler Repo Watch"
        assert schedule_sender is not None and schedule_sender.kind == "system"
        assert schedule_sender.external_ref == "sched-repo-watch"
        assert prompt_row.coalesce_key == "repo-watch"
        assert by_id[str(scheduled_notice["message_id"])].message_type == "notice"
        assert by_id[str(scheduled_note["message_id"])].message_type == "notice"
        assert "disk 91%" in by_id[str(scheduled_notice["message_id"])].message_contents
        note_row: ChannelMessageDAO = by_id[str(workflow_note["message_id"])]
        assert note_row.message_type == "note"
        assert note_row.message_contents.startswith("[workflow wf-12]")
        assert note_row.sender_id == channel_participant_id_for_session(session_id=_ORCHESTRATOR_SESSION_ID)
        assert note_row.sender_name == "orchestrator wf-12"
        completed_row: ChannelMessageDAO = by_id[str(workflow_completed["message_id"])]
        assert completed_row.message_type == "prompt"
        assert completed_row.sender_id == note_row.sender_id
        assert all(row.forced_at is None for row in pending)
        assert done_row is None
        assert orchestrator is not None and orchestrator.kind == "agent" and orchestrator.status == "closed"
        assert not (session_dir / "inbox").exists()
        migrated: list[Path] = _migrated_dirs(session_dir=session_dir)
        assert len(migrated) == 1
        assert (migrated[0] / "done" / done_file.name).is_file()
        assert sorted(path.name for path in (migrated[0] / "claimed").glob("*.json")) != []

    async def test_forced_rerun_after_a_crash_before_rename_creates_no_duplicates(
        self, tmp_path: Path
    ) -> None:
        """I3: rows keep the inbox ``message_id``, so a re-run counts duplicates and inserts nothing."""
        session_dir: Path = tmp_path / "history" / _SESSION_ID
        items: list[dict[str, object]] = [
            _legacy_item(
                minute=index, kind="scheduled_prompt", delivery_mode="chat_turn", text=f"run {index}"
            )
            for index in range(3)
        ]
        _write_lane_file(session_dir=session_dir, lane="pending", item=items[0])
        _write_lane_file(session_dir=session_dir, lane="claimed", item=items[1])
        _write_lane_file(session_dir=session_dir, lane="pending", item=items[2])
        crash_copy: Path = tmp_path / "inbox-before-rename"
        shutil.copytree(src=session_dir / "inbox", dst=crash_copy)
        gateway: ChannelGateway = await _open_gateway_with_agent(tmp_path=tmp_path)
        importer: InboxImporter = InboxImporter(
            session_dir=session_dir, gateway=gateway, agent_id=UUID(_SESSION_ID)
        )

        first: InboxImportReportDAO = await importer.run()
        shutil.copytree(src=crash_copy, dst=session_dir / "inbox")
        second: InboxImportReportDAO = await importer.run()
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
        await gateway.close()

        assert first == InboxImportReportDAO(imported=3, duplicates=0, unreadable=[])
        assert second == InboxImportReportDAO(imported=0, duplicates=3, unreadable=[])
        assert sorted(str(row.id) for row in pending) == sorted(str(item["message_id"]) for item in items)
        assert not (session_dir / "inbox").exists()
        assert len(_migrated_dirs(session_dir=session_dir)) == 2

    async def test_an_accepted_import_is_not_redelivered_by_a_rerun(self, tmp_path: Path) -> None:
        """A row the agent already took stays accepted; the re-run never revives it as pending."""
        session_dir: Path = tmp_path / "history" / _SESSION_ID
        item = _legacy_item(minute=0, kind="scheduled_prompt", delivery_mode="chat_turn", text="run once")
        _write_lane_file(session_dir=session_dir, lane="claimed", item=item)
        crash_copy: Path = tmp_path / "inbox-before-rename"
        shutil.copytree(src=session_dir / "inbox", dst=crash_copy)
        gateway: ChannelGateway = await _open_gateway_with_agent(tmp_path=tmp_path)
        importer: InboxImporter = InboxImporter(
            session_dir=session_dir, gateway=gateway, agent_id=UUID(_SESSION_ID)
        )

        await importer.run()
        assert await gateway.accept(message_id=UUID(str(item["message_id"]))) is True
        shutil.copytree(src=crash_copy, dst=session_dir / "inbox")
        rerun: InboxImportReportDAO = await importer.run()
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
        await gateway.close()

        assert rerun.duplicates == 1 and rerun.imported == 0
        assert pending == []

    async def test_unreadable_files_stay_in_place_and_are_noticed_once(self, tmp_path: Path) -> None:
        """Unparseable files are reported, left in ``inbox/``, and produce exactly one notice row."""
        session_dir: Path = tmp_path / "history" / _SESSION_ID
        readable = _legacy_item(minute=0, kind="scheduled_prompt", delivery_mode="chat_turn", text="valid")
        _write_lane_file(session_dir=session_dir, lane="pending", item=readable)
        broken: Path = session_dir / "inbox" / "pending" / "20261120T090500.000000Z-broken.json"
        broken.write_text("{not json", encoding="utf-8")
        gateway: ChannelGateway = await _open_gateway_with_agent(tmp_path=tmp_path)
        importer: InboxImporter = InboxImporter(
            session_dir=session_dir, gateway=gateway, agent_id=UUID(_SESSION_ID)
        )

        first: InboxImportReportDAO = await importer.run()
        second: InboxImportReportDAO = await importer.run()
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
        await gateway.close()

        assert first == InboxImportReportDAO(imported=1, duplicates=0, unreadable=[broken.name])
        assert second == InboxImportReportDAO(imported=0, duplicates=1, unreadable=[broken.name])
        assert broken.is_file()
        assert (session_dir / "inbox").is_dir()
        assert _migrated_dirs(session_dir=session_dir) == []
        notices: list[ChannelMessageDAO] = [row for row in pending if row.message_type == "notice"]
        assert len(notices) == 1
        assert broken.name in notices[0].message_contents
        assert [row.message_type for row in pending if row.message_type != "notice"] == ["prompt"]

    async def test_session_without_an_inbox_is_a_no_op(self, tmp_path: Path) -> None:
        """A session that never had a file inbox imports nothing and creates nothing."""
        session_dir: Path = tmp_path / "history" / _SESSION_ID
        session_dir.mkdir(parents=True)
        gateway: ChannelGateway = await _open_gateway_with_agent(tmp_path=tmp_path)

        report: InboxImportReportDAO = await InboxImporter(
            session_dir=session_dir, gateway=gateway, agent_id=UUID(_SESSION_ID)
        ).run()
        pending: list[ChannelMessageDAO] = await gateway.pending_inbound(recipient_id=UUID(_SESSION_ID))
        await gateway.close()

        assert report == InboxImportReportDAO(imported=0, duplicates=0, unreadable=[])
        assert pending == []
        assert sorted(path.name for path in session_dir.iterdir()) == []

    async def test_a_live_orchestrator_is_used_as_sender_and_stays_open(self, tmp_path: Path) -> None:
        """A workflow item from an orchestrator that is still registered keeps that participant open."""
        session_dir: Path = tmp_path / "history" / _SESSION_ID
        item = _legacy_item(
            minute=0,
            kind="workflow_started",
            delivery_mode="context_note",
            text="started — orchestrator session x",
            schedule_id="workflow:wf-12",
            payload=_workflow_payload(),
        )
        _write_lane_file(session_dir=session_dir, lane="pending", item=item)
        gateway: ChannelGateway = await _open_gateway_with_agent(tmp_path=tmp_path)
        orchestrator_id: UUID = channel_participant_id_for_session(session_id=_ORCHESTRATOR_SESSION_ID)
        await gateway.register_agent(session_id=orchestrator_id, name="orchestrator wf-12 (live)")

        report: InboxImportReportDAO = await InboxImporter(
            session_dir=session_dir, gateway=gateway, agent_id=UUID(_SESSION_ID)
        ).run()
        row: Optional[ChannelMessageDAO] = await gateway.get(message_id=UUID(str(item["message_id"])))
        orchestrator: Optional[ParticipantDAO] = await gateway.get_participant(participant_id=orchestrator_id)
        await gateway.close()

        assert report.imported == 1
        assert row is not None and row.sender_id == orchestrator_id
        assert row.message_contents == "[workflow wf-12] started — orchestrator session x"
        assert orchestrator is not None and orchestrator.status == "open"
        assert orchestrator.name == "orchestrator wf-12 (live)"
