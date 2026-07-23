"""Tests for ``WorkflowNotifier`` (spec 57.a.3)."""

from __future__ import annotations

from pathlib import Path

from src.agents.slo_agent.history.inbox.dao import SessionInboxMessageDAO
from src.agents.slo_agent.history.inbox.store import SessionInboxStore
from src.agents.slo_agent.orchestrator.notifier import WorkflowNotifier

_TARGET_SESSION_ID: str = "tui-session-1"
_ORCH_SESSION_ID: str = "orch-session-1"
_WORKFLOW_ID: str = "wf-3f2a"


class _ExplodingInboxStore:
    """Inbox store stand-in whose every enqueue raises."""

    def __init__(self) -> None:
        """Track how often the enqueue was attempted."""
        self.enqueue_attempts: int = 0

    async def enqueue(self, *, message: SessionInboxMessageDAO) -> None:
        """Raise unconditionally.

        Args:
            message (SessionInboxMessageDAO): Ignored.

        Raises:
            OSError: Always.
        """
        self.enqueue_attempts += 1
        raise OSError("inbox unavailable")


def _build_notifier(
    *,
    tmp_path: Path,
    store: SessionInboxStore | _ExplodingInboxStore | None = None,
) -> tuple[WorkflowNotifier, SessionInboxStore]:
    """Build a notifier wired to a tmp-path inbox store.

    Args:
        tmp_path (Path): Pytest tmp path.
        store: Optional store override.

    Returns:
        tuple[WorkflowNotifier, SessionInboxStore]: Notifier and its store.
    """
    inbox_store: SessionInboxStore | _ExplodingInboxStore = (
        store if store is not None else SessionInboxStore(history_root=tmp_path / "history")
    )
    notifier: WorkflowNotifier = WorkflowNotifier(
        target_session_id=_TARGET_SESSION_ID,
        orchestrator_session_id=_ORCH_SESSION_ID,
        workflow_id=_WORKFLOW_ID,
        inbox_store=inbox_store,  # type: ignore[arg-type]
    )
    return notifier, inbox_store  # type: ignore[return-value]


async def _pending(*, store: SessionInboxStore) -> list[SessionInboxMessageDAO]:
    """Return the pending inbox items for the target session.

    Args:
        store (SessionInboxStore): Store under inspection.

    Returns:
        list[SessionInboxMessageDAO]: Pending messages oldest-first.
    """
    return await store.list_pending(session_id=_TARGET_SESSION_ID)


class TestStarted:
    """``started()`` — the workflow_started context note."""

    async def test_started_enqueues_context_note_with_identity_payload(
        self, tmp_path: Path
    ) -> None:
        """The started note is a context_note carrying the identity pair."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.started(brief_preview="run the code-test-review workflow")
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert len(pending) == 1
        message: SessionInboxMessageDAO = pending[0]
        assert message.kind == "workflow_started"
        assert message.delivery_mode == "context_note"
        assert message.session_id == _TARGET_SESSION_ID
        assert message.payload == {
            "workflow_id": _WORKFLOW_ID,
            "orchestrator_session_id": _ORCH_SESSION_ID,
        }
        assert "run the code-test-review workflow" in message.text

    async def test_started_truncates_long_brief_preview(self, tmp_path: Path) -> None:
        """Brief previews are clipped to 200 characters in the note text."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.started(brief_preview="x" * 500)
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert "x" * 200 in pending[0].text
        assert "x" * 201 not in pending[0].text


class TestPhaseUpdate:
    """``phase_update()`` — per-phase context notes."""

    async def test_phase_update_increments_phase_index(self, tmp_path: Path) -> None:
        """Two updates number themselves phase 1 and phase 2."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.phase_update(phase_summary="phase one done")
        await notifier.phase_update(phase_summary="phase two done")
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        assert len(pending) == 2
        assert "phase 1: phase one done" in pending[0].text
        assert "phase 2: phase two done" in pending[1].text
        assert all(message.kind == "workflow_phase_update" for message in pending)
        assert all(message.delivery_mode == "context_note" for message in pending)


class TestTerminal:
    """``completed()`` / ``failed()`` — the terminal chat_turn messages."""

    async def test_completed_enqueues_chat_turn_with_synthesis_and_json(
        self, tmp_path: Path
    ) -> None:
        """The completion message carries the synthesis and result JSON."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.completed(synthesis="all phases green", result_json='{"all_completed": true}')
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        message: SessionInboxMessageDAO = pending[0]
        assert message.kind == "workflow_completed"
        assert message.delivery_mode == "chat_turn"
        assert "all phases green" in message.text
        assert '{"all_completed": true}' in message.text

    async def test_failed_enqueues_chat_turn_with_error(self, tmp_path: Path) -> None:
        """The failure message carries the terminal error description."""
        notifier, store = _build_notifier(tmp_path=tmp_path)

        await notifier.failed(error="run_failed: model exhausted")
        pending: list[SessionInboxMessageDAO] = await _pending(store=store)

        message: SessionInboxMessageDAO = pending[0]
        assert message.kind == "workflow_failed"
        assert message.delivery_mode == "chat_turn"
        assert "run_failed: model exhausted" in message.text


class TestFailureSwallowing:
    """A notify failure must never propagate into the workflow."""

    async def test_enqueue_failure_is_swallowed(self, tmp_path: Path) -> None:
        """Every lifecycle method survives a store that always raises."""
        exploding: _ExplodingInboxStore = _ExplodingInboxStore()
        notifier, _ = _build_notifier(tmp_path=tmp_path, store=exploding)

        await notifier.started(brief_preview="b")
        await notifier.phase_update(phase_summary="p")
        await notifier.completed(synthesis="s", result_json="{}")
        await notifier.failed(error="e")

        assert exploding.enqueue_attempts == 4
