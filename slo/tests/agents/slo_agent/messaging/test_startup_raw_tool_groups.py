"""Startup raw marked-group validation under the ownership/history barrier (96.a.2 §6.3.1).

The proofs use real sessions, real SQLite messaging state and both real history
adapters. One-method subclasses configure the existing ``application_evidence``
page seam or make an early projection impossible, so a missing startup barrier
fails instead of being hidden by the later context projection.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.dao import (
    MessageHistoryEvidenceDAO,
    SessionHistoryEventDAO,
)
from src.agents.slo_agent.history.filesystem_store import FilesystemSessionHistoryStore
from src.agents.slo_agent.history.message_contract_reconciler import (
    UnsettledToolGroupError,
)
from src.agents.slo_agent.history.tree_store import TreeBasedFilesystemSessionHistoryStore
from src.agents.slo_agent.messaging.client import LocalSessionMessagingClient
from src.agents.slo_agent.sessions.dao import SessionConfigDAO
from src.agents.slo_agent.sessions.service import SloAgentSession
from tests.agents.slo_agent.history.test_projector_tool_groups import (
    _group,
    _no_start,
    _opening,
    _result,
    _terminal,
    _user_message,
)

Store = FilesystemSessionHistoryStore | TreeBasedFilesystemSessionHistoryStore


class _RejectEarlyProjectionMixin:
    """Fail if startup reaches projection before raw group validation."""

    async def load_events(self, *, session_id: str) -> list[SessionHistoryEventDAO]:
        """Refuse the projection read that the startup barrier must precede."""
        raise AssertionError("startup projected history before validating raw tool groups")


class _FlatBarrierStore(_RejectEarlyProjectionMixin, FilesystemSessionHistoryStore):
    """Real flat adapter with the early-projection guard."""


class _TreeBarrierStore(_RejectEarlyProjectionMixin, TreeBasedFilesystemSessionHistoryStore):
    """Real tree adapter with the early-projection guard."""


class _OneEventPageMixin(FilesystemSessionHistoryStore):
    """Force the real adapter's existing configurable page seam to one event."""

    async def application_evidence(
        self, *, session_id: str, after_sequence: int = 0, limit: int = 256
    ) -> MessageHistoryEvidenceDAO:
        """Read through the real owner with the smallest legal page."""
        return await super().application_evidence(
            session_id=session_id, after_sequence=after_sequence, limit=1
        )


class _FlatOneEventPageStore(_OneEventPageMixin, FilesystemSessionHistoryStore):
    """Real flat adapter paged one event at a time."""


class _TreeOneEventPageStore(_OneEventPageMixin, TreeBasedFilesystemSessionHistoryStore):
    """Real tree adapter paged one event at a time."""


def _store(*, tmp_path: Path, tree: bool, variant: str) -> Store:
    """Build one real adapter variant under the test-owned temporary root."""
    assert tmp_path.resolve().is_relative_to(tmp_path.resolve())
    if variant == "barrier":
        return _TreeBarrierStore(root=tmp_path) if tree else _FlatBarrierStore(root=tmp_path)
    if variant == "one-page":
        return _TreeOneEventPageStore(root=tmp_path) if tree else _FlatOneEventPageStore(root=tmp_path)
    return (
        TreeBasedFilesystemSessionHistoryStore(root=tmp_path)
        if tree
        else FilesystemSessionHistoryStore(root=tmp_path)
    )


def _session(*, tmp_path: Path, root: Path, store: Store, session_id: str) -> SloAgentSession:
    """Build the real session with a contained history root and SQLite target."""
    return SloAgentSession(
        workdir=tmp_path,
        session_id=session_id,
        enable_history=True,
        config=SessionConfigDAO(
            workdir=tmp_path, history_root=root, session_id=session_id, model_name="gpt-5.4"
        ),
        history_store=store,
    )


