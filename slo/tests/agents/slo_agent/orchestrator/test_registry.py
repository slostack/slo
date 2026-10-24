"""Tests for ``ProcessRegistry`` (sub-spec 01-sub-agents 01.c)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from src.agents.slo_agent.orchestrator.dao import (
    AttachedDispatchSnapshotDAO,
    DispatchIdentityDAO,
    StdoutCaptureIdentityDAO,
    SubAgentResultDAO,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.registry import (
    ExecutionConflictError,
    ProcessRegistry,
    StaleExecutionError,
)

_UNKNOWN_EXECUTION_ID: str = "00000000-0000-4000-8000-000000000000"
"""Canonical UUID that no registry allocates, used for unknown-session calls."""

_DISPATCH_ID: str = "11111111-1111-4111-8111-111111111111"
"""Dispatch begun by ``_registry`` so ordinary tests can register children."""

_SECOND_DISPATCH_ID: str = "22222222-2222-4222-8222-222222222222"
"""A later dispatch used by generation tests."""


def _registry(fleet_store: Optional[FleetStore] = None) -> ProcessRegistry:
    """Build a registry with ``_DISPATCH_ID`` already begun.

    ``register`` requires an admitted dispatch, so tests that exercise other
    behaviour start from one open batch, as the pool always does.

    Args:
        fleet_store (Optional[FleetStore]): Optional durable projection double.

    Returns:
        ProcessRegistry: Registry whose latest dispatch is ``_DISPATCH_ID``.
    """
    registry: ProcessRegistry = ProcessRegistry(fleet_store=fleet_store)
    registry.begin_dispatch(dispatch_id=_DISPATCH_ID)
    return registry


def _task(
    task_id: str = "t1",
    prompt: str = "Do something.",
) -> SubAgentTaskDAO:
    """Build a minimal ``SubAgentTaskDAO`` for test convenience.

    Args:
        task_id (str): Task identifier.
        prompt (str): Task prompt text.

    Returns:
        SubAgentTaskDAO: Minimal task for use in registry tests.
    """
    return SubAgentTaskDAO(task_summary="Track child execution publication", task_id=task_id, prompt=prompt)


class TestProcessRegistryRegister:
    """``register()`` creates entries in ``pending`` state."""

    def test_register_creates_pending_entry(self) -> None:
        """A registered task is immediately visible with ``status='pending'``."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        entry = reg.get(session_id="s1")

        assert entry is not None
        assert entry.status == "pending"
        assert entry.task_id == "t1"
        assert entry.session_id == "s1"

    def test_prompt_preview_uses_authored_summary_not_long_prompt(self) -> None:
        """The released preview field carries the authored label, not a clipped prompt."""
        reg: ProcessRegistry = _registry()
        reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task(prompt="x" * 200))

        entry = reg.get(session_id="s1")

        assert entry is not None
        assert entry.prompt_preview == "Task summary v1: Track child execution publication"

    def test_prompt_controls_cannot_change_authored_summary(self) -> None:
        """Prompt formatting cannot replace the independently authored summary."""
        reg: ProcessRegistry = _registry()
        reg.register(
            dispatch_id=_DISPATCH_ID,
            task_id="t1",
            session_id="s1",
            task=_task(prompt="Short\n\x1b[2Jtask.  "),
        )

        entry = reg.get(session_id="s1")

        assert entry is not None
        assert entry.prompt_preview == "Task summary v1: Track child execution publication"


