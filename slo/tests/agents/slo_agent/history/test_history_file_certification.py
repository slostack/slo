"""R1 proofs for successful re-fsync certification in both real history adapters.

The flat owner writes and flushes a complete JSONL line before asking its
injected certification collaborator to fsync the exact descriptor. A retry of
the same canonical event must certify the existing raw file again; readable
bytes alone are not durable evidence. Only a later successful certification
may repair metadata and return the original persisted event.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from src.agents.slo_agent.history.dao import SessionHistoryEventDAO
from src.agents.slo_agent.history.filesystem_store import (
    FileCertification,
    FilesystemSessionHistoryStore,
)
from src.agents.slo_agent.history.message_contract_reconciler import (
    CooperativeYieldSettlementError,
)
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.tool_execution.dao import ToolGroupMetadataDAO
from tests.agents.slo_agent.messaging.test_history_cooperative_append import (
    _group,
    _raw_lines,
    _tool_event,
    _uuid,
)

Store = FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore


class _ScriptedCertifier(FileCertification):
    """Real storage barrier failing a bounded number of certifications first."""

    def __init__(self, *, failures: int) -> None:
        """Record the failure budget and certification calls."""
        self.failures: int = failures
        self.certified_paths: list[Path] = []

    def certify(self, *, path: Path) -> None:
        """Record the exact file, fail while the budget remains, then fsync."""
        self.certified_paths.append(path)
        if self.failures > 0:
            self.failures -= 1
            raise OSError("injected fsync certification failure")
        super().certify(path=path)


def _store_with_certifier(*, tmp_path: Path, tree: bool, certifier: _ScriptedCertifier) -> Store:
    """Build a real adapter under the test-owned root with the injected port."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    return (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path, file_certification=certifier)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path, file_certification=certifier)
    )


class _ReplyLosingFlatStore(FilesystemSessionHistoryStore):
    """Small public-port subclass that withholds the reply after real persistence."""

    def __init__(self, *, root: Optional[Path] = None) -> None:
        """Initialise the flat owner with one unknown-reply budget."""
        super().__init__(root=root)
        self.reply_loss_budget: int = 1

    async def append_cooperative_event_once(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
        """Persist first, then raise once as if the reply was lost."""
        persisted: SessionHistoryEventDAO = await super().append_cooperative_event_once(event=event)
        if self.reply_loss_budget > 0:
            self.reply_loss_budget -= 1
            raise CooperativeYieldSettlementError()
        return persisted


class _ReplyLosingTreeStore(TreeBasedFilesystemSessionHistoryStore):
    """Tree analogue of the small public-port reply-loss subclass."""

    def __init__(self, *, root: Optional[Path] = None) -> None:
        """Initialise the tree owner with one unknown-reply budget."""
        super().__init__(root=root)
        self.reply_loss_budget: int = 1

    async def append_cooperative_event_once(self, *, event: SessionHistoryEventDAO) -> SessionHistoryEventDAO:
        """Persist first, then raise once as if the reply was lost."""
        persisted: SessionHistoryEventDAO = await super().append_cooperative_event_once(event=event)
        if self.reply_loss_budget > 0:
            self.reply_loss_budget -= 1
            raise CooperativeYieldSettlementError()
        return persisted


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_equal_event_retry_requires_successful_refsync_certification(
    tmp_path: Path, tree: bool
) -> None:
    """Fail at write and retry certification, then return the original durable event."""
    certifier: _ScriptedCertifier = _ScriptedCertifier(failures=2)
    store: Store = _store_with_certifier(tmp_path=tmp_path, tree=tree, certifier=certifier)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=5, call_ids=("call-a", "call-b"))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)

    lines: list[str] = _raw_lines(tmp_path=tmp_path, session_id=session_id)
    assert len(lines) == 1
    written: SessionHistoryEventDAO = SessionHistoryEventDAO.model_validate_json(lines[0])
    assert written.sequence == 1
    assert written.application_sha256() == event.application_sha256()

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1

    recovered: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)

    assert recovered.event_id == event.event_id
    assert recovered.sequence == 1
    assert recovered.recorded_at == event.recorded_at
    assert recovered.application_sha256() == event.application_sha256()
    final_lines: list[str] = _raw_lines(tmp_path=tmp_path, session_id=session_id)
    assert final_lines == lines
    assert SessionHistoryEventDAO.model_validate_json(final_lines[0]).application_sha256() == (
        event.application_sha256()
    )
    events_path: Path = tmp_path / session_id / "events.jsonl"
    assert certifier.certified_paths == [events_path, events_path, events_path]
    assert (await store.read_metadata(session_id=session_id)).latest_sequence == 1


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_unknown_reply_after_successful_persist_dedups_on_retry(tmp_path: Path, tree: bool) -> None:
    """A lost reply after real persistence is followed by exact raw deduplication."""
    store: Store = _ReplyLosingTreeStore(root=tmp_path) if tree else _ReplyLosingFlatStore(root=tmp_path)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=6, call_ids=("call-a",))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1

    recovered: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)

    assert recovered.event_id == event.event_id
    assert recovered.sequence == 1
    assert recovered.recorded_at == event.recorded_at
    assert recovered.application_sha256() == event.application_sha256()
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1


