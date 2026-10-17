"""Terminal arbitration before every cache and durable projection (feature 94.a.4, T02).

Orchestration and adapter tests over a real ``ProcessRegistry`` bound to a real
temp-owned ``FleetStore``. The OS boundary is replaced by a controlled fake child
and an injected ``FleetReaper``; no subprocess, signal, provider or user history
is touched. Every write resolves below ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from src.agents.slo_agent.history.atomic_io import AtomicFileWriter
from src.agents.slo_agent.orchestrator.dao import (
    ChildExecutionEvidenceDAO,
    ExecutionIndexDAO,
    SubAgentResultDAO,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.fleet_store import FleetStore
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.orchestrator.reaper import ReapOutcome
from src.agents.slo_agent.orchestrator.registry import ProcessRegistry, StaleExecutionError
from tests.agents.slo_agent.orchestrator.fake_child import FakeChildProcess, terminal_line
from tests.agents.slo_agent.orchestrator.released_schemas import (
    ReleasedFleetSnapshotDAO,
    ReleasedSpawnContextDAO,
    ReleasedSubAgentResultDAO,
)

_PARENT: str = "orch-1"
_CHILD: str = "child-1"
_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"
_BOUNDED_SECONDS: float = 2.0
"""Bounded wait for operations that must not block; never a timing oracle."""


class _Harness:
    """One registered incarnation wired to temp-owned durable projections."""

    def __init__(self, *, tmp_path: Path) -> None:
        self.root: Path = tmp_path
        self.store: FleetStore = FleetStore(
            history_root=tmp_path, orchestrator_session_id=_PARENT, run_id=_RUN_ID
        )
        self.registry: ProcessRegistry = ProcessRegistry(fleet_store=self.store)
        self.task: SubAgentTaskDAO = SubAgentTaskDAO(task_id="t1", prompt="do the work")
        self.execution_id: str = self.registry.register(task_id="t1", session_id=_CHILD, task=self.task)
        self.process: SubAgentProcess = self.build_process(execution_id=self.execution_id)

    def build_process(self, *, execution_id: str) -> SubAgentProcess:
        async def relay(event: AgentStreamEventDAO) -> None:
            return None

        return SubAgentProcess(
            task=self.task,
            session_id=_CHILD,
            model=None,
            relay=relay,
            registry=self.registry,
            parent_session_id=_PARENT,
            history_root=self.root,
            execution_id=execution_id,
        )

    @property
    def child_dir(self) -> Path:
        return self.root / _PARENT / "children" / _CHILD

    def status_bytes(self) -> bytes:
        return (self.child_dir / "status.json").read_bytes()

    def verified(self) -> Optional[ChildExecutionEvidenceDAO]:
        return FleetStore.load_verified_execution(
            history_root=self.root, orchestrator_session_id=_PARENT, child_session_id=_CHILD
        )

    def assert_projections_agree(self, *, winner: SubAgentResultDAO) -> None:
        """Result, registry, wrapper cache, status.json, fleet.json and evidence agree."""
        entry = self.registry.get(session_id=_CHILD)
        assert entry is not None
        assert (entry.status, entry.exit_code, entry.last_text, entry.execution_id) == (
            winner.status,
            winner.exit_code,
            winner.answer,
            winner.execution_id,
        )
        assert self.registry.terminal_result(session_id=_CHILD, execution_id=self.execution_id) == winner
        assert self.process._terminal_result_built == winner
        status = ReleasedSubAgentResultDAO.model_validate_json(self.status_bytes())
        assert (status.status, status.exit_code, status.answer, status.failure_code) == (
            winner.status,
            winner.exit_code,
            winner.answer,
            winner.failure_code,
        )
        fleet = ReleasedFleetSnapshotDAO.model_validate_json(
            (self.root / _PARENT / "fleet.json").read_bytes()
        )
        assert (fleet.entries[0].status, fleet.entries[0].exit_code) == (winner.status, winner.exit_code)
        index = ExecutionIndexDAO.model_validate_json(
            (self.root / _PARENT / "execution-index.v1.json").read_bytes()
        )
        assert index.executions[_CHILD] == winner.execution_id
        evidence = self.verified()
        assert evidence is not None
        assert (evidence.phase, evidence.status, evidence.execution_id) == (
            "terminal",
            winner.status,
            winner.execution_id,
        )
        assert evidence.status_sha256 == hashlib.sha256(self.status_bytes()).hexdigest()


def _aborted_candidate(harness: _Harness) -> SubAgentResultDAO:
    return SubAgentResultDAO(
        task_id="t1",
        session_id=_CHILD,
        status="aborted",
        answer="aborted by operator before child spawn",
        exit_code=2,
        execution_id=harness.execution_id,
    )


def _gated_reap(
    *, outcome: ReapOutcome, release: asyncio.Event, calls: list[int]
) -> Callable[..., Awaitable[ReapOutcome]]:
    async def reap(*, pid: int) -> ReapOutcome:
        calls.append(pid)
        await release.wait()
        return outcome

    return reap


async def _wait_for(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until a state predicate holds, bounded by a deadline."""

    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=_BOUNDED_SECONDS)