class TestProcessRegistryTransitions:
    """Lifecycle transition methods update state correctly."""

    def test_mark_running_transitions_to_running(self) -> None:
        """``mark_running`` transitions status from ``pending`` to ``running``."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        reg.mark_running(session_id="s1", execution_id=eid_s1)

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.status == "running"

    def test_update_last_text_sets_last_text(self) -> None:
        """``update_last_text`` updates ``last_text`` without changing status."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.mark_running(session_id="s1", execution_id=eid_s1)

        reg.update_last_text(session_id="s1", execution_id=eid_s1, text="Processing…")

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.last_text == "Processing…"
        assert entry.status == "running"

    def test_mark_terminal_completed_sets_status_and_answer(self) -> None:
        """``mark_terminal`` with ``completed`` stores answer in ``last_text``."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        reg.mark_terminal(session_id="s1", execution_id=eid_s1, status="completed", answer="Done!")

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.status == "completed"
        assert entry.last_text == "Done!"

    def test_mark_terminal_failed_sets_status(self) -> None:
        """``mark_terminal`` with ``failed`` sets status correctly."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        reg.mark_terminal(session_id="s1", execution_id=eid_s1, status="failed", answer="Error: crash")

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.status == "failed"

    def test_mark_terminal_preserves_existing_operator_abort(self) -> None:
        """A natural completion cannot overwrite durable operator-abort evidence."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.mark_terminal(
            session_id="s1",
            execution_id=eid_s1,
            status="aborted",
            answer="aborted by operator",
            exit_code=2,
            terminal_reason="operator_abort",
            terminated_by="abort",
        )

        reg.mark_terminal(
            session_id="s1",
            execution_id=eid_s1,
            status="failed",
            answer="natural result arrived late",
            exit_code=1,
            terminal_reason="failed",
            terminated_by="natural",
        )

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert entry.status == "aborted"
        assert entry.terminal_reason == "operator_abort"
        assert entry.terminated_by == "abort"

    def test_unknown_session_id_is_a_noop_for_all_write_methods(self) -> None:
        """All write methods silently no-op for unregistered session ids."""
        reg: ProcessRegistry = _registry()

        # None of these should raise:
        reg.mark_running(session_id="nonexistent", execution_id=_UNKNOWN_EXECUTION_ID)
        reg.update_last_text(session_id="nonexistent", execution_id=_UNKNOWN_EXECUTION_ID, text="x")
        reg.mark_terminal(
            session_id="nonexistent",
            execution_id=_UNKNOWN_EXECUTION_ID,
            status="failed",
            answer="",
        )

        assert reg.get(session_id="nonexistent") is None


class TestProcessRegistryDurableTransitions:
    """Registry durable projection and high-frequency write behavior."""

    def test_register_persists_snapshot(self) -> None:
        """Registering a child persists its pending fleet entry."""
        store: MagicMock = MagicMock()
        registry: ProcessRegistry = _registry(fleet_store=store)

        eid_s1 = registry.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        store.persist.assert_called_once_with(entries=registry.snapshot())

    def test_mark_running_records_pid_and_persists(self) -> None:
        """Post-spawn running transition stores process identity durably."""
        store: MagicMock = MagicMock()
        registry: ProcessRegistry = _registry(fleet_store=store)
        eid_s1 = registry.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        store.reset_mock()

        registry.mark_running(session_id="s1", execution_id=eid_s1, pid=1234, started_at=10.0)

        entry = registry.get(session_id="s1")
        assert entry is not None
        assert entry.status == "running"
        assert entry.pid == 1234
        assert entry.started_at == 10.0
        store.persist.assert_called_once_with(entries=registry.snapshot())

    def test_record_heartbeat_does_not_persist(self) -> None:
        """Heartbeat telemetry updates memory without a durable write."""
        store: MagicMock = MagicMock()
        registry: ProcessRegistry = _registry(fleet_store=store)
        eid_s1 = registry.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        store.reset_mock()

        registry.record_heartbeat(session_id="s1", execution_id=eid_s1, phase="streaming", at_seconds=11.0)

        entry = registry.get(session_id="s1")
        assert entry is not None
        assert entry.last_heartbeat_at == 11.0
        assert entry.heartbeat_phase == "streaming"
        store.persist.assert_not_called()

    def test_record_stdout_does_not_persist(self) -> None:
        """Stdout receipt updates memory without a durable write."""
        store: MagicMock = MagicMock()
        registry: ProcessRegistry = _registry(fleet_store=store)
        eid_s1 = registry.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        store.reset_mock()

        registry.record_stdout(session_id="s1", execution_id=eid_s1, at_seconds=11.0)

        entry = registry.get(session_id="s1")
        assert entry is not None
        assert entry.last_stdout_at == 11.0
        store.persist.assert_not_called()

    def test_mark_terminal_records_reason_and_persists(self) -> None:
        """Terminal transitions persist exit and cleanup evidence."""
        store: MagicMock = MagicMock()
        registry: ProcessRegistry = _registry(fleet_store=store)
        eid_s1 = registry.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        store.reset_mock()

        registry.mark_terminal(
            session_id="s1",
            execution_id=eid_s1,
            status="completed",
            answer="done",
            exit_code=0,
            terminal_reason="completed",
            terminated_by="natural",
        )

        entry = registry.get(session_id="s1")
        assert entry is not None
        assert entry.exit_code == 0
        assert entry.terminal_reason == "completed"
        assert entry.terminated_by == "natural"
        store.persist.assert_called_once_with(entries=registry.snapshot())

    def test_mark_running_noops_for_unknown_session(self) -> None:
        """Unknown post-spawn transitions do not create a fleet entry."""
        registry: ProcessRegistry = _registry()

        registry.mark_running(
            session_id="unknown", execution_id=_UNKNOWN_EXECUTION_ID, pid=1234, started_at=10.0
        )

        assert registry.get(session_id="unknown") is None

    def test_record_heartbeat_noops_for_unknown_session(self) -> None:
        """Unknown heartbeat telemetry does not create a fleet entry."""
        registry: ProcessRegistry = _registry()

        registry.record_heartbeat(
            session_id="unknown", execution_id=_UNKNOWN_EXECUTION_ID, phase="streaming", at_seconds=10.0
        )

        assert registry.get(session_id="unknown") is None

    def test_record_stdout_noops_for_unknown_session(self) -> None:
        """Unknown stdout telemetry does not create a fleet entry."""
        registry: ProcessRegistry = _registry()

        registry.record_stdout(session_id="unknown", execution_id=_UNKNOWN_EXECUTION_ID, at_seconds=10.0)

        assert registry.get(session_id="unknown") is None

    def test_mark_terminal_noops_for_unknown_session(self) -> None:
        """Unknown terminal transitions do not create a fleet entry."""
        registry: ProcessRegistry = _registry()

        registry.mark_terminal(
            session_id="unknown",
            execution_id=_UNKNOWN_EXECUTION_ID,
            status="failed",
            answer="error",
            exit_code=1,
            terminal_reason="failed",
            terminated_by="natural",
        )

        assert registry.get(session_id="unknown") is None


class TestProcessRegistrySnapshot:
    """``snapshot()`` and ``get()`` read API behaviour."""

    def test_snapshot_returns_all_entries_in_insertion_order(self) -> None:
        """Snapshot preserves insertion order across two registered tasks."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task("t1"))
        eid_s2 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t2", session_id="s2", task=_task("t2"))

        snap = reg.snapshot()

        assert len(snap) == 2
        assert snap[0].task_id == "t1"
        assert snap[1].task_id == "t2"

    def test_snapshot_returns_a_copy_not_the_internal_list(self) -> None:
        """Mutating the returned snapshot list does not affect the registry."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        snap = reg.snapshot()
        snap.clear()

        assert reg.count == 1

    def test_get_returns_none_for_unknown_session_id(self) -> None:
        """``get()`` returns ``None`` when the session id is not registered."""
        reg: ProcessRegistry = _registry()

        assert reg.get(session_id="unknown") is None


class TestProcessRegistryCounts:
    """``count`` and ``running_count`` property behaviour."""

    def test_count_reflects_total_registered_entries(self) -> None:
        """``count`` returns the total number of registered sub-agents."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task("t1"))
        eid_s2 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t2", session_id="s2", task=_task("t2"))

        assert reg.count == 2

    def test_running_count_reflects_only_running_entries(self) -> None:
        """``running_count`` counts only sub-agents in ``running`` state."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task("t1"))
        eid_s2 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t2", session_id="s2", task=_task("t2"))
        reg.mark_running(session_id="s1", execution_id=eid_s1)

        assert reg.running_count == 1

    def test_running_count_zero_when_all_terminal(self) -> None:
        """``running_count`` returns 0 after all sub-agents reach terminal state."""
        reg: ProcessRegistry = _registry()
        eid_s1 = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.mark_running(session_id="s1", execution_id=eid_s1)
        reg.mark_terminal(session_id="s1", execution_id=eid_s1, status="completed", answer="ok")

        assert reg.running_count == 0


# ── Feature 94 T02: execution identity and canonical terminal arbitration ────


def _result(
    *,
    session_id: str = "s1",
    execution_id: str,
    status: str = "completed",
    answer: str = "ok",
    exit_code: int = 0,
) -> SubAgentResultDAO:
    """Build one complete terminal candidate for an incarnation."""
    return SubAgentResultDAO(
        task_id="t1",
        session_id=session_id,
        status=status,  # type: ignore[arg-type]
        answer=answer,
        exit_code=exit_code,
        execution_id=execution_id,
    )


class TestProcessRegistryExecutionIdentity:
    """Registration allocates incarnations and every mutator validates them."""

    def test_register_returns_fresh_canonical_execution_id(self) -> None:
        """Each registration allocates a distinct UUID stored on the runtime entry."""
        reg: ProcessRegistry = _registry()

        first: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        second: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t2", session_id="s2", task=_task())

        assert first != second
        assert str(UUID(first)) == first
        entry = reg.get(session_id="s1")
        assert entry is not None and entry.execution_id == first

    def test_register_refuses_non_terminal_session(self) -> None:
        """The same session cannot execute concurrently in one registry."""
        reg: ProcessRegistry = _registry()
        original: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        with pytest.raises(ExecutionConflictError):
            reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        entry = reg.get(session_id="s1")
        assert entry is not None and entry.execution_id == original

    def test_reregister_terminal_session_replaces_incarnation_and_clears_winner(self) -> None:
        """Reuse after terminal allocates a new identity and forgets the old winner."""
        reg: ProcessRegistry = _registry()
        old: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.commit_terminal(
            result=_result(execution_id=old), terminal_reason="completed", terminated_by="natural"
        )

        new: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        assert new != old
        entry = reg.get(session_id="s1")
        assert entry is not None and (entry.status, entry.execution_id) == ("pending", new)
        assert reg.terminal_result(session_id="s1", execution_id=new) is None
        assert reg.terminal_result(session_id="s1", execution_id=old) is None

    def test_stale_incarnation_mutators_are_refused(self) -> None:
        """A captured old execution_id cannot change the reused session entry."""
        reg: ProcessRegistry = _registry()
        old: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.commit_terminal(
            result=_result(execution_id=old), terminal_reason="completed", terminated_by="natural"
        )
        reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        reg.mark_running(session_id="s1", execution_id=old, pid=9, started_at=1.0)
        reg.record_heartbeat(session_id="s1", execution_id=old, phase="p", at_seconds=1.0)
        reg.record_stdout(session_id="s1", execution_id=old, at_seconds=1.0)
        reg.update_last_text(session_id="s1", execution_id=old, text="stale")
        reg.mark_terminal(session_id="s1", execution_id=old, status="failed", answer="stale")
        with pytest.raises(StaleExecutionError):
            reg.commit_terminal(
                result=_result(execution_id=old, status="failed"),
                terminal_reason="failed",
                terminated_by="natural",
            )

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert (entry.status, entry.pid, entry.last_text, entry.last_stdout_at) == (
            "pending",
            None,
            None,
            None,
        )

    def test_register_publishes_pending_evidence_before_fleet(self) -> None:
        """Pending identity is published before the pending fleet projection."""
        store: MagicMock = MagicMock()
        reg: ProcessRegistry = _registry(fleet_store=store)

        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )

        assert [name for name, _, _ in store.mock_calls] == ["publish_execution", "persist"]
        evidence = store.publish_execution.call_args.kwargs["evidence"]
        assert (evidence.phase, evidence.execution_id) == ("pending", execution_id)

    def test_mark_running_publishes_running_evidence_before_fleet(self) -> None:
        """Fresh capture/context identity is published before the running row."""
        store: MagicMock = MagicMock()
        reg: ProcessRegistry = _registry(fleet_store=store)
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        store.reset_mock()
        identity = StdoutCaptureIdentityDAO(device=3, inode=4)

        reg.mark_running(
            session_id="s1",
            execution_id=execution_id,
            pid=7,
            started_at=1.0,
            stdout_identity=identity,
            spawn_context_sha256="d" * 64,
        )

        assert [name for name, _, _ in store.mock_calls] == ["publish_execution", "persist"]
        evidence = store.publish_execution.call_args.kwargs["evidence"]
        assert (evidence.phase, evidence.stdout_identity, evidence.spawn_context_sha256) == (
            "running",
            identity,
            "d" * 64,
        )


class TestProcessRegistryCommitTerminal:
    """commit_terminal is the single no-await terminal linearization point."""

    def test_first_candidate_wins_and_updates_entry(self) -> None:
        """The first complete candidate becomes the winner and the fleet row."""
        store: MagicMock = MagicMock()
        reg: ProcessRegistry = _registry(fleet_store=store)
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        store.reset_mock()
        candidate = _result(execution_id=execution_id, answer="done")

        winner = reg.commit_terminal(result=candidate, terminal_reason="completed", terminated_by="natural")

        assert winner == candidate
        entry = reg.get(session_id="s1")
        assert entry is not None
        assert (
            entry.status,
            entry.last_text,
            entry.exit_code,
            entry.terminal_reason,
            entry.terminated_by,
        ) == (
            "completed",
            "done",
            0,
            "completed",
            "natural",
        )
        store.persist.assert_called_once_with(entries=reg.snapshot())
        assert reg.terminal_result(session_id="s1", execution_id=execution_id) == candidate

    def test_competing_candidate_returns_existing_complete_winner(self) -> None:
        """A later candidate cannot regress or rewrite the winner or its envelope."""
        reg: ProcessRegistry = _registry()
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        aborted = _result(
            execution_id=execution_id, status="aborted", answer="aborted by operator", exit_code=2
        )
        reg.commit_terminal(result=aborted, terminal_reason="operator_abort", terminated_by="abort")
        failure = _result(execution_id=execution_id, status="failed", answer="late", exit_code=1).model_copy(
            update={"failure_code": "provider_stream_interrupted", "safe_message": "x"}
        )

        winner = reg.commit_terminal(result=failure, terminal_reason="failed", terminated_by="natural")

        assert winner == aborted
        entry = reg.get(session_id="s1")
        assert entry is not None and (entry.status, entry.terminal_reason) == ("aborted", "operator_abort")

    def test_winner_preserves_failure_envelope(self) -> None:
        """The complete failure envelope is retained, never rebuilt from last_text."""
        reg: ProcessRegistry = _registry()
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        reg.update_last_text(session_id="s1", execution_id=execution_id, text="partial")
        failure = _result(
            execution_id=execution_id, status="failed", answer="stream cut", exit_code=1
        ).model_copy(
            update={
                "failure_code": "provider_stream_disconnected",
                "attempts": 3,
                "partial_output_committed": True,
            }
        )

        winner = reg.commit_terminal(result=failure, terminal_reason="failed", terminated_by="natural")

        assert (winner.failure_code, winner.attempts, winner.partial_output_committed, winner.answer) == (
            "provider_stream_disconnected",
            3,
            True,
            "stream cut",
        )

    def test_terminal_entry_never_regresses(self) -> None:
        """Running, heartbeat, stdout and text updates cannot touch a terminal entry."""
        reg: ProcessRegistry = _registry()
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        reg.commit_terminal(
            result=_result(execution_id=execution_id, answer="final"),
            terminal_reason="completed",
            terminated_by="natural",
        )

        reg.mark_running(session_id="s1", execution_id=execution_id, pid=5, started_at=1.0)
        reg.update_last_text(session_id="s1", execution_id=execution_id, text="late delta")
        reg.record_heartbeat(session_id="s1", execution_id=execution_id, phase="p", at_seconds=2.0)
        reg.record_stdout(session_id="s1", execution_id=execution_id, at_seconds=2.0)

        entry = reg.get(session_id="s1")
        assert entry is not None
        assert (entry.status, entry.last_text, entry.pid, entry.heartbeat_phase, entry.last_stdout_at) == (
            "completed",
            "final",
            None,
            None,
            None,
        )

    def test_fleet_persist_failure_retains_winner(self) -> None:
        """A raising fleet projection never rolls back the in-memory winner."""
        store: MagicMock = MagicMock()
        reg: ProcessRegistry = _registry(fleet_store=store)
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        store.persist.side_effect = OSError("disk full")
        candidate = _result(execution_id=execution_id)

        with pytest.raises(OSError):
            reg.commit_terminal(result=candidate, terminal_reason="completed", terminated_by="natural")

        assert reg.terminal_result(session_id="s1", execution_id=execution_id) == candidate
        entry = reg.get(session_id="s1")
        assert entry is not None and entry.status == "completed"

    @pytest.mark.parametrize("status", ["pending", "running"])
    def test_non_terminal_candidate_is_refused(self, status: str) -> None:
        """Only completed, failed or aborted candidates can be committed."""
        reg: ProcessRegistry = _registry()
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )

        with pytest.raises(ValueError):
            reg.commit_terminal(
                result=_result(execution_id=execution_id, status=status),
                terminal_reason="completed",
                terminated_by="natural",
            )

        assert reg.terminal_result(session_id="s1", execution_id=execution_id) is None

    def test_unknown_session_commit_is_refused(self) -> None:
        """No winner can be installed for an unregistered session."""
        with pytest.raises(StaleExecutionError):
            _registry().commit_terminal(
                result=_result(execution_id=_UNKNOWN_EXECUTION_ID),
                terminal_reason="completed",
                terminated_by="natural",
            )

    def test_mark_terminal_adapter_delegates_to_commit(self) -> None:
        """The compatibility adapter builds a complete result and keeps first-wins."""
        reg: ProcessRegistry = _registry()
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )

        reg.mark_terminal(
            session_id="s1",
            execution_id=execution_id,
            status="failed",
            answer="swept",
            exit_code=1,
            terminal_reason="failed",
            terminated_by="sweep",
        )

        winner = reg.terminal_result(session_id="s1", execution_id=execution_id)
        assert winner is not None
        assert (winner.task_id, winner.status, winner.answer, winner.exit_code, winner.execution_id) == (
            "t1",
            "failed",
            "swept",
            1,
            execution_id,
        )

    def test_record_terminal_evidence_publishes_winner_status(self) -> None:
        """Terminal sibling evidence carries the winner's status and status digest."""
        store: MagicMock = MagicMock()
        reg: ProcessRegistry = _registry(fleet_store=store)
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        reg.commit_terminal(
            result=_result(execution_id=execution_id, status="aborted", exit_code=2),
            terminal_reason="operator_abort",
            terminated_by="abort",
        )
        store.reset_mock()
        store.publish_execution.side_effect = [False, True]

        failed: bool = reg.record_terminal_evidence(
            session_id="s1", execution_id=execution_id, status_sha256="e" * 64
        )
        committed: bool = reg.record_terminal_evidence(
            session_id="s1", execution_id=execution_id, status_sha256="e" * 64
        )

        assert (failed, committed) == (False, True)
        evidence = store.publish_execution.call_args.kwargs["evidence"]
        assert (evidence.phase, evidence.status, evidence.status_sha256) == ("terminal", "aborted", "e" * 64)

    def test_record_terminal_evidence_without_winner_or_stale_is_noop(self) -> None:
        """No terminal evidence is published before a winner or for a stale identity."""
        store: MagicMock = MagicMock()
        reg: ProcessRegistry = _registry(fleet_store=store)
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        store.reset_mock()

        before_winner: bool = reg.record_terminal_evidence(
            session_id="s1", execution_id=execution_id, status_sha256="e" * 64
        )
        stale: bool = reg.record_terminal_evidence(
            session_id="s1", execution_id=_UNKNOWN_EXECUTION_ID, status_sha256="e" * 64
        )

        assert (before_winner, stale) == (False, False)
        store.publish_execution.assert_not_called()


