"""Barrier tests for explicit dispatch generation in ``SubAgentPool`` (feature 94 a.2, T03).

The displayed attached group is the latest *admitted* batch, captured
explicitly through chain/run/register/lifecycle calls. Child events never
select a batch. Every wait below is an ``asyncio.Event`` barrier or a bounded
poll of loop turns; no test sleeps on wall-clock time, spawns a process or
touches a real terminal. Process execution is replaced at
``SubAgentProcess.run`` by a gate that publishes through the real
``_publish_terminal`` gateway, so registry/fleet projections stay real
(temp-owned history root).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.orchestrator.dao import (
    SubAgentResultDAO,
    SubAgentStatus,
    SubAgentTaskDAO,
    terminal_reason_for_status,
)
from src.agents.slo_agent.orchestrator.pool import SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess

_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_LIFECYCLE_KINDS: frozenset[str] = frozenset(
    {"sub_agent_spawned", "sub_agent_completed", "sub_agent_failed", "sub_agent_aborted", "sub_agent_reaped"}
)
_START: str = "sub_agent_dispatch_started"

RelayHook = Callable[[AgentStreamEventDAO], Awaitable[None]]


class _GatedRuns:
    """Replaces ``SubAgentProcess.run`` with per-session barriers.

    A gated session's run blocks until ``release`` names it; ungated sessions
    finish immediately. Each run publishes its terminal candidate through the
    wrapper's real gateway, so the pool emits the registry winner.
    """

    def __init__(
        self, *, gated: tuple[str, ...] = (), statuses: Optional[dict[str, SubAgentStatus]] = None
    ) -> None:
        self._gates: dict[str, asyncio.Event] = {session_id: asyncio.Event() for session_id in gated}
        self._statuses: dict[str, SubAgentStatus] = statuses or {}
        self.started: list[str] = []
        self.prompts: dict[str, str] = {}

    def as_method(self) -> Callable[[SubAgentProcess], Awaitable[SubAgentResultDAO]]:
        """Return a plain function that binds as ``SubAgentProcess.run`` (``self`` = process)."""

        async def run(process: SubAgentProcess) -> SubAgentResultDAO:
            return await self.run(process)

        return run

    def release(self, *, session_id: str) -> None:
        """Let one gated session's run finish."""
        self._gates[session_id].set()

    async def run(self, process: SubAgentProcess) -> SubAgentResultDAO:
        """Record the start, wait for the session's gate, then publish its winner."""
        self.started.append(process.session_id)
        self.prompts[process.session_id] = process.task.prompt
        gate: Optional[asyncio.Event] = self._gates.get(process.session_id)
        if gate is not None:
            await gate.wait()
        status: SubAgentStatus = self._statuses.get(process.session_id, "completed")
        candidate = SubAgentResultDAO(
            task_id=process.task.task_id,
            session_id=process.session_id,
            status=status,
            answer=f"answer-{process.session_id}",
            exit_code=0 if status == "completed" else 1,
            execution_id=process.execution_id,
        )
        return process._publish_terminal(
            candidate=candidate,
            terminal_reason=terminal_reason_for_status(status=status),  # type: ignore[arg-type]
            terminated_by="natural",
        )


def _pool(
    *, tmp_path: Path, hook: Optional[RelayHook] = None
) -> tuple[SubAgentPool, list[AgentStreamEventDAO]]:
    """Build a temp-rooted pool whose relay records events and may await a test hook."""
    relayed: list[AgentStreamEventDAO] = []

    async def relay(event: AgentStreamEventDAO) -> None:
        relayed.append(event)
        if hook is not None:
            await hook(event)

    pool = SubAgentPool(
        orchestrator_session_id="orch-1",
        default_model=None,
        relay=relay,
        owner_session_id="owner-1",
        run_id=_RUN_ID,
        history_root=tmp_path,
    )
    return pool, relayed