class TestPendingPublication:
    """finish_without_spawn is a synchronous third publisher (CRITICAL-1, AMBIGUOUS-1)."""

    async def test_pending_publication_does_not_wait_reap_settlement(self, tmp_path: Path) -> None:
        """Direct pending publication completes although settlement is (invalidly) cleared."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        harness.process._cancel_settled.clear()  # sensitivity check, not a supported state

        winner: SubAgentResultDAO = await asyncio.wait_for(
            harness.process.finish_without_spawn(
                result=_aborted_candidate(harness), terminal_reason="operator_abort", terminated_by="abort"
            ),
            timeout=_BOUNDED_SECONDS,
        )

        assert not harness.process._cancel_settled.is_set()
        assert (winner.status, winner.exit_code) == ("aborted", 2)
        harness.assert_projections_agree(winner=winner)
        evidence = harness.verified()
        assert evidence is not None and evidence.stdout_identity is None

    @pytest.mark.parametrize("with_handle", [False, True])
    async def test_pending_publication_rejects_spawn_entry(self, tmp_path: Path, with_handle: bool) -> None:
        """After spawn entry the pending path raises before any registry, cache or file change."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        harness.process._spawn_in_progress = True
        if with_handle:
            harness.process._proc = FakeChildProcess(lines=[])  # type: ignore[assignment]
        evidence_before = harness.verified()

        with pytest.raises(RuntimeError, match="pending publication after spawn entry"):
            await harness.process.finish_without_spawn(
                result=_aborted_candidate(harness), terminal_reason="operator_abort", terminated_by="abort"
            )

        entry = harness.registry.get(session_id=_CHILD)
        assert entry is not None and entry.status == "pending"
        assert harness.registry.terminal_result(session_id=_CHILD, execution_id=harness.execution_id) is None
        assert harness.process._terminal_result_built is None
        assert not (harness.child_dir / "status.json").exists()
        assert harness.verified() == evidence_before

    async def test_pre_run_cancel_latch_publishes_pending_abort_without_spawn(self, tmp_path: Path) -> None:
        """A cancel admitted before run entry latches; run publishes directly and never spawns."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        spawn: AsyncMock = AsyncMock(side_effect=AssertionError("spawn must not be reached"))

        with (
            patch("asyncio.create_subprocess_exec", new=spawn),
            patch("src.agents.slo_agent.orchestrator.process.FleetReaper.reap", new=AsyncMock()) as reap,
        ):
            outcome: Optional[ReapOutcome] = await harness.process.cancel()
            winner: SubAgentResultDAO = await asyncio.wait_for(
                harness.process.run(), timeout=_BOUNDED_SECONDS
            )

        assert outcome == "already_dead"
        spawn.assert_not_awaited()
        reap.assert_not_awaited()
        assert (winner.status, winner.exit_code) == ("aborted", 2)
        assert harness.process._cancel_settled.is_set()
        harness.assert_projections_agree(winner=winner)


class TestSpawnedPublication:
    """Spawned completion publishes only after the active reaper settles."""

    @pytest.mark.parametrize(
        ("reap_outcome", "expected_status"),
        [
            ("graceful", "aborted"),
            ("killed", "aborted"),
            ("unresolved", "completed"),
            ("already_dead", "completed"),
        ],
    )
    async def test_spawned_publication_waits_active_reaper(
        self, tmp_path: Path, reap_outcome: ReapOutcome, expected_status: str
    ) -> None:
        """A ready natural candidate waits for reap; only confirmed termination commits abort."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line()], exit_code=0)
        release: asyncio.Event = asyncio.Event()
        reap_calls: list[int] = []

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome",
                return_value="matching",
            ),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.reap",
                new=_gated_reap(outcome=reap_outcome, release=release, calls=reap_calls),
            ),
        ):
            run_task: asyncio.Task[SubAgentResultDAO] = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            cancel_task: asyncio.Task[Optional[ReapOutcome]] = asyncio.create_task(harness.process.cancel())
            await _wait_for(lambda: bool(reap_calls))
            child.exit()
            await _wait_for(
                lambda: not harness.process._cancel_settled.is_set() and child.returncode is not None
            )
            for _ in range(5):
                await asyncio.sleep(0)

            assert not run_task.done()
            entry = harness.registry.get(session_id=_CHILD)
            assert entry is not None and entry.status == "running"
            assert harness.process._terminal_result_built is None
            assert not (harness.child_dir / "status.json").exists()

            release.set()
            winner: SubAgentResultDAO = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)
            assert await cancel_task == reap_outcome

        assert winner.status == expected_status
        assert reap_calls == [child.pid]
        harness.assert_projections_agree(winner=winner)

    async def test_natural_winner_is_kept_when_reap_succeeds_late(self, tmp_path: Path) -> None:
        """An exit observed before the cancel worker keeps the natural candidate; no signal."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="natural")], exit_code=0)

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.reap",
                new=AsyncMock(return_value="graceful"),
            ) as reap,
        ):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            child.exit()
            winner: SubAgentResultDAO = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)
            outcome = await harness.process.cancel()

        assert outcome is None
        reap.assert_not_awaited()
        assert (winner.status, winner.answer) == ("completed", "natural")
        harness.assert_projections_agree(winner=winner)

    async def test_duplicate_cancellation_joins_one_reap(self, tmp_path: Path) -> None:
        """Concurrent whole/child cancel callers share one reap task and one winner."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[], exit_code=-15)
        release: asyncio.Event = asyncio.Event()
        reap_calls: list[int] = []

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome",
                return_value="matching",
            ),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.reap",
                new=_gated_reap(outcome="graceful", release=release, calls=reap_calls),
            ),
        ):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            first = asyncio.create_task(harness.process.cancel())
            second = asyncio.create_task(harness.process.cancel())
            await _wait_for(lambda: bool(reap_calls))
            child.exit()
            release.set()
            outcomes = await asyncio.gather(first, second)
            winner = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)

        assert outcomes == ["graceful", "graceful"]
        assert reap_calls == [child.pid]
        assert (winner.status, winner.exit_code) == ("aborted", 2)
        harness.assert_projections_agree(winner=winner)

    async def test_spawn_failure_publishes_failed_winner(self, tmp_path: Path) -> None:
        """A spawn failure is a natural candidate published through the same gateway."""
        harness: _Harness = _Harness(tmp_path=tmp_path)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=OSError("spawn failed"))):
            winner: SubAgentResultDAO = await asyncio.wait_for(
                harness.process.run(), timeout=_BOUNDED_SECONDS
            )

        assert (winner.status, winner.exit_code) == ("failed", 1)
        harness.assert_projections_agree(winner=winner)
        evidence = harness.verified()
        assert evidence is not None
        assert (evidence.stdout_identity, evidence.spawn_context_sha256) == (None, None)