class TestDispatchGeneration:
    """Explicit dispatch membership (feature 94 a.2): batches never come from child events."""

    def test_no_dispatch_returns_explicit_empty_snapshot(self) -> None:
        """Before any dispatch the observer sees the empty value."""
        assert ProcessRegistry().attached_snapshot() == AttachedDispatchSnapshotDAO.empty()

    def test_begin_dispatch_returns_monotonic_sequence(self) -> None:
        """Each admitted dispatch gets the next sequence; an empty batch still replaces the group."""
        reg: ProcessRegistry = ProcessRegistry()

        first: int = reg.begin_dispatch(dispatch_id=_DISPATCH_ID)
        second: int = reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)

        assert (first, second) == (1, 2)
        assert reg.attached_snapshot() == AttachedDispatchSnapshotDAO(
            dispatch_id=_SECOND_DISPATCH_ID, dispatch_sequence=2, entries=()
        )

    def test_duplicate_dispatch_identity_is_refused_without_side_effect(self) -> None:
        """Reusing a dispatch id raises and neither sequence nor latest batch changes."""
        reg: ProcessRegistry = _registry()

        with pytest.raises(ValueError, match="duplicate dispatch identity"):
            reg.begin_dispatch(dispatch_id=_DISPATCH_ID)

        assert reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID) == 2

    def test_register_requires_begun_dispatch(self) -> None:
        """An unknown dispatch is refused before any entry or evidence exists."""
        reg: ProcessRegistry = ProcessRegistry()

        with pytest.raises(ValueError, match="unknown dispatch identity"):
            reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        assert reg.get(session_id="s1") is None
        assert reg.count == 0

    def test_snapshot_lists_only_latest_batch_in_registration_order(self) -> None:
        """Old executions survive in the registry but never reappear in the latest group."""
        reg: ProcessRegistry = _registry()
        old: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="old", task=_task())
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)
        b: str = reg.register(dispatch_id=_SECOND_DISPATCH_ID, task_id="t2", session_id="b", task=_task())
        a: str = reg.register(dispatch_id=_SECOND_DISPATCH_ID, task_id="t3", session_id="a", task=_task())

        snapshot: AttachedDispatchSnapshotDAO = reg.attached_snapshot()

        assert [(e.session_id, e.execution_id) for e in snapshot.entries] == [("b", b), ("a", a)]
        old_entry = reg.get(session_id="old")
        assert old_entry is not None and (old_entry.execution_id, old_entry.status) == (old, "pending")
        assert [e.session_id for e in reg.snapshot()] == ["old", "b", "a"]

    def test_late_registration_joins_its_captured_dispatch_not_the_latest(self) -> None:
        """A first-batch child registered after the second batch began stays out of the latest group."""
        reg: ProcessRegistry = _registry()
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)

        reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="late", task=_task())

        assert reg.attached_snapshot().entries == ()
        assert reg.get(session_id="late") is not None

    def test_snapshot_entries_are_deep_copies(self) -> None:
        """Mutating an observed entry cannot change registry state."""
        reg: ProcessRegistry = _registry()
        reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        observed = reg.attached_snapshot().entries[0]
        observed.status = "failed"

        entry = reg.get(session_id="s1")
        assert entry is not None and entry.status == "pending"

    def test_terminal_reuse_by_newer_dispatch_leaves_old_batch_without_stale_member(self) -> None:
        """A reused session is shown only for the incarnation registered in the observed batch."""
        reg: ProcessRegistry = _registry()
        old: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.commit_terminal(
            result=_result(execution_id=old), terminal_reason="completed", terminated_by="natural"
        )
        old_view: AttachedDispatchSnapshotDAO = reg.attached_snapshot()
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)

        new: str = reg.register(dispatch_id=_SECOND_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        assert [e.execution_id for e in old_view.entries] == [old]
        assert [(e.execution_id, e.status) for e in reg.attached_snapshot().entries] == [(new, "pending")]

    def test_latest_batch_hides_member_reregistered_by_an_older_batch(self) -> None:
        """A late older-batch registration of a latest-batch session never shows that new incarnation."""
        reg: ProcessRegistry = _registry()
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)
        latest: str = reg.register(
            dispatch_id=_SECOND_DISPATCH_ID, task_id="t2", session_id="s1", task=_task()
        )
        reg.commit_terminal(
            result=_result(execution_id=latest), terminal_reason="completed", terminated_by="natural"
        )

        late: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        assert late != latest
        assert reg.attached_snapshot().entries == ()

    def test_retired_non_latest_dispatch_is_pruned_but_latest_is_kept(self) -> None:
        """Teardown discards obsolete membership only; executions and latest batch remain."""
        reg: ProcessRegistry = _registry()
        reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)
        reg.register(dispatch_id=_SECOND_DISPATCH_ID, task_id="t2", session_id="s2", task=_task())

        reg.retire_dispatch(dispatch_id=_SECOND_DISPATCH_ID)
        reg.retire_dispatch(dispatch_id=_DISPATCH_ID)

        assert reg.retained_dispatch_ids() == (_SECOND_DISPATCH_ID,)
        assert [e.session_id for e in reg.attached_snapshot().entries] == ["s2"]
        assert [e.session_id for e in reg.snapshot()] == ["s1", "s2"]

    def test_retired_latest_dispatch_is_pruned_when_a_newer_one_begins(self) -> None:
        """A completed latest batch is dropped once it stops being latest; active ones stay."""
        third: str = "33333333-3333-4333-8333-333333333333"
        reg: ProcessRegistry = _registry()
        reg.retire_dispatch(dispatch_id=_DISPATCH_ID)
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)
        reg.begin_dispatch(dispatch_id=third)

        assert reg.retained_dispatch_ids() == (_SECOND_DISPATCH_ID, third)

    def test_retire_unknown_dispatch_is_a_no_op(self) -> None:
        """Retiring an id that holds no membership changes nothing."""
        reg: ProcessRegistry = _registry()

        reg.retire_dispatch(dispatch_id=_SECOND_DISPATCH_ID)

        assert reg.retained_dispatch_ids() == (_DISPATCH_ID,)

    def test_dispatch_of_returns_captured_identity_for_current_incarnation_only(self) -> None:
        """Lifecycle consumers resolve an incarnation's batch; stale or unknown incarnations get None."""
        reg: ProcessRegistry = _registry()
        old: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.commit_terminal(
            result=_result(execution_id=old), terminal_reason="completed", terminated_by="natural"
        )
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)
        new: str = reg.register(dispatch_id=_SECOND_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        assert reg.dispatch_of(session_id="s1", execution_id=new) == DispatchIdentityDAO(
            dispatch_id=_SECOND_DISPATCH_ID, dispatch_sequence=2
        )
        assert reg.dispatch_of(session_id="s1", execution_id=old) is None
        assert reg.dispatch_of(session_id="nobody", execution_id=new) is None

    @pytest.mark.parametrize(
        ("terminal", "expected"),
        [(None, True), ("running", False), ("pending", False), ("completed", True)],
        ids=["unknown", "running", "pending", "terminal"],
    )
    def test_accepts_new_execution_only_for_absent_or_terminal_sessions(
        self, terminal: Optional[str], expected: bool
    ) -> None:
        """Admission may reuse a session only when it has no live incarnation."""
        reg: ProcessRegistry = _registry()
        if terminal is not None:
            eid: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
            if terminal == "running":
                reg.mark_running(session_id="s1", execution_id=eid, pid=1, started_at=1.0)
            if terminal == "completed":
                reg.commit_terminal(
                    result=_result(execution_id=eid), terminal_reason="completed", terminated_by="natural"
                )

        assert reg.accepts_new_execution(session_id="s1") is expected


_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
"""Synthetic run identity for the real temporary fleet store."""


def _sibling(*, history_root: Path, session_id: str) -> dict[str, Any]:
    """Read one child's published execution sibling from disk.

    Args:
        history_root (Path): Temporary history root the store writes under.
        session_id (str): Child session whose sibling is read.

    Returns:
        dict[str, Any]: Decoded ``execution.v1.json`` content.
    """
    path: Path = history_root / "orch-1" / "children" / session_id / "execution.v1.json"
    return json.loads(path.read_text(encoding="utf-8"))


class TestExecutionSiblingDispatchIdentity:
    """The sibling carries the admitting dispatch in every phase (feature 94 a.4)."""

    @staticmethod
    def _store(*, tmp_path: Path) -> FleetStore:
        """Build a real writer-side fleet store under ``tmp_path``."""
        return FleetStore(history_root=tmp_path, orchestrator_session_id="orch-1", run_id=_RUN_ID)

    def test_pending_running_and_terminal_siblings_carry_admitting_dispatch(self, tmp_path: Path) -> None:
        """Every published phase keeps the dispatch passed to register."""
        reg: ProcessRegistry = _registry(fleet_store=self._store(tmp_path=tmp_path))
        execution_id: str = reg.register(
            dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task()
        )
        pending: dict[str, Any] = _sibling(history_root=tmp_path, session_id="s1")
        reg.mark_running(session_id="s1", execution_id=execution_id, pid=1, started_at=1.0)
        running: dict[str, Any] = _sibling(history_root=tmp_path, session_id="s1")
        reg.commit_terminal(
            result=_result(execution_id=execution_id), terminal_reason="completed", terminated_by="natural"
        )
        assert reg.record_terminal_evidence(
            session_id="s1", execution_id=execution_id, status_sha256="e" * 64
        )
        terminal: dict[str, Any] = _sibling(history_root=tmp_path, session_id="s1")

        assert [
            (doc["phase"], doc["dispatch_id"], doc["execution_id"]) for doc in (pending, running, terminal)
        ] == [
            ("pending", _DISPATCH_ID, execution_id),
            ("running", _DISPATCH_ID, execution_id),
            ("terminal", _DISPATCH_ID, execution_id),
        ]

    def test_terminal_reuse_by_newer_dispatch_republishes_new_identity(self, tmp_path: Path) -> None:
        """A reused session's sibling names the newer dispatch and incarnation."""
        reg: ProcessRegistry = _registry(fleet_store=self._store(tmp_path=tmp_path))
        old: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())
        reg.commit_terminal(
            result=_result(execution_id=old), terminal_reason="completed", terminated_by="natural"
        )
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)

        new: str = reg.register(dispatch_id=_SECOND_DISPATCH_ID, task_id="t1", session_id="s1", task=_task())

        sibling: dict[str, Any] = _sibling(history_root=tmp_path, session_id="s1")
        assert (sibling["phase"], sibling["dispatch_id"], sibling["execution_id"]) == (
            "pending",
            _SECOND_DISPATCH_ID,
            new,
        )
        assert new != old

    def test_late_chain_step_sibling_keeps_its_captured_older_dispatch(self, tmp_path: Path) -> None:
        """A step registered after a newer batch began records the batch that admitted it."""
        reg: ProcessRegistry = _registry(fleet_store=self._store(tmp_path=tmp_path))
        reg.begin_dispatch(dispatch_id=_SECOND_DISPATCH_ID)

        late: str = reg.register(dispatch_id=_DISPATCH_ID, task_id="t1", session_id="late", task=_task())

        sibling: dict[str, Any] = _sibling(history_root=tmp_path, session_id="late")
        assert (sibling["dispatch_id"], sibling["execution_id"]) == (_DISPATCH_ID, late)