@pytest.mark.parametrize(argnames="tree", argvalues=[False, True])
async def test_equal_event_retry_repairs_stale_metadata_only_after_certification(
    tmp_path: Path, tree: bool
) -> None:
    """A stale high-water marker is repaired from raw only through the certified retry."""
    certifier: _ScriptedCertifier = _ScriptedCertifier(failures=2)
    store: Store = _store_with_certifier(tmp_path=tmp_path, tree=tree, certifier=certifier)
    session_id: str = _uuid()
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")
    group: ToolGroupMetadataDAO = _group(attempt_turn_id=_uuid(), iteration=7, call_ids=("call-a",))
    event: SessionHistoryEventDAO = _tool_event(
        session_id=session_id, group=group, kind="tool_call", call_id="call-a"
    )

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)
    lines: list[str] = _raw_lines(tmp_path=tmp_path, session_id=session_id)
    assert len(lines) == 1
    written: SessionHistoryEventDAO = SessionHistoryEventDAO.model_validate_json(lines[0])
    assert written.event_id == event.event_id
    assert written.sequence == 1
    assert written.recorded_at == event.recorded_at
    assert written.application_sha256() == event.application_sha256()
    assert (await store.read_metadata(session_id=session_id)).latest_sequence == 0

    with pytest.raises(expected_exception=CooperativeYieldSettlementError):
        await store.append_cooperative_event_once(event=event)
    assert len(_raw_lines(tmp_path=tmp_path, session_id=session_id)) == 1
    assert (await store.read_metadata(session_id=session_id)).latest_sequence == 0

    recovered: SessionHistoryEventDAO = await store.append_cooperative_event_once(event=event)
    assert recovered.event_id == event.event_id
    assert recovered.sequence == 1
    assert recovered.recorded_at == event.recorded_at
    assert recovered.application_sha256() == event.application_sha256()
    final_lines: list[str] = _raw_lines(tmp_path=tmp_path, session_id=session_id)
    assert final_lines == lines
    assert SessionHistoryEventDAO.model_validate_json(final_lines[0]).event_id == event.event_id
    assert SessionHistoryEventDAO.model_validate_json(final_lines[0]).sequence == 1
    assert SessionHistoryEventDAO.model_validate_json(final_lines[0]).application_sha256() == (
        event.application_sha256()
    )
    events_path: Path = tmp_path / session_id / "events.jsonl"
    assert certifier.certified_paths == [events_path, events_path, events_path]
    assert (await store.read_metadata(session_id=session_id)).latest_sequence == 1