def _exiting_gated_reap(
    *, child: FakeChildProcess, release: asyncio.Event, calls: list[int]
) -> Callable[..., Awaitable[ReapOutcome]]:
    """Return a reap that waits for release, then ends the child as a confirmed kill."""

    async def reap(*, pid: int) -> ReapOutcome:
        calls.append(pid)
        await release.wait()
        child.exit()
        return "killed"

    return reap


class TestInactivityPublication:
    """An inactivity reap never claims an operator abort, even when a whole abort joins."""

    @pytest.mark.parametrize("whole_abort_joins", [False, True])
    async def test_inactivity_reap_publishes_failed_winner(
        self, tmp_path: Path, whole_abort_joins: bool
    ) -> None:
        """A confirmed inactivity kill waits for settlement and publishes failed/1, natural."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[], exit_code=-9)
        child.stdout.readline = AsyncMock(side_effect=asyncio.TimeoutError)
        release: asyncio.Event = asyncio.Event()
        reap_calls: list[int] = []

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome",
                return_value="matching",
            ),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.reap",
                new=_exiting_gated_reap(child=child, release=release, calls=reap_calls),
            ),
        ):
            run_task: asyncio.Task[SubAgentResultDAO] = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: bool(reap_calls))
            cancel_task: Optional[asyncio.Task[Optional[ReapOutcome]]] = (
                asyncio.create_task(harness.process.cancel()) if whole_abort_joins else None
            )
            for _ in range(5):
                await asyncio.sleep(0)

            assert not run_task.done()
            entry = harness.registry.get(session_id=_CHILD)
            assert entry is not None and entry.status == "running"
            assert not (harness.child_dir / "status.json").exists()
            assert not harness.process._cancel_settled.is_set()

            release.set()
            winner: SubAgentResultDAO = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)
            if cancel_task is not None:
                assert await cancel_task == "killed"

        assert (winner.status, winner.exit_code) == ("failed", 1)
        assert winner.answer is not None and winner.answer.startswith("TimeoutError:")
        settled = harness.registry.get(session_id=_CHILD)
        assert settled is not None and settled.terminated_by == "natural"
        assert reap_calls == [child.pid]
        harness.assert_projections_agree(winner=winner)


class TestPreSpawnFailure:
    """A failure before the spawn call still releases cancellers waiting on spawn entry."""

    @pytest.mark.parametrize("failing_step", ["credential", "environment"])
    async def test_cancel_after_pre_spawn_failure_returns_promptly(
        self, tmp_path: Path, failing_step: str
    ) -> None:
        """Credential/env failure publishes failed; a later cancel settles with no reap."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        # A spawn here would be a test defect; fail loudly instead of streaming a mock.
        spawn: AsyncMock = AsyncMock(side_effect=AssertionError("spawn must not be reached"))
        # Patch the wrapper instance, not the module path: test_process reloads the module.
        failure = (
            patch("src.agents.slo_agent.orchestrator.process.CredentialResolver.resolve")
            if failing_step == "credential"
            else patch.object(harness.process, "_build_child_spawn_env")
        )

        with (
            failure as failing,
            patch("asyncio.create_subprocess_exec", new=spawn),
            patch("src.agents.slo_agent.orchestrator.process.FleetReaper.reap", new=AsyncMock()) as reap,
        ):
            failing.side_effect = RuntimeError("setup failed")
            winner: SubAgentResultDAO = await asyncio.wait_for(
                harness.process.run(), timeout=_BOUNDED_SECONDS
            )
            outcome: Optional[ReapOutcome] = await asyncio.wait_for(
                harness.process.cancel(), timeout=_BOUNDED_SECONDS
            )

        assert outcome is None
        assert harness.process._cancel_settled.is_set()
        assert harness.process._spawn_in_progress
        spawn.assert_not_awaited()
        reap.assert_not_awaited()
        assert (winner.status, winner.exit_code) == ("failed", 1)
        harness.assert_projections_agree(winner=winner)