def _task(*, task_id: str, session_id: str, prompt: str = "do it") -> SubAgentTaskDAO:
    """Build one task bound to an explicit child session."""
    return SubAgentTaskDAO(task_id=task_id, prompt=prompt, session_id=session_id)


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield loop turns until ``predicate`` holds (bounded, no wall-clock sleeping)."""

    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=2.0)


def _snapshot_sessions(pool: SubAgentPool) -> list[str]:
    """Return the session ids of the latest attached group."""
    return [entry.session_id for entry in pool.attached_dispatch_snapshot().entries]


def _starts(relayed: list[AgentStreamEventDAO]) -> list[AgentStreamEventDAO]:
    """Return the dispatch start events in delivery order."""
    return [event for event in relayed if event.kind == _START]


def _registered(*, pool: SubAgentPool, session_id: str) -> bool:
    """Return whether the session has a registry entry."""
    return pool.registry.get(session_id=session_id) is not None


class TestStartEvent:
    """The stream-only start event is emitted once, before every child lifecycle event."""

    async def test_start_precedes_all_child_lifecycle_with_exact_metadata(self, tmp_path: Path) -> None:
        """Start carries exactly three keys; every lifecycle event carries the same batch identity."""
        pool, relayed = _pool(tmp_path=tmp_path)
        runs = _GatedRuns()

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            await pool.dispatch(
                mode="parallel",
                tasks=[_task(task_id="t1", session_id="a"), _task(task_id="t2", session_id="b")],
            )

        start = relayed[0]
        snapshot = pool.attached_dispatch_snapshot()
        assert start.kind == _START
        assert (start.sub_agent_id, start.task_id, start.content) == (None, None, None)
        assert start.metadata == {
            "orchestrator_session_id": "orch-1",
            "dispatch_id": snapshot.dispatch_id,
            "dispatch_sequence": 1,
        }
        lifecycle = [event for event in relayed if event.kind in _LIFECYCLE_KINDS]
        assert len(lifecycle) == 4 and len(_starts(relayed)) == 1
        executions = {entry.session_id: entry.execution_id for entry in snapshot.entries}
        for event in lifecycle:
            assert event.metadata == {
                "dispatch_id": snapshot.dispatch_id,
                "dispatch_sequence": 1,
                "execution_id": executions[event.sub_agent_id or ""],
            }

    async def test_execution_sibling_on_disk_names_the_announced_dispatch(self, tmp_path: Path) -> None:
        """The durable sibling records the batch the start event announced (a.4 sibling identity)."""
        pool, relayed = _pool(tmp_path=tmp_path)

        with patch.object(SubAgentProcess, "run", new=_GatedRuns().as_method()):
            await pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])

        start = _starts(relayed)[0]
        entry = pool.registry.get(session_id="a")
        sibling_path: Path = tmp_path / "orch-1" / "children" / "a" / "execution.v1.json"
        sibling = json.loads(sibling_path.read_text(encoding="utf-8"))
        assert entry is not None
        assert (sibling["phase"], sibling["dispatch_id"], sibling["execution_id"]) == (
            "terminal",
            start.metadata["dispatch_id"],
            entry.execution_id,
        )

    async def test_spawned_preview_uses_task_preview(self, tmp_path: Path) -> None:
        """The spawned event carries the normalized 150-code-point label (199 normalized → 149 + "…")."""
        pool, relayed = _pool(tmp_path=tmp_path)

        with patch.object(SubAgentProcess, "run", new=_GatedRuns().as_method()):
            await pool.dispatch(
                mode="single", tasks=[_task(task_id="t1", session_id="a", prompt="y\n" * 100)]
            )

        spawned = next(event for event in relayed if event.kind == "sub_agent_spawned")
        assert spawned.content == " ".join(["y"] * 100)[:149] + "…"


class TestBatchReplacement:
    """The latest admitted batch is displayed; older executions survive in the registry."""

    async def test_second_batch_replaces_group_while_first_child_lives(self, tmp_path: Path) -> None:
        """Old live child stays registered and wrapped but leaves the latest snapshot."""
        pool, relayed = _pool(tmp_path=tmp_path)
        runs = _GatedRuns(gated=("a",))

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            first = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])
            )
            await _until(lambda: "a" in runs.started)
            second = await pool.dispatch(mode="single", tasks=[_task(task_id="t2", session_id="b")])

            snapshot = pool.attached_dispatch_snapshot()
            assert (snapshot.dispatch_sequence, _snapshot_sessions(pool)) == (2, ["b"])
            old = pool.registry.get(session_id="a")
            assert old is not None and old.status == "pending"
            assert list(pool._active_by_session_id) == ["a"]

            runs.release(session_id="a")
            first_result = await first

        assert second.all_completed and first_result.all_completed
        assert _snapshot_sessions(pool) == ["b"]
        assert [entry.session_id for entry in pool.registry.snapshot()] == ["a", "b"]
        assert [event.metadata["dispatch_sequence"] for event in _starts(relayed)] == [1, 2]
        assert pool.registry.retained_dispatch_ids() == (snapshot.dispatch_id,)

    async def test_late_first_batch_chain_registration_cannot_restore_old_group(self, tmp_path: Path) -> None:
        """A chain step of batch 1 registered after batch 2 began joins batch 1 only."""
        pool, relayed = _pool(tmp_path=tmp_path)
        runs = _GatedRuns(gated=("a",))

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            chain = asyncio.create_task(
                pool.dispatch(
                    mode="chain",
                    tasks=[
                        _task(task_id="t1", session_id="a"),
                        _task(task_id="t2", session_id="late", prompt="after {previous}"),
                    ],
                )
            )
            await _until(lambda: "a" in runs.started)
            await pool.dispatch(mode="single", tasks=[_task(task_id="t3", session_id="b")])
            runs.release(session_id="a")
            result = await asyncio.wait_for(chain, timeout=2.0)

        assert [r.status for r in result.results] == ["completed", "completed"]
        assert runs.prompts["late"] == "after answer-a"
        assert _snapshot_sessions(pool) == ["b"]
        first_id = _starts(relayed)[0].metadata["dispatch_id"]
        late_events = [event for event in relayed if event.sub_agent_id == "late"]
        assert late_events and all(event.metadata["dispatch_id"] == first_id for event in late_events)
        assert all(event.metadata["dispatch_sequence"] == 1 for event in late_events)

    async def test_empty_valid_dispatch_replaces_group(self, tmp_path: Path) -> None:
        """An admitted empty batch emits start and shows an empty latest group."""
        pool, relayed = _pool(tmp_path=tmp_path)

        with patch.object(SubAgentProcess, "run", new=_GatedRuns().as_method()):
            await pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])
            result = await pool.dispatch(mode="parallel", tasks=[])

        snapshot = pool.attached_dispatch_snapshot()
        assert result.all_completed and result.results == []
        assert (snapshot.dispatch_sequence, snapshot.entries) == (2, ())
        assert len(_starts(relayed)) == 2
        assert _registered(pool=pool, session_id="a")


class TestAdmissionOrder:
    """Preparation completion, not coroutine invocation, orders admission."""

    async def test_slower_preparation_is_admitted_later_and_displayed(self, tmp_path: Path) -> None:
        """Dispatch X invoked first but resolved last gets the higher sequence and is latest."""
        pool, relayed = _pool(tmp_path=tmp_path)
        resolve_gate = asyncio.Event()
        original = pool._resolve_child_session_id

        async def resolve(*, task: SubAgentTaskDAO) -> str:
            if task.task_id == "slow":
                await resolve_gate.wait()
            return await original(task=task)

        with (
            patch.object(SubAgentProcess, "run", new=_GatedRuns().as_method()),
            patch.object(pool, "_resolve_child_session_id", new=resolve),
        ):
            slow = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="slow", session_id="x")])
            )
            await asyncio.sleep(0)
            await pool.dispatch(mode="single", tasks=[_task(task_id="fast", session_id="y")])
            assert _snapshot_sessions(pool) == ["y"]
            resolve_gate.set()
            await slow

        sequences = {
            event.metadata["dispatch_sequence"]: event.metadata["dispatch_id"] for event in _starts(relayed)
        }
        assert sorted(sequences) == [1, 2]
        assert _snapshot_sessions(pool) == ["x"]
        assert pool.attached_dispatch_snapshot().dispatch_id == sequences[2]

    async def test_cancellation_during_preparation_admits_nothing(self, tmp_path: Path) -> None:
        """No start, no sequence, no registration and no reservation survive a cancelled preparation."""
        pool, relayed = _pool(tmp_path=tmp_path)
        entered = asyncio.Event()

        async def resolve(*, task: SubAgentTaskDAO) -> str:
            entered.set()
            await asyncio.Event().wait()
            return "never"

        with patch.object(pool, "_resolve_child_session_id", new=resolve):
            pending = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])
            )
            await asyncio.wait_for(entered.wait(), timeout=2.0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending

        assert relayed == [] and pool.registry.count == 0
        assert pool.attached_dispatch_snapshot().dispatch_sequence == 0
        with patch.object(SubAgentProcess, "run", new=_GatedRuns().as_method()):
            reused = await pool.dispatch(mode="single", tasks=[_task(task_id="t2", session_id="a")])
        assert reused.all_completed

    async def test_seal_during_preparation_is_rechecked_at_admission(self, tmp_path: Path) -> None:
        """A pool sealed while a batch prepares refuses it without beginning a dispatch."""
        pool, relayed = _pool(tmp_path=tmp_path)
        resolve_gate = asyncio.Event()

        async def resolve(*, task: SubAgentTaskDAO) -> str:
            await resolve_gate.wait()
            return task.session_id or "x"

        with patch.object(pool, "_resolve_child_session_id", new=resolve):
            pending = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])
            )
            await asyncio.sleep(0)
            await pool.abort_and_drain()
            resolve_gate.set()
            result = await pending

        assert (result.all_completed, result.failed_task_ids) == (False, ["t1"])
        assert result.error is not None and "sealed" in result.error
        assert relayed == [] and pool.attached_dispatch_snapshot().dispatch_sequence == 0


class TestRejectedBatches:
    """Rejected batches never begin a dispatch, emit start, spawn or leak a reservation."""

    async def test_duplicate_session_ids_in_batch_are_rejected(self, tmp_path: Path) -> None:
        """Two tasks resolving to one session refuse the whole batch before begin_dispatch."""
        pool, relayed = _pool(tmp_path=tmp_path)
        runs = _GatedRuns()

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            result = await pool.dispatch(
                mode="parallel",
                tasks=[_task(task_id="t1", session_id="dup"), _task(task_id="t2", session_id="dup")],
            )
            assert (result.all_completed, result.results, result.failed_task_ids) == (False, [], ["t1", "t2"])
            assert result.error == "duplicate child session in dispatch; no sub-agents were started"
            assert relayed == [] and runs.started == [] and pool.registry.count == 0
            assert pool.attached_dispatch_snapshot().dispatch_sequence == 0
            accepted = await pool.dispatch(mode="single", tasks=[_task(task_id="t3", session_id="dup")])

        assert accepted.all_completed

    async def test_live_session_reuse_is_rejected_and_group_kept(self, tmp_path: Path) -> None:
        """A batch naming a nonterminal child is refused; the displayed batch does not change."""
        pool, relayed = _pool(tmp_path=tmp_path)
        runs = _GatedRuns(gated=("a",))

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            first = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])
            )
            await _until(lambda: "a" in runs.started)
            before = pool.attached_dispatch_snapshot()
            refused = await pool.dispatch(
                mode="parallel",
                tasks=[_task(task_id="t2", session_id="c"), _task(task_id="t3", session_id="a")],
            )
            assert refused.error == "child session already executing in this pool; no sub-agents were started"
            assert pool.attached_dispatch_snapshot() == before
            assert len(_starts(relayed)) == 1 and not _registered(pool=pool, session_id="c")
            runs.release(session_id="a")
            await first

        assert runs.started == ["a"]

    async def test_reserved_unstarted_chain_session_is_rejected(self, tmp_path: Path) -> None:
        """A later chain step's session is reserved at admission even before it registers."""
        pool, _ = _pool(tmp_path=tmp_path)
        runs = _GatedRuns(gated=("a",))

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            chain = asyncio.create_task(
                pool.dispatch(
                    mode="chain",
                    tasks=[_task(task_id="t1", session_id="a"), _task(task_id="t2", session_id="b")],
                )
            )
            await _until(lambda: "a" in runs.started)
            refused = await pool.dispatch(mode="single", tasks=[_task(task_id="t3", session_id="b")])
            runs.release(session_id="a")
            await chain

        assert refused.error == "child session already executing in this pool; no sub-agents were started"
        assert runs.started == ["a", "b"]

    async def test_unsafe_resolved_session_rejects_batch(self, tmp_path: Path) -> None:
        """A session id unsafe as a path component refuses the batch before admission."""
        pool, relayed = _pool(tmp_path=tmp_path)

        result = await pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="../escape")])

        assert (result.all_completed, result.failed_task_ids) == (False, ["t1"])
        assert result.error == "unsafe child session id; no sub-agents were started"
        assert relayed == [] and pool.registry.count == 0