async def _prepare(*, store: Store, tmp_path: Path, session_id: str) -> None:
    """Create the real session directory before appending raw evidence."""
    await store.ensure_session(session_id=session_id, workdir=tmp_path, model_name="gpt-5.4")


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_startup_rejects_unresolved_opening_before_projection(*, tmp_path: Path, tree: bool) -> None:
    """An opening with no result or disposition blocks startup, even in an incomplete turn."""
    root: Path = tmp_path / "history"
    store: Store = _store(tmp_path=root, tree=tree, variant="barrier")
    session_id: str = str(uuid4())
    await _prepare(store=store, tmp_path=tmp_path, session_id=session_id)
    turn_id: str = str(uuid4())
    group = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))

    session: SloAgentSession = _session(tmp_path=tmp_path, root=root, store=store, session_id=session_id)
    try:
        with pytest.raises(UnsettledToolGroupError):
            await session.start_messaging()
    finally:
        await session.close_messaging()
    assert session.is_messaging_ready is False


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_startup_rejects_unknown_group_metadata_before_projection(
    *, tmp_path: Path, tree: bool
) -> None:
    """An unknown marked schema fails startup instead of being healed or ignored."""
    root: Path = tmp_path / "history"
    store: Store = _store(tmp_path=root, tree=tree, variant="barrier")
    session_id: str = str(uuid4())
    await _prepare(store=store, tmp_path=tmp_path, session_id=session_id)
    turn_id: str = str(uuid4())
    group = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    unknown_metadata: dict[str, object] = group.model_dump(mode="json")
    unknown_metadata["schema_version"] = 2
    opening: SessionHistoryEventDAO = _opening(session_id=session_id, group=group, call_id="a")
    unknown: SessionHistoryEventDAO = opening.model_copy(
        update={
            "payload": opening.payload.model_copy(update={"metadata": {"tool_group_v1": unknown_metadata}})
        }
    )
    await store.append_event(event=unknown)
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    session: SloAgentSession = _session(tmp_path=tmp_path, root=root, store=store, session_id=session_id)
    try:
        with pytest.raises(UnsettledToolGroupError):
            await session.start_messaging()
    finally:
        await session.close_messaging()
    assert session.is_messaging_ready is False


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_startup_allows_affirmative_no_start_and_exposes_real_client(
    *, tmp_path: Path, tree: bool
) -> None:
    """A first full opening plus a no-start marker permits readiness and client composition."""
    root: Path = tmp_path / "history"
    store: Store = _store(tmp_path=root, tree=tree, variant="normal")
    session_id: str = str(uuid4())
    await _prepare(store=store, tmp_path=tmp_path, session_id=session_id)
    turn_id: str = str(uuid4())
    group = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a",))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_no_start(session_id=session_id, group=group))

    session: SloAgentSession = _session(tmp_path=tmp_path, root=root, store=store, session_id=session_id)
    await session.start_messaging()
    client: LocalSessionMessagingClient = LocalSessionMessagingClient(
        session=session,
        target=session.messaging_target,
        principal=session.messaging_owner_principal,
    )
    try:
        assert session.is_messaging_ready is True
        assert client is not None
    finally:
        await client.close()
        await session.close_messaging()


@pytest.mark.asyncio
@pytest.mark.parametrize("tree", [False, True])
async def test_startup_carries_settled_group_across_every_evidence_page(
    *, tmp_path: Path, tree: bool
) -> None:
    """A group split over one-event pages is assembled and validated once at startup."""
    root: Path = tmp_path / "history"
    store: Store = _store(tmp_path=root, tree=tree, variant="one-page")
    session_id: str = str(uuid4())
    await _prepare(store=store, tmp_path=tmp_path, session_id=session_id)
    turn_id: str = str(uuid4())
    group = _group(attempt_turn_id=turn_id, iteration=1, call_ids=("a", "b"))
    await store.append_event(event=_user_message(session_id=session_id, turn_id=turn_id, content="go"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_opening(session_id=session_id, group=group, call_id="b"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="a"))
    await store.append_cooperative_event_once(event=_result(session_id=session_id, group=group, call_id="b"))
    await store.append_event(event=_terminal(session_id=session_id, turn_id=turn_id))

    session: SloAgentSession = _session(tmp_path=tmp_path, root=root, store=store, session_id=session_id)
    try:
        await session.start_messaging()
        assert session.is_messaging_ready is True
    finally:
        await session.close_messaging()