class TestCompetingCandidates:
    """The first complete candidate wins every projection; later candidates cannot regress it."""

    def test_failure_envelope_winner_survives_abort_candidate(self, tmp_path: Path) -> None:
        """A committed provider failure keeps its envelope in result, status and fleet."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        failure: SubAgentResultDAO = SubAgentResultDAO(
            task_id="t1",
            session_id=_CHILD,
            status="failed",
            answer="partial",
            exit_code=1,
            failure_code="provider_stream_interrupted",
            partial_output_committed=True,
            attempts=2,
            safe_message="Provider stream interrupted; inspect durable artifacts before continuing.",
            execution_id=harness.execution_id,
        )
        first = harness.process._publish_terminal(
            candidate=failure, terminal_reason="failed", terminated_by="natural"
        )

        second = harness.process._publish_terminal(
            candidate=_aborted_candidate(harness), terminal_reason="operator_abort", terminated_by="abort"
        )

        assert first == second == failure
        harness.assert_projections_agree(winner=failure)
        assert ReleasedSubAgentResultDAO.model_validate_json(harness.status_bytes()).attempts == 2

    def test_stale_wrapper_cannot_publish(self, tmp_path: Path) -> None:
        """A wrapper of a superseded incarnation is refused before cache or file writes."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        harness.process._publish_terminal(
            candidate=_aborted_candidate(harness), terminal_reason="operator_abort", terminated_by="abort"
        )
        stale_execution: str = harness.execution_id
        harness.execution_id = harness.registry.register(task_id="t1", session_id=_CHILD, task=harness.task)
        stale: SubAgentProcess = harness.build_process(execution_id=stale_execution)
        status_before: bytes = harness.status_bytes()

        with pytest.raises(StaleExecutionError):
            stale._publish_terminal(
                candidate=_aborted_candidate(harness).model_copy(update={"execution_id": stale_execution}),
                terminal_reason="operator_abort",
                terminated_by="abort",
            )

        assert stale._terminal_result_built is None
        assert harness.status_bytes() == status_before
        entry = harness.registry.get(session_id=_CHILD)
        assert entry is not None and (entry.status, entry.execution_id) == ("pending", harness.execution_id)