class TestReservationLifetime:
    """Reservations end only at the documented teardown barriers."""

    async def test_chain_stop_releases_unused_reservation(self, tmp_path: Path) -> None:
        """A noncompleted step stops the chain (A4-F02); the never-run step's session is free again."""
        pool, relayed = _pool(tmp_path=tmp_path)
        runs = _GatedRuns(statuses={"a": "failed"})

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            result = await pool.dispatch(
                mode="chain",
                tasks=[_task(task_id="t1", session_id="a"), _task(task_id="t2", session_id="b")],
            )
            assert [r.task_id for r in result.results] == ["t1"]
            assert runs.started == ["a"] and not _registered(pool=pool, session_id="b")
            reuse = await pool.dispatch(mode="single", tasks=[_task(task_id="t3", session_id="b")])

        assert reuse.all_completed
        assert runs.started == ["a", "b"]

    async def test_started_reservation_held_until_terminal_event_settles(self, tmp_path: Path) -> None:
        """A terminal registry entry is still reserved while its terminal lifecycle event is in flight."""
        terminal_seen = asyncio.Event()
        release_terminal = asyncio.Event()

        async def hook(event: AgentStreamEventDAO) -> None:
            if (
                event.kind == "sub_agent_completed"
                and event.sub_agent_id == "a"
                and not release_terminal.is_set()
            ):
                terminal_seen.set()
                await release_terminal.wait()

        pool, _ = _pool(tmp_path=tmp_path, hook=hook)
        runs = _GatedRuns()

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            first = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])
            )
            await asyncio.wait_for(terminal_seen.wait(), timeout=2.0)
            entry = pool.registry.get(session_id="a")
            assert entry is not None and entry.status == "completed"
            refused = await asyncio.wait_for(
                pool.dispatch(mode="single", tasks=[_task(task_id="t2", session_id="a")]), timeout=2.0
            )
            release_terminal.set()
            await first
            reused = await pool.dispatch(mode="single", tasks=[_task(task_id="t3", session_id="a")])

        assert refused.error == "child session already executing in this pool; no sub-agents were started"
        assert reused.all_completed

    async def test_terminal_reuse_after_teardown_creates_new_incarnation(self, tmp_path: Path) -> None:
        """Safe reuse allocates a new execution; the old batch's membership is pruned."""
        pool, relayed = _pool(tmp_path=tmp_path)

        with patch.object(SubAgentProcess, "run", new=_GatedRuns().as_method()):
            await pool.dispatch(mode="single", tasks=[_task(task_id="t1", session_id="a")])
            old = pool.attached_dispatch_snapshot()
            await pool.dispatch(mode="single", tasks=[_task(task_id="t2", session_id="a")])

        new = pool.attached_dispatch_snapshot()
        assert old.entries[0].execution_id != new.entries[0].execution_id
        assert [(e.session_id, e.task_id, e.status) for e in new.entries] == [("a", "t2", "completed")]
        assert pool.registry.retained_dispatch_ids() == (new.dispatch_id,)

    async def test_cancellation_after_admission_releases_every_reservation(self, tmp_path: Path) -> None:
        """Cancelling while the start event is delivered releases reserved sessions and retires the batch."""
        started = asyncio.Event()

        async def hook(event: AgentStreamEventDAO) -> None:
            if event.kind == _START and event.metadata["dispatch_sequence"] == 1:
                started.set()
                await asyncio.Event().wait()

        pool, relayed = _pool(tmp_path=tmp_path, hook=hook)
        runs = _GatedRuns()

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            pending = asyncio.create_task(
                pool.dispatch(
                    mode="parallel",
                    tasks=[_task(task_id="t1", session_id="a"), _task(task_id="t2", session_id="b")],
                )
            )
            await asyncio.wait_for(started.wait(), timeout=2.0)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert runs.started == [] and pool.registry.count == 0
            reused = await pool.dispatch(
                mode="parallel",
                tasks=[_task(task_id="t3", session_id="a"), _task(task_id="t4", session_id="b")],
            )

        assert reused.all_completed
        assert pool.registry.retained_dispatch_ids() == (pool.attached_dispatch_snapshot().dispatch_id,)

    async def test_cancellation_mid_batch_releases_started_and_unstarted_sessions(
        self, tmp_path: Path
    ) -> None:
        """Cancelling a running parallel batch frees both sessions once their children settle."""
        pool, _ = _pool(tmp_path=tmp_path)
        runs = _GatedRuns(gated=("a", "b"))

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            pending = asyncio.create_task(
                pool.dispatch(
                    mode="parallel",
                    tasks=[_task(task_id="t1", session_id="a"), _task(task_id="t2", session_id="b")],
                )
            )
            await _until(lambda: len(runs.started) == 2)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert pool._active_by_session_id == {}
            for session_id in ("a", "b"):
                entry = pool.registry.get(session_id=session_id)
                if entry is not None and entry.status not in {"completed", "failed", "aborted"}:
                    pool.registry.commit_terminal(
                        result=SubAgentResultDAO(
                            task_id="t",
                            session_id=session_id,
                            status="aborted",
                            execution_id=entry.execution_id,
                        ),
                        terminal_reason="operator_abort",
                        terminated_by="abort",
                    )
            runs.release(session_id="a")
            reused = await pool.dispatch(mode="single", tasks=[_task(task_id="t3", session_id="a")])

        assert reused.all_completed

    async def test_finishing_dispatch_never_releases_a_session_reused_by_a_newer_dispatch(
        self, tmp_path: Path
    ) -> None:
        """Dispatch teardown releases only sessions it never started, not a reservation now held by another batch."""
        second_terminal_seen = asyncio.Event()
        release_second_terminal = asyncio.Event()

        async def hook(event: AgentStreamEventDAO) -> None:
            if (
                event.kind == "sub_agent_completed"
                and event.sub_agent_id == "a"
                and event.metadata["dispatch_sequence"] == 2
            ):
                second_terminal_seen.set()
                await release_second_terminal.wait()

        pool, relayed = _pool(tmp_path=tmp_path, hook=hook)
        runs = _GatedRuns(gated=("b",))

        def first_a_torn_down() -> bool:
            completed = [e for e in relayed if e.kind == "sub_agent_completed" and e.sub_agent_id == "a"]
            return bool(completed) and "a" not in pool._active_by_session_id

        with patch.object(SubAgentProcess, "run", new=runs.as_method()):
            first = asyncio.create_task(
                pool.dispatch(
                    mode="parallel",
                    tasks=[_task(task_id="t1", session_id="a"), _task(task_id="t2", session_id="b")],
                )
            )
            await _until(first_a_torn_down)
            second = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[_task(task_id="t3", session_id="a")])
            )
            await asyncio.wait_for(second_terminal_seen.wait(), timeout=2.0)
            runs.release(session_id="b")
            await asyncio.wait_for(first, timeout=2.0)

            entry = pool.registry.get(session_id="a")
            assert entry is not None and entry.status == "completed"
            refused = await asyncio.wait_for(
                pool.dispatch(mode="single", tasks=[_task(task_id="t4", session_id="a")]), timeout=2.0
            )
            release_second_terminal.set()
            await asyncio.wait_for(second, timeout=2.0)

        assert refused.error == "child session already executing in this pool; no sub-agents were started"
