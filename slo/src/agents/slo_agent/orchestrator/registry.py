"""ProcessRegistry — observable lifecycle tracking for sub-agent processes.

The registry is the in-memory write authority. A bound FleetStore mirrors its
lifecycle transitions to durable fleet evidence.

Feature 94 (a.4, T02) adds execution identity: ``register`` allocates one
``execution_id`` per incarnation, every mutator validates the incarnation its
caller captured, and ``commit_terminal`` is the single no-await linearization
point for terminal results. Callers publish caches and status.json only from the
winner it returns.

Feature 94 (a.2, T03) adds explicit dispatch generation: ``begin_dispatch``
selects a fresh display batch, ``register`` appends each child to the batch its
caller captured, and ``attached_snapshot`` projects only the latest batch.
Execution entries are never cleared when the displayed batch changes.

Sub-spec 71.a.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from src.agents.slo_agent.orchestrator.dao import (
    TERMINAL_STATUSES,
    AttachedDispatchSnapshotDAO,
    ChildExecutionEvidenceDAO,
    DispatchIdentityDAO,
    StdoutCaptureIdentityDAO,
    SubAgentResultDAO,
    SubAgentStatus,
    SubAgentStatusDAO,
    SubAgentTaskDAO,
    TerminalReason,
    TerminatedBy,
    terminal_reason_for_status,
)
from src.agents.slo_agent.orchestrator.task_preview import TaskPreview

if TYPE_CHECKING:
    from src.agents.slo_agent.orchestrator.fleet_store import FleetStore

__all__ = ["ExecutionConflictError", "ProcessRegistry", "StaleExecutionError"]


class StaleExecutionError(RuntimeError):
    """A terminal commit named an unknown session or a superseded incarnation."""


class ExecutionConflictError(ValueError):
    """Registration targeted a session whose current incarnation is not terminal."""


class ProcessRegistry:
    """In-memory lifecycle authority for one pool, optionally mirrored to fleet.json."""

    def __init__(self, *, fleet_store: Optional["FleetStore"] = None) -> None:
        """Initialize an empty registry with an optional durable projection.

        WHAT: Creates the pool-owned lifecycle authority and retains its mirror.
        WHO: Called by SubAgentPool once per orchestrator session.
        WHEN: Before the pool accepts its first child task.

        Args:
            fleet_store (Optional[FleetStore]): Durable projection target; None keeps
                direct callers in legacy in-memory-only mode.
        """
        self._store: dict[str, SubAgentStatusDAO] = {}
        # Winner per session for its *current* incarnation; cleared on reuse.
        self._terminal_results: dict[str, SubAgentResultDAO] = {}
        # Last published versioned evidence per session's current incarnation.
        self._evidence: dict[str, ChildExecutionEvidenceDAO] = {}
        self._fleet_store: Optional[FleetStore] = fleet_store
        # Dispatch generation (a.2). Membership lists hold (session_id, execution_id)
        # in registration order; only begun, not-yet-pruned dispatches have one, and
        # identities are pruned with them, so both stay bounded by active + latest.
        self._dispatch_members: dict[str, list[tuple[str, str]]] = {}
        self._dispatch_identities: dict[str, DispatchIdentityDAO] = {}
        # Dispatches whose pool teardown finished; pruned once they are not latest.
        self._retired_dispatch_ids: set[str] = set()
        self._latest_dispatch_id: str = ""
        # Monotonic within one pool; never reset.
        self._dispatch_sequence: int = 0
        # Batch identity of each session's current incarnation, for lifecycle metadata.
        self._entry_dispatch: dict[str, DispatchIdentityDAO] = {}

    def begin_dispatch(self, *, dispatch_id: str) -> int:
        """Select a fresh display batch before dispatch yields to child work.

        WHAT: Increments the sequence, makes ``dispatch_id`` the latest batch with
            an empty membership (so an empty valid dispatch still replaces the
            displayed group) and prunes retired batches that are no longer latest.
        WHO: Called by SubAgentPool inside its no-await admission section.
        WHEN: Once per admitted dispatch, before the start event and any child.

        Args:
            dispatch_id (str): Pool-generated unique batch identity.

        Returns:
            int: Monotonic sequence used to ignore older event delivery.

        Raises:
            ValueError: If the identity's membership is still held by this registry.
        """
        if dispatch_id in self._dispatch_members:
            raise ValueError("duplicate dispatch identity")
        self._dispatch_sequence += 1
        self._latest_dispatch_id = dispatch_id
        self._dispatch_members[dispatch_id] = []
        self._dispatch_identities[dispatch_id] = DispatchIdentityDAO(
            dispatch_id=dispatch_id, dispatch_sequence=self._dispatch_sequence
        )
        self._prune_retired_dispatches()
        return self._dispatch_sequence

    def retire_dispatch(self, *, dispatch_id: str) -> None:
        """Release a finished batch's membership unless it is still the displayed one.

        WHAT: Marks the batch retired and discards every retired membership list
            except the latest; execution entries are never touched. Unknown ids
            are a no-op.
        WHO: Called by SubAgentPool.dispatch in its teardown ``finally``.
        WHEN: After every child of the batch has settled.

        Args:
            dispatch_id (str): Batch whose dispatch call has finished.
        """
        if dispatch_id not in self._dispatch_members:
            return
        self._retired_dispatch_ids.add(dispatch_id)
        self._prune_retired_dispatches()

    def retained_dispatch_ids(self) -> tuple[str, ...]:
        """Return the batches whose membership is still held, oldest first.

        WHAT: Exposes only identities, for teardown-bound verification.
        WHO: Called by tests asserting membership stays bounded.
        WHEN: After dispatch teardown.

        Returns:
            tuple[str, ...]: Active batches plus the latest one.
        """
        return tuple(self._dispatch_members)

    def attached_snapshot(self) -> AttachedDispatchSnapshotDAO:
        """Return the latest group for session observers without changing execution.

        WHAT: Deep-copies the latest batch's members whose session still holds
            the incarnation registered in that batch; a session reused by a newer
            batch drops out of the older one.
        WHO: Called through SubAgentPool and SloAgentSession by TUI observation.
        WHEN: On every observation poll; it never mutates registry state.

        Returns:
            AttachedDispatchSnapshotDAO: Ordered current-batch projection only, or
                the explicit empty value before the first dispatch.
        """
        identity: Optional[DispatchIdentityDAO] = self._dispatch_identities.get(self._latest_dispatch_id)
        if identity is None:
            return AttachedDispatchSnapshotDAO.empty()
        return AttachedDispatchSnapshotDAO(
            dispatch_id=identity.dispatch_id,
            dispatch_sequence=identity.dispatch_sequence,
            entries=tuple(
                self._store[session_id].model_copy(deep=True)
                for session_id, execution_id in self._dispatch_members[identity.dispatch_id]
                if self._store[session_id].execution_id == execution_id
            ),
        )

    def dispatch_of(self, *, session_id: str, execution_id: str) -> Optional[DispatchIdentityDAO]:
        """Return the batch that registered the named current incarnation.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation the caller captured.

        Returns:
            Optional[DispatchIdentityDAO]: Captured batch identity, or None for an
                unknown or superseded incarnation.
        """
        if self._current_entry(session_id=session_id, execution_id=execution_id) is None:
            return None
        return self._entry_dispatch.get(session_id)

    def accepts_new_execution(self, *, session_id: str) -> bool:
        """Return whether a new incarnation of the session may be admitted.

        Args:
            session_id (str): Candidate child session identifier.

        Returns:
            bool: True when the session is unknown or its current incarnation is terminal.
        """
        existing: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        return existing is None or existing.status in TERMINAL_STATUSES

    def register(self, *, dispatch_id: str, task_id: str, session_id: str, task: SubAgentTaskDAO) -> str:
        """Register a new pending incarnation and persist its identity and fleet row.

        WHAT: Allocates a fresh execution_id, replaces a terminal prior incarnation
            (forgetting its winner), records the normalized TaskPreview of the
            prompt, publishes pending sibling evidence stamped with the captured
            dispatch, persists the pending fleet entry, then appends the child to
            that dispatch.
        WHO: Called by SubAgentPool before it creates the wrapper and emits spawned.
        WHEN: Once for every accepted child task, after any earlier incarnation of
            the same session has finished its pool teardown.

        Args:
            dispatch_id (str): Batch captured at admission, never the latest batch.
            task_id (str): Caller-assigned child task identifier.
            session_id (str): Pool-assigned child session identifier.
            task (SubAgentTaskDAO): Child task that supplies the prompt preview.

        Returns:
            str: The new incarnation's canonical execution UUID.

        Raises:
            ExecutionConflictError: If the session's current incarnation is not terminal.
            ValueError: If the dispatch was never begun or was pruned, or the
                session id is unsafe as an evidence path component.
        """
        if dispatch_id not in self._dispatch_members:
            raise ValueError("unknown dispatch identity")
        if not self.accepts_new_execution(session_id=session_id):
            raise ExecutionConflictError("session already has a non-terminal execution in this pool")
        execution_id: str = str(uuid4())
        pending: ChildExecutionEvidenceDAO = ChildExecutionEvidenceDAO.pending(
            session_id=session_id, execution_id=execution_id, dispatch_id=dispatch_id
        )
        self._terminal_results.pop(session_id, None)
        self._store[session_id] = SubAgentStatusDAO(
            task_id=task_id,
            session_id=session_id,
            status="pending",
            prompt_preview=TaskPreview.build(task_text=task.prompt),
            execution_id=execution_id,
        )
        self._publish_evidence(evidence=pending)
        self._persist()
        self._register_dispatch_member(
            dispatch_id=dispatch_id, session_id=session_id, execution_id=execution_id
        )
        return execution_id

    def _register_dispatch_member(self, *, dispatch_id: str, session_id: str, execution_id: str) -> None:
        """Associate register's child with its captured batch, never the latest batch.

        Args:
            dispatch_id (str): Dispatch captured before asynchronous identity resolution.
            session_id (str): Registered session identity.
            execution_id (str): Incarnation returned by register.
        """
        self._dispatch_members[dispatch_id].append((session_id, execution_id))
        self._entry_dispatch[session_id] = self._dispatch_identities[dispatch_id]

    def _prune_retired_dispatches(self) -> None:
        """Discard retired membership lists except the latest batch's."""
        for dispatch_id in self._retired_dispatch_ids - {self._latest_dispatch_id}:
            self._dispatch_members.pop(dispatch_id, None)
            self._dispatch_identities.pop(dispatch_id, None)
        self._retired_dispatch_ids &= {self._latest_dispatch_id}

    def mark_running(
        self,
        *,
        session_id: str,
        execution_id: str,
        pid: int = 0,
        started_at: float = 0.0,
        stdout_identity: Optional[StdoutCaptureIdentityDAO] = None,
        spawn_context_sha256: Optional[str] = None,
    ) -> None:
        """Record a spawned child identity and persist its running transition.

        WHAT: Publishes running sibling evidence for the fresh capture/context, then
            moves the entry to running with its pid and spawn time.
        WHO: Called by SubAgentProcess immediately after child subprocess creation.
        WHEN: Once after a successful spawn; refused for stale or terminal incarnations.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation captured by the calling wrapper.
            pid (int): Spawned process id. Defaults to 0 for legacy direct callers.
            started_at (float): Wall-clock spawn time. Defaults to 0.0.
            stdout_identity (Optional[StdoutCaptureIdentityDAO]): Freshly opened
                stdout capture identity. Defaults to None (no trusted capture).
            spawn_context_sha256 (Optional[str]): Digest of this incarnation's exact
                spawn-context bytes. Defaults to None (no trusted context).
        """
        entry: Optional[SubAgentStatusDAO] = self._live_entry(
            session_id=session_id, execution_id=execution_id
        )
        if entry is None:
            return
        running: ChildExecutionEvidenceDAO = self._current_evidence(entry=entry).running(
            stdout_identity=stdout_identity, spawn_context_sha256=spawn_context_sha256
        )
        self._store[session_id] = entry.model_copy(
            update={"status": "running", "pid": pid, "started_at": started_at}
        )
        self._publish_evidence(evidence=running)
        self._persist()

    def record_heartbeat(self, *, session_id: str, execution_id: str, phase: str, at_seconds: float) -> None:
        """Record accepted heartbeat telemetry without a high-frequency durable write.

        WHAT: Updates the latest heartbeat time and phase in memory.
        WHO: Called by SubAgentProcess after it accepts same-session stderr telemetry.
        WHEN: On each recognized headless_status event; refused once terminal or stale.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation captured by the calling wrapper.
            phase (str): Latest heartbeat phase label.
            at_seconds (float): Monotonic telemetry receipt time.
        """
        self._update_live(
            session_id=session_id,
            execution_id=execution_id,
            update={"last_heartbeat_at": at_seconds, "heartbeat_phase": phase},
        )

    def record_stdout(self, *, session_id: str, execution_id: str, at_seconds: float) -> None:
        """Record stdout receipt telemetry without a high-frequency durable write.

        WHAT: Updates the latest stdout time in memory.
        WHO: Called by SubAgentProcess before it parses a stdout line.
        WHEN: Once for every non-empty child stdout line; refused once terminal or stale.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation captured by the calling wrapper.
            at_seconds (float): Monotonic stdout receipt time.
        """
        self._update_live(
            session_id=session_id, execution_id=execution_id, update={"last_stdout_at": at_seconds}
        )

    def update_last_text(self, *, session_id: str, execution_id: str, text: str) -> None:
        """Update the latest visible child text without a high-frequency durable write.

        WHAT: Retains the most recent text_delta in the in-memory fleet entry.
        WHO: Called by SubAgentProcess while relaying parsed child stdout.
        WHEN: On each visible text delta; refused once terminal or stale.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation captured by the calling wrapper.
            text (str): Latest visible child text fragment.
        """
        self._update_live(session_id=session_id, execution_id=execution_id, update={"last_text": text})

    def commit_terminal(
        self,
        *,
        result: SubAgentResultDAO,
        terminal_reason: TerminalReason,
        terminated_by: TerminatedBy,
    ) -> SubAgentResultDAO:
        """Install the first complete terminal result for an incarnation and return the winner.

        WHAT: Without awaiting, returns the existing winner when one is installed;
            otherwise installs ``result``, updates the fleet entry, then persists.
            A persistence failure never rolls back the installed winner.
        WHO: Called by SubAgentProcess._publish_terminal (natural run, confirmed
            reap, pending abort) and by the mark_terminal compatibility adapter.
        WHEN: Before any caller caches a result or writes status.json.

        Args:
            result (SubAgentResultDAO): Complete candidate carrying session and execution identity.
            terminal_reason (TerminalReason): Candidate cause recorded on the fleet entry.
            terminated_by (TerminatedBy): Cleanup owner recorded on the fleet entry.

        Returns:
            SubAgentResultDAO: The immutable winner for this incarnation.

        Raises:
            StaleExecutionError: If the session is unknown or the candidate names a
                superseded incarnation.
            ValueError: If the candidate status is not terminal.
        """
        entry: Optional[SubAgentStatusDAO] = self._current_entry(
            session_id=result.session_id, execution_id=result.execution_id
        )
        if entry is None:
            raise StaleExecutionError("terminal candidate does not name the current execution")
        if result.status not in TERMINAL_STATUSES:
            raise ValueError("terminal candidate must have a terminal status")
        winner: Optional[SubAgentResultDAO] = self._terminal_results.get(result.session_id)
        if winner is not None:
            return winner
        self._terminal_results[result.session_id] = result
        self._store[result.session_id] = entry.model_copy(
            update={
                "status": result.status,
                "last_text": result.answer,
                "exit_code": result.exit_code,
                "terminal_reason": terminal_reason,
                "terminated_by": terminated_by,
            }
        )
        self._persist()
        return result

    def terminal_result(self, *, session_id: str, execution_id: str) -> Optional[SubAgentResultDAO]:
        """Return the installed winner for the named current incarnation.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation the caller captured.

        Returns:
            Optional[SubAgentResultDAO]: The winner, or None before a commit or for
                an unknown or stale incarnation.
        """
        if self._current_entry(session_id=session_id, execution_id=execution_id) is None:
            return None
        return self._terminal_results.get(session_id)

    def record_terminal_evidence(self, *, session_id: str, execution_id: str, status_sha256: str) -> bool:
        """Publish terminal sibling evidence bound to the exact status.json bytes.

        WHAT: Replaces the sibling with phase terminal, the winner's status and the
            digest of the status bytes the process just wrote. Memory evidence always
            becomes terminal; the return value reports only the disk projection.
        WHO: Called by SubAgentProcess._publish_terminal after status.json commits.
        WHEN: After a successful status write, and again on a later publication of
            the same winner while the sibling projection has not committed.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation the caller captured.
            status_sha256 (str): SHA-256 of the exact status.json bytes.

        Returns:
            bool: True when the sibling projection committed (or no store is bound);
                False before a winner, for a stale incarnation, or after a write
                failure, so the caller retries only this projection.
        """
        winner: Optional[SubAgentResultDAO] = self.terminal_result(
            session_id=session_id, execution_id=execution_id
        )
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if winner is None or entry is None:
            return False
        return self._publish_evidence(
            evidence=self._current_evidence(entry=entry).terminal(
                status=winner.status, status_sha256=status_sha256
            )
        )

    def mark_terminal(
        self,
        *,
        session_id: str,
        execution_id: str,
        status: SubAgentStatus,
        answer: str,
        exit_code: int = -1,
        terminal_reason: Optional[TerminalReason] = None,
        terminated_by: Optional[TerminatedBy] = None,
    ) -> None:
        """Commit terminal evidence for callers that hold no complete result.

        WHAT: Compatibility adapter that builds a complete result from the arguments
            and delegates to commit_terminal; unknown or stale incarnations no-op.
        WHO: Called by HeadlessRunner's terminal straggler sweep and legacy callers.
            Result-bearing callers use commit_terminal through the process gateway.
        WHEN: When a sweep observes a child that no wrapper will publish.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation the caller captured.
            status (SubAgentStatus): Completed, failed, or aborted terminal status.
            answer (str): Final answer or redacted failure message.
            exit_code (int): Child process exit code. Defaults to -1 for legacy callers.
            terminal_reason (Optional[TerminalReason]): Ending reason; inferred when absent.
            terminated_by (Optional[TerminatedBy]): Cleanup owner; ``natural`` when absent.
        """
        entry: Optional[SubAgentStatusDAO] = self._current_entry(
            session_id=session_id, execution_id=execution_id
        )
        if entry is None:
            return
        resolved_reason: TerminalReason = terminal_reason or terminal_reason_for_status(status=status)  # type: ignore[assignment]
        self.commit_terminal(
            result=SubAgentResultDAO(
                task_id=entry.task_id,
                session_id=session_id,
                status=status,
                answer=answer,
                exit_code=exit_code,
                execution_id=execution_id,
            ),
            terminal_reason=resolved_reason,
            terminated_by=terminated_by or "natural",
        )

    def _current_entry(self, *, session_id: str, execution_id: str) -> Optional[SubAgentStatusDAO]:
        """Return the entry only when it belongs to the captured incarnation.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation the caller captured.

        Returns:
            Optional[SubAgentStatusDAO]: Current entry, or None when unknown or stale.
        """
        entry: Optional[SubAgentStatusDAO] = self._store.get(session_id)
        if entry is None or entry.execution_id != execution_id:
            return None
        return entry

    def _live_entry(self, *, session_id: str, execution_id: str) -> Optional[SubAgentStatusDAO]:
        """Return the current incarnation's entry only while it is not terminal.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation the caller captured.

        Returns:
            Optional[SubAgentStatusDAO]: Live entry, or None when unknown, stale or terminal.
        """
        entry: Optional[SubAgentStatusDAO] = self._current_entry(
            session_id=session_id, execution_id=execution_id
        )
        if entry is None or entry.status in TERMINAL_STATUSES:
            return None
        return entry

    def _update_live(self, *, session_id: str, execution_id: str, update: dict[str, object]) -> None:
        """Apply an in-memory telemetry update to a live current incarnation.

        Args:
            session_id (str): Registered child session identifier.
            execution_id (str): Incarnation the caller captured.
            update (dict[str, object]): Field values to copy into the entry.
        """
        entry: Optional[SubAgentStatusDAO] = self._live_entry(
            session_id=session_id, execution_id=execution_id
        )
        if entry is None:
            return
        self._store[session_id] = entry.model_copy(update=update)

    def _current_evidence(self, *, entry: SubAgentStatusDAO) -> ChildExecutionEvidenceDAO:
        """Return the retained evidence for an entry's incarnation.

        ``register`` is the only writer of new entries and retains pending evidence
        for the same incarnation first, so the lookup cannot miss.

        Args:
            entry (SubAgentStatusDAO): Current registry entry.

        Returns:
            ChildExecutionEvidenceDAO: Last evidence retained for that incarnation.
        """
        return self._evidence[entry.session_id]

    def _publish_evidence(self, *, evidence: ChildExecutionEvidenceDAO) -> bool:
        """Retain evidence in memory and mirror it to the bound projection.

        Args:
            evidence (ChildExecutionEvidenceDAO): Complete phase evidence.

        Returns:
            bool: True when the projection committed or no store is bound.
        """
        self._evidence[evidence.session_id] = evidence
        if self._fleet_store is None:
            return True
        return self._fleet_store.publish_execution(evidence=evidence)

    def _persist(self) -> None:
        """Mirror the current registry snapshot when a fleet store is bound.

        WHAT: Sends one complete ordered snapshot to the optional durable projection.
        WHO: Called by lifecycle transition methods after their memory update.
        WHEN: Never for high-frequency stdout, heartbeat, or text updates.
        """
        if self._fleet_store is None:
            return
        self._fleet_store.persist(entries=self.snapshot())

    def snapshot(self) -> list[SubAgentStatusDAO]:
        """Return registered fleet entries in registration order.

        WHAT: Provides a point-in-time projection of the in-memory registry.
        WHO: Called by fleet persistence and observer surfaces.
        WHEN: After lifecycle updates and while readers render fleet state.

        Returns:
            list[SubAgentStatusDAO]: Current entries in registration order.
        """
        return list(self._store.values())

    def get(self, *, session_id: str) -> Optional[SubAgentStatusDAO]:
        """Return one fleet entry when the session is registered.

        WHAT: Looks up a child entry without mutating the registry.
        WHO: Called by tests and observer surfaces.
        WHEN: While resolving one child status.

        Args:
            session_id (str): Child session identifier to look up.

        Returns:
            Optional[SubAgentStatusDAO]: Matching entry, or None when unknown.
        """
        return self._store.get(session_id)

    @property
    def count(self) -> int:
        """Return the total number of registered fleet entries."""
        return len(self._store)

    @property
    def running_count(self) -> int:
        """Return the number of entries currently marked running."""
        return sum(1 for entry in self._store.values() if entry.status == "running")