class TestProjectionFailures:
    """Writer failures retain memory truth and leave disk observation stale, never complete."""

    def test_status_write_failure_retains_winner_and_retries_same_winner(self, tmp_path: Path) -> None:
        """A failed status write keeps the winner; a retry writes only that winner."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        real_write = AtomicFileWriter.write_text

        def fail_status(*, path: Path, text: str, private: bool = True) -> None:
            if path.name == "status.json":
                raise OSError("disk full")
            real_write(path=path, text=text, private=private)

        with (
            patch(
                "src.agents.slo_agent.orchestrator.process.AtomicFileWriter.write_text",
                side_effect=fail_status,
            ),
            patch("src.agents.slo_agent.orchestrator.process.log_warning") as warning,
        ):
            winner = harness.process._publish_terminal(
                candidate=_aborted_candidate(harness), terminal_reason="operator_abort", terminated_by="abort"
            )

        assert warning.call_args.kwargs["msg"] == "child_status_write_failed"
        assert "disk full" not in str(warning.call_args)
        assert (
            harness.registry.terminal_result(session_id=_CHILD, execution_id=harness.execution_id) == winner
        )
        assert harness.process._terminal_result_built == winner
        assert not (harness.child_dir / "status.json").exists()
        evidence = harness.verified()
        assert evidence is not None and evidence.phase == "pending"

        natural = SubAgentResultDAO(
            task_id="t1",
            session_id=_CHILD,
            status="completed",
            answer="late",
            exit_code=0,
            execution_id=harness.execution_id,
        )
        retried = harness.process._publish_terminal(
            candidate=natural, terminal_reason="completed", terminated_by="natural"
        )

        assert retried == winner
        harness.assert_projections_agree(winner=winner)

    def test_fleet_write_failure_retains_winner_and_status(self, tmp_path: Path) -> None:
        """A failed fleet projection does not block the winner's status projection."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        real_write = AtomicFileWriter.write_text

        def fail_fleet(*, path: Path, text: str, private: bool = True) -> None:
            if path.name == "fleet.json":
                raise OSError("disk full")
            real_write(path=path, text=text, private=private)

        with patch(
            "src.agents.slo_agent.orchestrator.fleet_store.AtomicFileWriter.write_text",
            side_effect=fail_fleet,
        ):
            winner = harness.process._publish_terminal(
                candidate=_aborted_candidate(harness), terminal_reason="operator_abort", terminated_by="abort"
            )

        entry = harness.registry.get(session_id=_CHILD)
        assert entry is not None and entry.status == "aborted"
        assert ReleasedSubAgentResultDAO.model_validate_json(harness.status_bytes()).status == "aborted"
        fleet = ReleasedFleetSnapshotDAO.model_validate_json((tmp_path / _PARENT / "fleet.json").read_bytes())
        assert fleet.entries[0].status == "pending"
        assert winner.status == "aborted"

    def test_pending_sibling_write_failure_never_verifies(self, tmp_path: Path) -> None:
        """Without a pending sibling, a new reader shows nothing for the incarnation."""
        with patch.object(FleetStore, "publish_execution", return_value=False):
            harness: _Harness = _Harness(tmp_path=tmp_path)

        assert harness.verified() is None

    async def test_running_sibling_write_failure_stays_pending(self, tmp_path: Path) -> None:
        """If running evidence fails to publish, readers keep waiting instead of trusting output."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[], exit_code=0)
        real_publish = FleetStore.publish_execution

        def fail_running(self: FleetStore, *, evidence: ChildExecutionEvidenceDAO) -> bool:
            if evidence.phase == "running":
                return False
            return real_publish(self, evidence=evidence)

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch.object(FleetStore, "publish_execution", new=fail_running),
        ):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            evidence = harness.verified()
            child.exit()
            await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)

        assert evidence is not None and evidence.phase == "pending"
        entry = harness.registry.get(session_id=_CHILD)
        assert entry is not None and entry.status == "completed"

    async def test_terminal_sibling_failure_stays_running_and_retries_only_sibling(
        self, tmp_path: Path
    ) -> None:
        """status.json commits but the terminal sibling fails: disk stays running (stale,
        never complete) while memory, cache, status and fleet agree; a later publication
        retries only the sibling and never rewrites status.json."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="done")], exit_code=0)
        real_publish = FleetStore.publish_execution

        def fail_terminal(self: FleetStore, *, evidence: ChildExecutionEvidenceDAO) -> bool:
            if evidence.phase == "terminal":
                return False
            return real_publish(self, evidence=evidence)

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch.object(FleetStore, "publish_execution", new=fail_terminal),
        ):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            child.exit()
            winner: SubAgentResultDAO = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)

        stale = harness.verified()
        assert stale is not None and (stale.phase, stale.status_sha256) == ("running", None)
        entry = harness.registry.get(session_id=_CHILD)
        assert entry is not None and (entry.status, entry.last_text) == ("completed", "done")
        assert (
            harness.registry.terminal_result(session_id=_CHILD, execution_id=harness.execution_id) == winner
        )
        assert harness.process._terminal_result_built == winner
        assert ReleasedSubAgentResultDAO.model_validate_json(harness.status_bytes()).answer == "done"
        fleet = ReleasedFleetSnapshotDAO.model_validate_json((tmp_path / _PARENT / "fleet.json").read_bytes())
        assert fleet.entries[0].status == "completed"
        status_inode: int = os.stat(harness.child_dir / "status.json").st_ino
        real_write = AtomicFileWriter.write_text

        def refuse_status(*, path: Path, text: str, private: bool = True) -> None:
            assert path.name != "status.json", "status.json must not be rewritten"
            real_write(path=path, text=text, private=private)

        with patch(
            "src.agents.slo_agent.orchestrator.process.AtomicFileWriter.write_text",
            side_effect=refuse_status,
        ):
            retried = harness.process._publish_terminal(
                candidate=_aborted_candidate(harness), terminal_reason="operator_abort", terminated_by="abort"
            )

        assert retried == winner
        assert os.stat(harness.child_dir / "status.json").st_ino == status_inode
        harness.assert_projections_agree(winner=winner)


class TestFreshIncarnationEvidence:
    """A reused session path never lets an earlier child identify the current execution."""

    async def test_reused_path_replaces_context_and_capture(self, tmp_path: Path) -> None:
        """Old spawn context and stdout are replaced before running evidence is published."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        harness.child_dir.mkdir(parents=True, exist_ok=True)
        (harness.child_dir / "spawn_context.json").write_text('{"task_id": "old"}', encoding="utf-8")
        (harness.child_dir / "stdout.jsonl").write_bytes(b"old incarnation output\n")
        old_capture = os.stat(harness.child_dir / "stdout.jsonl")
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="new")], exit_code=0)

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            running = harness.verified()
            child.exit()
            winner = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)

        assert running is not None and running.phase == "running"
        assert running.stdout_identity is not None
        new_capture = os.stat(harness.child_dir / "stdout.jsonl")
        assert (running.stdout_identity.device, running.stdout_identity.inode) == (
            new_capture.st_dev,
            new_capture.st_ino,
        )
        assert new_capture.st_ino != old_capture.st_ino
        context = ReleasedSpawnContextDAO.model_validate_json(
            (harness.child_dir / "spawn_context.json").read_bytes()
        )
        assert context.task_id == "t1"
        assert b"old incarnation output" not in (harness.child_dir / "stdout.jsonl").read_bytes()
        harness.assert_projections_agree(winner=winner)

    async def test_failed_identity_writes_never_attribute_new_output_to_old_execution(
        self, tmp_path: Path
    ) -> None:
        """Pending/running sibling, index and context writes all fail: the fresh capture
        inode alone keeps the previous terminal evidence from verifying."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        first: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="old")], exit_code=0)
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=first)):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            first.exit()
            await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)
        old_evidence = harness.verified()
        assert old_evidence is not None and old_evidence.phase == "terminal"

        real_text = AtomicFileWriter.write_text
        real_json = AtomicFileWriter.write_json

        def fail_context(*, path: Path, text: str, private: bool = True) -> None:
            if path.name == "spawn_context.json":
                raise OSError("disk full")
            real_text(path=path, text=text, private=private)

        def fail_index(*, path: Path, model: BaseModel, private: bool = True) -> None:
            if path.name == "execution-index.v1.json":
                raise OSError("disk full")
            real_json(path=path, model=model, private=private)

        second: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="new")], exit_code=0)
        with (
            patch.object(FleetStore, "publish_execution", return_value=False),
            patch(
                "src.agents.slo_agent.orchestrator.process.AtomicFileWriter.write_text",
                side_effect=fail_context,
            ),
            patch(
                "src.agents.slo_agent.orchestrator.fleet_store.AtomicFileWriter.write_json",
                side_effect=fail_index,
            ),
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=second)),
        ):
            harness.execution_id = harness.registry.register(
                task_id="t1", session_id=_CHILD, task=harness.task
            )
            harness.process = harness.build_process(execution_id=harness.execution_id)
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            during_new_run = harness.verified()
            second.exit()
            await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)

        assert during_new_run is None


_REAL_REPLACE: Callable[..., None] = os.replace


def _replace_failing_for(name: str) -> Callable[..., None]:
    """Build an ``os.replace`` stand-in that fails only when moving onto ``name``.

    Every other replace (status, fleet, index, sibling atomic writes) goes through
    unchanged, so the failure stays confined to the stdout capture under test.
    """

    def replace(*args: object, **kwargs: object) -> None:
        destination: object = kwargs.get("dst", args[1] if len(args) > 1 else None)
        if Path(str(destination)).name == name:
            raise OSError("capture replace failed")
        _REAL_REPLACE(*args, **kwargs)

    return replace


_REAL_MKSTEMP: Callable[..., tuple[int, str]] = tempfile.mkstemp


def _mkstemp_failing_for(name: str) -> Callable[..., tuple[int, str]]:
    """Build a ``tempfile.mkstemp`` stand-in that fails only for ``name``'s temp file."""

    def mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        if str(kwargs.get("prefix", "")).startswith(f".{name}."):
            raise OSError("no space for capture")
        return _REAL_MKSTEMP(*args, **kwargs)

    return mkstemp


class TestStdoutCaptureFailure:
    """A capture that cannot be freshly opened is never trusted; the run still completes."""

    async def test_capture_replace_failure_runs_without_trusted_capture(self, tmp_path: Path) -> None:
        """os.replace fails onto stdout.jsonl: the temp file is removed, running evidence
        names no capture, and the natural winner publishes to every projection."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="natural")], exit_code=0)

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.os.replace",
                side_effect=_replace_failing_for("stdout.jsonl"),
            ) as replace,
        ):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            running = harness.verified()
            child.exit()
            winner: SubAgentResultDAO = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)

        assert any(
            Path(str(call.args[1])).name == "stdout.jsonl" for call in replace.call_args_list if call.args
        )
        assert running is not None and running.phase == "running"
        assert running.stdout_identity is None
        assert sorted(path.name for path in harness.child_dir.iterdir() if path.name.endswith(".tmp")) == []
        assert not (harness.child_dir / "stdout.jsonl").exists()
        assert (winner.status, winner.answer) == ("completed", "natural")
        harness.assert_projections_agree(winner=winner)

    async def test_capture_open_failure_runs_without_trusted_capture(self, tmp_path: Path) -> None:
        """The capture file cannot even be created: no identity, no temp file, same winner."""
        harness: _Harness = _Harness(tmp_path=tmp_path)
        child: FakeChildProcess = FakeChildProcess(lines=[terminal_line(content="natural")], exit_code=0)

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.tempfile.mkstemp",
                side_effect=_mkstemp_failing_for("stdout.jsonl"),
            ) as mkstemp,
        ):
            run_task = asyncio.create_task(harness.process.run())
            await _wait_for(lambda: harness.process._spawn_ready.is_set())
            running = harness.verified()
            child.exit()
            winner: SubAgentResultDAO = await asyncio.wait_for(run_task, timeout=_BOUNDED_SECONDS)

        mkstemp.assert_called()
        assert running is not None and running.phase == "running"
        assert running.stdout_identity is None
        assert harness.process._stdout_capture is None
        assert sorted(path.name for path in harness.child_dir.iterdir() if path.name.endswith(".tmp")) == []
        assert (winner.status, winner.answer) == ("completed", "natural")
        harness.assert_projections_agree(winner=winner)
