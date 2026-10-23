"""Tests for ``SubAgentPool`` (sub-spec 01-sub-agents 01.d)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.agents.slo_agent.history.filesystem_store import default_history_root
from src.agents.slo_agent.orchestrator.dao import (
    OrchestratorResultDAO,
    ResolvedDispatchTaskDAO,
    SubAgentResultDAO,
    SubAgentTaskDAO,
    terminal_reason_for_status,
)
from src.agents.slo_agent.orchestrator.pool import MAX_CONCURRENCY, MAX_PARALLEL_TASKS, SubAgentPool
from src.agents.slo_agent.orchestrator.process import SubAgentProcess
from src.agents.slo_agent.events.stream import AgentStreamEventDAO
from tests.agents.slo_agent.orchestrator.fake_child import FakeChildProcess, terminal_line
from tests.agents.slo_agent.orchestrator.released_schemas import ReleasedSubAgentResultDAO

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_pool() -> tuple[SubAgentPool, list[AgentStreamEventDAO]]:
    """Build a ``SubAgentPool`` with a collector relay.

    Returns:
        tuple[SubAgentPool, list[AgentStreamEventDAO]]: Pool and event collector.
    """
    relayed: list[AgentStreamEventDAO] = []

    async def _relay(event: AgentStreamEventDAO) -> None:
        relayed.append(event)

    pool: SubAgentPool = SubAgentPool(
        orchestrator_session_id="orch-1",
        default_model=None,
        relay=_relay,
        owner_session_id="owner-1",
        run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
        history_root=default_history_root(),
    )
    return pool, relayed


def _publish(process: SubAgentProcess, result: SubAgentResultDAO) -> SubAgentResultDAO:
    """Publish a patched run's result through the canonical wrapper gateway.

    Patched ``SubAgentProcess.run`` fakes must honour the production contract:
    run returns the registry winner, which the pool emits without reconciling.
    """
    candidate: SubAgentResultDAO = result.model_copy(
        update={"session_id": process.session_id, "execution_id": process.execution_id}
    )
    return process._publish_terminal(
        candidate=candidate,
        terminal_reason=terminal_reason_for_status(status=candidate.status),  # type: ignore[arg-type]
        terminated_by="natural",
    )


def _register_child(*, pool: SubAgentPool, task: SubAgentTaskDAO, session_id: str) -> str:
    """Register one child directly inside a freshly begun registry dispatch.

    Abort-accounting tests need a registry entry without running the pool's
    dispatch; ``register`` requires an admitted batch, as in production.

    Returns:
        str: The child's execution id.
    """
    dispatch_id: str = str(uuid4())
    pool.registry.begin_dispatch(dispatch_id=dispatch_id)
    return pool.registry.register(
        dispatch_id=dispatch_id, task_id=task.task_id, session_id=session_id, task=task
    )


def _completed_result(task_id: str) -> SubAgentResultDAO:
    """Build a completed ``SubAgentResultDAO`` for ``task_id``.

    Args:
        task_id (str): Task identifier.

    Returns:
        SubAgentResultDAO: Completed terminal result.
    """
    return SubAgentResultDAO(
        task_id=task_id,
        session_id="s",
        status="completed",
        answer="ok",
        exit_code=0,
    )


def _failed_result(task_id: str) -> SubAgentResultDAO:
    """Build a failed ``SubAgentResultDAO`` for ``task_id``.

    Args:
        task_id (str): Task identifier.

    Returns:
        SubAgentResultDAO: Failed terminal result.
    """
    return SubAgentResultDAO(
        task_id=task_id,
        session_id="s",
        status="failed",
        answer="err",
        exit_code=1,
    )


# ── tests ─────────────────────────────────────────────────────────────────────


class TestSubAgentPoolBatchRejection:
    """Batches exceeding ``MAX_PARALLEL_TASKS`` are rejected before spawning."""

    async def test_batch_above_max_tasks_rejected_without_spawning(self) -> None:
        """An oversized batch returns a failed ``OrchestratorResultDAO`` immediately."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id=f"t{i}", prompt="x")
            for i in range(MAX_PARALLEL_TASKS + 1)
        ]

        result = await pool.dispatch(mode="parallel", tasks=tasks)

        assert result.all_completed is False
        assert len(relayed) == 0  # no children spawned
        assert len(result.failed_task_ids) == len(tasks)


class TestSubAgentPoolLifecycleEvents:
    """Lifecycle stream events are emitted for each dispatched task."""

    async def test_spawned_and_completed_events_emitted_per_task(self) -> None:
        """``sub_agent_spawned`` and ``sub_agent_completed`` are relayed for each task."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"),
        ]

        # Patch at the process level so _run_one still executes its full
        # lifecycle (including _emit_lifecycle calls).
        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(self_proc, _completed_result(self_proc._task.task_id))

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=_fake_process_run,
        ):
            await pool.dispatch(mode="single", tasks=tasks)

        kinds: list[str] = [e.kind for e in relayed]
        assert "sub_agent_spawned" in kinds
        assert "sub_agent_completed" in kinds

    async def test_terminal_event_observes_terminal_registry_entry(self) -> None:
        """Terminal lifecycle observers receive the already-terminal fleet snapshot.

        WHAT: Snapshots the pool registry inside the terminal relay callback.
        WHO: The fleet-reporting regression suite.
        WHEN: The terminal lifecycle ordering changes.
        """
        terminal_statuses: list[str] = []
        pool: SubAgentPool

        async def capture_terminal_snapshot(event: AgentStreamEventDAO) -> None:
            """Record the registry state visible at a terminal lifecycle relay."""
            if event.kind != "sub_agent_completed":
                return
            terminal_statuses.append(pool.registry.snapshot()[0].status)

        pool = SubAgentPool(
            orchestrator_session_id="orch-1",
            default_model=None,
            relay=capture_terminal_snapshot,
            owner_session_id="owner-1",
            run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
            history_root=default_history_root(),
        )
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
        )

        async def fake_process_run(self_proc) -> SubAgentResultDAO:
            """Return one completed process result without spawning a subprocess."""
            return _publish(self_proc, _completed_result(self_proc._task.task_id))

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=fake_process_run,
        ):
            await pool.dispatch(mode="single", tasks=[task])

        assert terminal_statuses == ["completed"]

    async def test_failed_task_emits_sub_agent_failed_event(self) -> None:
        """A failed task emits ``sub_agent_failed`` instead of ``sub_agent_completed``."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(self_proc, _failed_result(self_proc._task.task_id))

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=_fake_process_run,
        ):
            await pool.dispatch(mode="single", tasks=tasks)

        kinds: list[str] = [e.kind for e in relayed]
        assert "sub_agent_failed" in kinds


class TestSubAgentPoolChainMode:
    """Chain dispatch mode behaviour."""

    async def test_chain_substitutes_previous_placeholder(self) -> None:
        """In chain mode, ``{previous}`` in step 2 is replaced by step 1's answer."""
        pool, _ = _make_pool()
        received_prompts: list[str] = []

        async def _fake_run_one(*, resolved: ResolvedDispatchTaskDAO, **_: object) -> SubAgentResultDAO:
            task: SubAgentTaskDAO = resolved.task
            received_prompts.append(task.prompt)
            return SubAgentResultDAO(
                task_id=task.task_id,
                session_id="s",
                status="completed",
                answer=f"result-of-{task.task_id}",
                exit_code=0,
            )

        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Produce the initial analysis", task_id="t1", prompt="Do step 1."),
            SubAgentTaskDAO(
                task_summary="Exercise child dispatch lifecycle", task_id="t2", prompt="Based on: {previous}"
            ),
        ]
        with patch.object(pool, "_run_one", side_effect=_fake_run_one):
            result = await pool.dispatch(mode="chain", tasks=tasks)

        assert result.all_completed is True
        assert "result-of-t1" in received_prompts[1]

    async def test_chain_stops_on_first_failure(self) -> None:
        """In chain mode, a failed step prevents subsequent steps from running."""
        pool, _ = _make_pool()
        run_count: list[int] = [0]

        async def _fake_run_one(*, resolved: ResolvedDispatchTaskDAO, **_: object) -> SubAgentResultDAO:
            run_count[0] += 1
            return _failed_result(resolved.task.task_id)

        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Produce the initial analysis", task_id="t1", prompt="Step 1."),
            SubAgentTaskDAO(task_summary="Refine the previous analysis", task_id="t2", prompt="Step 2."),
        ]
        with patch.object(pool, "_run_one", side_effect=_fake_run_one):
            result = await pool.dispatch(mode="chain", tasks=tasks)

        assert run_count[0] == 1
        assert "t1" in result.failed_task_ids


class TestSubAgentPoolAggregate:
    """``_aggregate`` builds correct ``OrchestratorResultDAO``."""

    def test_all_completed_when_no_failures(self) -> None:
        """``all_completed=True`` when every task has ``status='completed'``."""
        pool, _ = _make_pool()
        results: list[SubAgentResultDAO] = [
            _completed_result("t1"),
            _completed_result("t2"),
        ]

        dao = pool._aggregate(mode="parallel", results=results)

        assert dao.all_completed is True
        assert dao.failed_task_ids == []

    def test_failed_task_ids_populated_for_incomplete_tasks(self) -> None:
        """Failed tasks appear in ``failed_task_ids`` and ``all_completed=False``."""
        pool, _ = _make_pool()
        results: list[SubAgentResultDAO] = [
            _completed_result("t1"),
            _failed_result("t2"),
        ]

        dao = pool._aggregate(mode="parallel", results=results)

        assert dao.all_completed is False
        assert "t2" in dao.failed_task_ids
        assert "t1" not in dao.failed_task_ids


class TestSubAgentPoolRegistry:
    """Pool exposes its registry via the ``registry`` property."""

    def test_registry_property_returns_process_registry(self) -> None:
        """``pool.registry`` returns the pool's ``ProcessRegistry`` instance."""
        from src.agents.slo_agent.orchestrator.registry import ProcessRegistry

        pool, _ = _make_pool()

        assert isinstance(pool.registry, ProcessRegistry)


class TestResolveChildSessionId:
    """``SubAgentPool._resolve_child_session_id`` priority and fallback behaviour."""

    async def test_returns_explicit_session_id_unchanged(self) -> None:
        """When ``task.session_id`` is set it is returned directly without store lookup."""
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle",
            task_id="t1",
            prompt="x",
            session_id="explicit-child-id",
        )

        with patch("src.agents.slo_agent.orchestrator.pool.FilesystemSessionHistoryStore") as MockStore:
            result: str = await pool._resolve_child_session_id(task=task)

        assert result == "explicit-child-id"
        MockStore.assert_not_called()

    async def test_resolves_resume_session_reference_via_store(self) -> None:
        """When ``task.resume_session_reference`` is set it is resolved via the history store."""
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle",
            task_id="t2",
            prompt="x",
            resume_session_reference="my-session-ref",
        )

        mock_store: AsyncMock = AsyncMock()
        mock_store.resolve_session_reference = AsyncMock(return_value="resolved-canonical-id")

        with patch(
            "src.agents.slo_agent.orchestrator.pool.FilesystemSessionHistoryStore",
            return_value=mock_store,
        ):
            result: str = await pool._resolve_child_session_id(task=task)

        assert result == "resolved-canonical-id"
        mock_store.resolve_session_reference.assert_called_once_with(reference="my-session-ref")

    async def test_falls_back_to_new_uuid_when_reference_unresolvable(self) -> None:
        """When the history store raises ``ValueError`` a fresh uuid4 is returned."""
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle",
            task_id="t3",
            prompt="x",
            resume_session_reference="missing-ref",
        )

        mock_store: AsyncMock = AsyncMock()
        mock_store.resolve_session_reference = AsyncMock(side_effect=ValueError("not found"))

        with patch(
            "src.agents.slo_agent.orchestrator.pool.FilesystemSessionHistoryStore",
            return_value=mock_store,
        ):
            result: str = await pool._resolve_child_session_id(task=task)

        # Result must be a fresh UUID4 (not the reference string, not the error)
        assert result != "missing-ref"
        import re

        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            result,
        ), f"Expected a UUID4, got: {result!r}"

    async def test_generates_new_uuid_when_neither_identity_field_set(self) -> None:
        """When ``task.session_id`` and ``task.resume_session_reference`` are both ``None``
        a fresh UUID4 is returned and no store is consulted."""
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="t4", prompt="x"
        )

        with patch("src.agents.slo_agent.orchestrator.pool.FilesystemSessionHistoryStore") as MockStore:
            result: str = await pool._resolve_child_session_id(task=task)

        import re

        assert re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            result,
        ), f"Expected a UUID4, got: {result!r}"
        MockStore.assert_not_called()

    async def test_two_unrelated_calls_produce_distinct_ids(self) -> None:
        """Two separate calls with no identity constraints produce distinct session ids."""
        pool, _ = _make_pool()
        task_a: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="ta", prompt="x"
        )
        task_b: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="tb", prompt="x"
        )

        id_a: str = await pool._resolve_child_session_id(task=task_a)
        id_b: str = await pool._resolve_child_session_id(task=task_b)

        assert id_a != id_b


class TestSubAgentPoolAbortedStatus:
    """Aborted child processes emit ``sub_agent_aborted``, not ``sub_agent_failed``."""

    async def test_aborted_task_emits_sub_agent_aborted_event(self) -> None:
        """A child exiting with status 'aborted' emits ``sub_agent_aborted``."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(
                self_proc,
                SubAgentResultDAO(
                    task_id=self_proc._task.task_id,
                    session_id="s",
                    status="aborted",
                    exit_code=2,
                ),
            )

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=_fake_process_run,
        ):
            result = await pool.dispatch(mode="single", tasks=tasks)

        kinds: list[str] = [e.kind for e in relayed]
        assert "sub_agent_aborted" in kinds
        assert "sub_agent_failed" not in kinds

    async def test_aborted_task_does_not_appear_as_failed(self) -> None:
        """``sub_agent_failed`` is not emitted for aborted children."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(
                self_proc,
                SubAgentResultDAO(
                    task_id=self_proc._task.task_id,
                    session_id="s",
                    status="aborted",
                    exit_code=2,
                ),
            )

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=_fake_process_run,
        ):
            await pool.dispatch(mode="single", tasks=tasks)

        kinds: list[str] = [e.kind for e in relayed]
        assert "sub_agent_failed" not in kinds

    async def test_failed_task_still_emits_sub_agent_failed(self) -> None:
        """A child exiting with status 'failed' still emits ``sub_agent_failed``."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(self_proc, _failed_result(self_proc._task.task_id))

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=_fake_process_run,
        ):
            await pool.dispatch(mode="single", tasks=tasks)

        kinds: list[str] = [e.kind for e in relayed]
        assert "sub_agent_failed" in kinds
        assert "sub_agent_aborted" not in kinds


class TestSubAgentPoolTerminalReasons:
    """Pool terminal statuses use the shared durable reason mapping."""

    async def test_terminal_reason_for_completed(self) -> None:
        """Completed child results persist the completed terminal reason."""
        pool, _ = _make_pool()

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(self_proc, _completed_result(self_proc._task.task_id))

        with patch("src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run", new=_fake_process_run):
            await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
                    )
                ],
            )

        entry = pool.registry.snapshot()[0]
        assert entry.terminal_reason == "completed"

    async def test_terminal_reason_for_failed(self) -> None:
        """Failed child results persist the failed terminal reason."""
        pool, _ = _make_pool()

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(self_proc, _failed_result(self_proc._task.task_id))

        with patch("src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run", new=_fake_process_run):
            await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
                    )
                ],
            )

        entry = pool.registry.snapshot()[0]
        assert entry.terminal_reason == "failed"

    async def test_terminal_reason_for_aborted(self) -> None:
        """Aborted child results persist the operator-abort terminal reason."""
        pool, _ = _make_pool()

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _publish(
                self_proc,
                SubAgentResultDAO(
                    task_id=self_proc._task.task_id,
                    session_id="s",
                    status="aborted",
                    exit_code=2,
                ),
            )

        with patch("src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run", new=_fake_process_run):
            await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
                    )
                ],
            )

        entry = pool.registry.snapshot()[0]
        assert entry.terminal_reason == "operator_abort"

    async def test_snapshot_omits_workflow_id_when_not_detached(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A non-detached pool persists a fleet snapshot without workflow identity."""
        monkeypatch.delenv("SLO_WORKFLOW_ID", raising=False)

        async def _relay(event: AgentStreamEventDAO) -> None:
            return None

        if True:  # explicit composition: the pool no longer reads a hidden history-root global
            pool: SubAgentPool = SubAgentPool(
                orchestrator_session_id="orchestrator-1",
                default_model=None,
                relay=_relay,
                owner_session_id="owner-1",
                run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
                history_root=tmp_path,
            )

            async def _fake_process_run(self_proc) -> SubAgentResultDAO:
                return _publish(self_proc, _completed_result(self_proc._task.task_id))

            with patch("src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run", new=_fake_process_run):
                await pool.dispatch(
                    mode="single",
                    tasks=[
                        SubAgentTaskDAO(
                            task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
                        )
                    ],
                )

        fleet_path: Path = tmp_path / "orchestrator-1" / "fleet.json"
        assert fleet_path.exists()
        assert '"workflow_id": null' in fleet_path.read_text(encoding="utf-8")


class TestSubAgentPoolAbortAndDrain:
    """Ordered pool abort records and reports every active child."""

    async def test_dispatch_returns_sealed_error_after_abort(self) -> None:
        """A sealed pool rejects a new task batch without spawning children."""
        pool, _ = _make_pool()
        pool._sealed = True
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x")
        ]

        result = await pool.dispatch(mode="single", tasks=tasks)

        assert result.error == "pool sealed by abort; no new sub-agents will be spawned"
        assert result.failed_task_ids == ["t1"]

    async def test_abort_and_drain_noops_when_already_sealed(self) -> None:
        """A second ordered abort does not repeat child cancellation or recording."""
        pool, _ = _make_pool()
        pool._sealed = True
        pool.cancel_all = AsyncMock()

        await pool.abort_and_drain()

        pool.cancel_all.assert_not_called()

    async def test_abort_and_drain_concurrent_callers_join_one_shutdown(self) -> None:
        """Concurrent abort callers wait for the same ordered pool shutdown."""
        pool, _ = _make_pool()
        started: asyncio.Event = asyncio.Event()
        release: asyncio.Event = asyncio.Event()

        async def cancel_all() -> None:
            started.set()
            await release.wait()

        pool.cancel_all = AsyncMock(side_effect=cancel_all)
        first: asyncio.Task[None] = asyncio.create_task(pool.abort_and_drain())
        await started.wait()
        second: asyncio.Task[None] = asyncio.create_task(pool.abort_and_drain())
        await asyncio.sleep(0)

        assert second.done() is False
        release.set()
        await asyncio.gather(first, second)
        pool.cancel_all.assert_awaited_once()

    async def test_sealed_pool_does_not_spawn_task_waiting_for_capacity(self) -> None:
        """A queued task is terminalized without spawning after the pool seals.

        WHAT: Seals the pool while a wrapper waits on its concurrency semaphore.
        WHO: The cleanup-guarantee regression suite.
        WHEN: Pre-spawn abort handling changes.
        """
        pool, _ = _make_pool()
        pool._semaphore = asyncio.Semaphore(0)
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
        )

        with patch.object(SubAgentProcess, "run", new=AsyncMock()) as run:
            queued: asyncio.Task[OrchestratorResultDAO] = asyncio.create_task(
                pool.dispatch(mode="single", tasks=[task])
            )
            while not pool._active_by_session_id:
                await asyncio.sleep(0)
            await pool.abort_and_drain()
            pool._semaphore.release()
            result: SubAgentResultDAO = (await queued).results[0]

        assert result.status == "aborted"
        run.assert_not_awaited()
        entry = pool.registry.snapshot()[0]
        assert entry.status == "aborted"
        assert entry.terminal_reason == "operator_abort"

    async def test_record_abort_outcomes_leaves_unresolved_child_running(self) -> None:
        """An unreadable active child stays visible for the terminal drain gate.

        WHAT: Verifies abort accounting never calls an unresolved child reaped.
        WHO: The cleanup-guarantee regression suite.
        WHEN: Pool cancellation outcome handling changes.
        """
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
        )
        execution_id: str = _register_child(pool=pool, task=task, session_id="child-1")
        pool.registry.mark_running(session_id="child-1", execution_id=execution_id, pid=123, started_at=1.0)
        pool._cancel_outcomes = {"child-1": "unresolved"}

        await pool._record_abort_outcomes()

        entry = pool.registry.snapshot()[0]
        assert entry.status == "running"
        assert entry.terminal_reason is None

    async def test_record_abort_outcomes_skips_terminal_entries(self) -> None:
        """Already terminal entries retain their prior terminal cleanup facts."""
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
        )
        execution_id: str = _register_child(pool=pool, task=task, session_id="child-1")
        pool.registry.mark_terminal(
            session_id="child-1",
            execution_id=execution_id,
            status="completed",
            answer="done",
            exit_code=0,
            terminal_reason="completed",
            terminated_by="natural",
        )

        await pool._record_abort_outcomes()

        entry = pool.registry.snapshot()[0]
        assert entry.status == "completed"
        assert entry.terminal_reason == "completed"

    async def test_sub_agent_reaped_emitted_only_for_killed_children(self) -> None:
        """Only a SIGKILL outcome emits the hard-reap lifecycle event."""
        pool, relayed = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
        )
        execution_id: str = _register_child(pool=pool, task=task, session_id="child-1")
        pool.registry.mark_running(session_id="child-1", execution_id=execution_id, pid=123, started_at=1.0)
        pool._cancel_outcomes = {"child-1": "killed"}

        await pool._record_abort_outcomes()

        assert [event.kind for event in relayed] == ["sub_agent_reaped"]
        dispatch = pool.registry.dispatch_of(session_id="child-1", execution_id=execution_id)
        assert dispatch is not None
        assert relayed[0].metadata == dispatch.lifecycle_metadata(execution_id=execution_id)

    async def test_reaped_event_for_superseded_incarnation_carries_only_execution_id(self) -> None:
        """A session reused while reaped events are relayed keeps no stale batch identity.

        ``_record_abort_outcomes`` iterates one snapshot and awaits each relay, so
        a later entry can be re-registered by a newer batch before its event is
        built; the old incarnation then has no current dispatch.
        """
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"
        )
        pool: SubAgentPool
        relayed: list[AgentStreamEventDAO] = []

        async def _relay(event: AgentStreamEventDAO) -> None:
            relayed.append(event)
            if len(relayed) == 1:
                _register_child(pool=pool, task=task, session_id="child-2")

        pool = SubAgentPool(
            orchestrator_session_id="orch-1",
            default_model=None,
            relay=_relay,
            owner_session_id="owner-1",
            run_id="7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f",
            history_root=default_history_root(),
        )
        _register_child(pool=pool, task=task, session_id="child-1")
        old_execution: str = _register_child(pool=pool, task=task, session_id="child-2")
        pool.registry.mark_terminal(
            session_id="child-2", execution_id=old_execution, status="aborted", answer="", exit_code=2
        )
        pool._cancel_outcomes = {"child-1": "killed", "child-2": "killed"}

        await pool._record_abort_outcomes()

        assert [event.sub_agent_id for event in relayed] == ["child-1", "child-2"]
        assert relayed[1].metadata == {"execution_id": old_execution}


class TestSubAgentPoolCancelAll:
    """``cancel_all()`` calls ``cancel()`` on every active process."""

    async def test_cancel_all_invokes_cancel_on_each_process(self) -> None:
        """``cancel_all()`` calls ``cancel()`` on every wrapper in ``_active_by_session_id``."""
        pool, _ = _make_pool()
        mock_proc_1: AsyncMock = AsyncMock()
        mock_proc_2: AsyncMock = AsyncMock()
        pool._active_by_session_id = {"child-1": mock_proc_1, "child-2": mock_proc_2}

        await pool.cancel_all()

        mock_proc_1.cancel.assert_called_once()
        mock_proc_2.cancel.assert_called_once()

    async def test_cancel_all_tolerates_individual_cancel_failure(self) -> None:
        """``cancel_all()`` continues even when one process's ``cancel`` raises."""
        pool, _ = _make_pool()
        failing_proc: AsyncMock = AsyncMock()
        failing_proc.session_id = "child-failing"
        failing_proc.cancel = AsyncMock(side_effect=RuntimeError("cancel failed"))
        succeeding_proc: AsyncMock = AsyncMock()
        succeeding_proc.session_id = "child-succeeding"
        pool._active_by_session_id = {"child-failing": failing_proc, "child-succeeding": succeeding_proc}

        await pool.cancel_all()  # must not raise

        succeeding_proc.cancel.assert_called_once()
        assert pool._cancel_outcomes["child-failing"] == "unresolved"


# ── Feature 94 T02: canonical winner, identity composition, abort cleanup ────

_RUN_ID: str = "7d1e2f3a-4b5c-4d6e-8f70-1a2b3c4d5e6f"


def _bound_pool(tmp_path: Path) -> tuple[SubAgentPool, list[AgentStreamEventDAO]]:
    """Build a pool composed with explicit temp-owned identity and history root."""
    relayed: list[AgentStreamEventDAO] = []

    async def _relay(event: AgentStreamEventDAO) -> None:
        relayed.append(event)

    pool: SubAgentPool = SubAgentPool(
        orchestrator_session_id="orch-1",
        default_model=None,
        relay=_relay,
        owner_session_id="owner-1",
        run_id=_RUN_ID,
        history_root=tmp_path,
    )
    return pool, relayed


def _terminal_kinds(relayed: list[AgentStreamEventDAO]) -> list[str]:
    return [
        event.kind
        for event in relayed
        if event.kind in {"sub_agent_completed", "sub_agent_failed", "sub_agent_aborted"}
    ]


async def _until(predicate) -> None:  # type: ignore[no-untyped-def]
    async def poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(poll(), timeout=2.0)


class TestSubAgentPoolIdentityComposition:
    """The pool receives immutable owner/run/history identity from its composer."""

    def test_identities_are_retained_and_bound_to_fleet_projection(self, tmp_path: Path) -> None:
        """The run identity reaches the execution index under the composed root."""
        pool, _ = _bound_pool(tmp_path)
        task = SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x")

        execution_id: str = _register_child(pool=pool, task=task, session_id="child-1")

        assert (pool.owner_session_id, pool.run_id) == ("owner-1", _RUN_ID)
        index = (tmp_path / "orch-1" / "execution-index.v1.json").read_text(encoding="utf-8")
        assert _RUN_ID in index and execution_id in index

    def test_identities_are_keyword_required(self) -> None:
        """No hidden global supplies owner, run or history identity."""

        async def _relay(event: AgentStreamEventDAO) -> None:
            return None

        with pytest.raises(TypeError):
            SubAgentPool(orchestrator_session_id="orch-1", default_model=None, relay=_relay)  # type: ignore[call-arg]


class TestSubAgentPoolCanonicalWinner:
    """_run_one emits and returns only the process's registry winner."""

    async def test_wrapper_registered_before_spawned_event(self, tmp_path: Path) -> None:
        """An observer of the spawned event already finds the wrapper registered."""
        seen: list[bool] = []
        pool: SubAgentPool

        async def relay(event: AgentStreamEventDAO) -> None:
            if event.kind == "sub_agent_spawned":
                seen.append(event.sub_agent_id in pool._active_by_session_id)

        pool = SubAgentPool(
            orchestrator_session_id="orch-1",
            default_model=None,
            relay=relay,
            owner_session_id="owner-1",
            run_id=_RUN_ID,
            history_root=tmp_path,
        )
        child = FakeChildProcess(lines=[terminal_line()], exit_code=0)
        child.exit()

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)):
            await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Exercise child dispatch lifecycle",
                        task_id="t1",
                        prompt="x",
                        session_id="child-1",
                    )
                ],
            )

        assert seen == [True]

    async def test_natural_result_is_registry_winner_with_one_lifecycle(self, tmp_path: Path) -> None:
        """Result, fleet, status.json and the single terminal event come from one winner."""
        pool, relayed = _bound_pool(tmp_path)
        child = FakeChildProcess(lines=[terminal_line(content="done")], exit_code=0)
        child.exit()

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)):
            result = await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Exercise child dispatch lifecycle",
                        task_id="t1",
                        prompt="x",
                        session_id="child-1",
                    )
                ],
            )

        winner = result.results[0]
        entry = pool.registry.get(session_id="child-1")
        assert entry is not None
        assert (winner.status, winner.answer, winner.execution_id) == (
            "completed",
            "done",
            entry.execution_id,
        )
        assert pool.registry.terminal_result(session_id="child-1", execution_id=entry.execution_id) == winner
        status = ReleasedSubAgentResultDAO.model_validate_json(
            (tmp_path / "orch-1" / "children" / "child-1" / "status.json").read_bytes()
        )
        assert (status.status, status.answer) == ("completed", "done")
        assert _terminal_kinds(relayed) == ["sub_agent_completed"]

    async def test_concurrent_same_session_is_refused_without_second_execution(self, tmp_path: Path) -> None:
        """A second batch naming a non-terminal session is refused before admission, no spawn."""
        pool, relayed = _bound_pool(tmp_path)
        child = FakeChildProcess(lines=[terminal_line()], exit_code=0)
        spawn = AsyncMock(return_value=child)

        with patch("asyncio.create_subprocess_exec", new=spawn):
            first = asyncio.create_task(
                pool.dispatch(
                    mode="single",
                    tasks=[
                        SubAgentTaskDAO(
                            task_summary="Exercise child dispatch lifecycle",
                            task_id="t1",
                            prompt="x",
                            session_id="dup",
                        )
                    ],
                )
            )
            await _until(lambda: pool.registry.get(session_id="dup") is not None)
            second = await pool.dispatch(
                mode="single",
                tasks=[
                    SubAgentTaskDAO(
                        task_summary="Exercise child dispatch lifecycle",
                        task_id="t2",
                        prompt="y",
                        session_id="dup",
                    )
                ],
            )
            child.exit()
            first_result = (await first).results[0]

        assert (second.results, second.failed_task_ids) == ([], ["t2"])
        assert second.error == "child session already executing in this pool; no sub-agents were started"
        assert first_result.status == "completed"
        assert spawn.await_count == 1
        assert [event.kind for event in relayed].count("sub_agent_spawned") == 1


class TestSubAgentPoolAbortCanonicalCleanup:
    """Whole abort consumes canonical winners instead of writing terminal state itself."""

    async def test_whole_abort_of_running_child_publishes_one_aborted_winner(self, tmp_path: Path) -> None:
        """A confirmed reap commits operator abort; one lifecycle; status and fleet agree."""
        pool, relayed = _bound_pool(tmp_path)
        child = FakeChildProcess(lines=[], exit_code=-15)

        async def reap(*, pid: int) -> str:
            child.exit()
            return "graceful"

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome",
                return_value="matching",
            ),
            patch("src.agents.slo_agent.orchestrator.process.FleetReaper.reap", new=reap),
        ):
            dispatch = asyncio.create_task(
                pool.dispatch(
                    mode="single",
                    tasks=[
                        SubAgentTaskDAO(
                            task_summary="Exercise child dispatch lifecycle",
                            task_id="t1",
                            prompt="x",
                            session_id="child-1",
                        )
                    ],
                )
            )
            await _until(
                lambda: (e := pool.registry.get(session_id="child-1")) is not None and e.status == "running"
            )
            await pool.abort_and_drain()
            result = await dispatch

        entry = pool.registry.get(session_id="child-1")
        assert entry is not None
        assert (entry.status, entry.terminal_reason, entry.terminated_by) == (
            "aborted",
            "operator_abort",
            "abort",
        )
        assert (result.results[0].status, result.results[0].exit_code) == ("aborted", 2)
        assert _terminal_kinds(relayed) == ["sub_agent_aborted"]
        status = ReleasedSubAgentResultDAO.model_validate_json(
            (tmp_path / "orch-1" / "children" / "child-1" / "status.json").read_bytes()
        )
        assert status.status == "aborted"

    async def test_unresolved_reap_never_claims_abort(self, tmp_path: Path) -> None:
        """An unresolved reap leaves the child running; its natural exit later wins."""
        pool, relayed = _bound_pool(tmp_path)
        child = FakeChildProcess(lines=[terminal_line(content="natural")], exit_code=0)

        with (
            patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=child)),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.child_identity_outcome",
                return_value="matching",
            ),
            patch(
                "src.agents.slo_agent.orchestrator.process.FleetReaper.reap",
                new=AsyncMock(return_value="unresolved"),
            ),
        ):
            dispatch = asyncio.create_task(
                pool.dispatch(
                    mode="single",
                    tasks=[
                        SubAgentTaskDAO(
                            task_summary="Exercise child dispatch lifecycle",
                            task_id="t1",
                            prompt="x",
                            session_id="child-1",
                        )
                    ],
                )
            )
            await _until(
                lambda: (e := pool.registry.get(session_id="child-1")) is not None and e.status == "running"
            )
            await pool.abort_and_drain()
            entry = pool.registry.get(session_id="child-1")
            assert entry is not None and entry.status == "running"
            child.exit()
            result = await dispatch

        assert result.results[0].status == "completed"
        assert _terminal_kinds(relayed) == ["sub_agent_completed"]

    async def test_sealed_pending_child_publishes_once_without_spawn(self, tmp_path: Path) -> None:
        """A queued child is aborted canonically at drain and emits one lifecycle later."""
        pool, relayed = _bound_pool(tmp_path)
        pool._semaphore = asyncio.Semaphore(0)
        spawn = AsyncMock(side_effect=AssertionError("spawn must not be reached"))

        with patch("asyncio.create_subprocess_exec", new=spawn):
            queued = asyncio.create_task(
                pool.dispatch(
                    mode="single",
                    tasks=[
                        SubAgentTaskDAO(
                            task_summary="Exercise child dispatch lifecycle",
                            task_id="t1",
                            prompt="x",
                            session_id="child-1",
                        )
                    ],
                )
            )
            await _until(lambda: bool(pool._active_by_session_id))
            await pool.abort_and_drain()

            entry = pool.registry.get(session_id="child-1")
            assert entry is not None
            assert (entry.status, entry.terminal_reason, entry.terminated_by) == (
                "aborted",
                "operator_abort",
                "abort",
            )
            assert (tmp_path / "orch-1" / "children" / "child-1" / "status.json").exists()
            assert _terminal_kinds(relayed) == []

            pool._semaphore.release()
            result = (await queued).results[0]

        spawn.assert_not_awaited()
        assert (result.status, result.exit_code, result.execution_id) == ("aborted", 2, entry.execution_id)
        assert _terminal_kinds(relayed) == ["sub_agent_aborted"]

    async def test_whole_abort_completes_while_pre_spawn_failure_lifecycle_is_in_flight(
        self, tmp_path: Path
    ) -> None:
        """A wrapper that failed before spawn never wedges abort_and_drain."""
        failed_seen: asyncio.Event = asyncio.Event()
        release_emit: asyncio.Event = asyncio.Event()

        async def relay(event: AgentStreamEventDAO) -> None:
            if event.kind == "sub_agent_failed":
                failed_seen.set()
                await release_emit.wait()

        pool: SubAgentPool = SubAgentPool(
            orchestrator_session_id="orch-1",
            default_model=None,
            relay=relay,
            owner_session_id="owner-1",
            run_id=_RUN_ID,
            history_root=tmp_path,
        )

        spawn = AsyncMock(side_effect=AssertionError("spawn must not be reached"))
        with (
            patch(
                "src.agents.slo_agent.orchestrator.process.CredentialResolver.resolve",
                side_effect=RuntimeError("setup failed"),
            ),
            patch("asyncio.create_subprocess_exec", new=spawn),
        ):
            dispatch = asyncio.create_task(
                pool.dispatch(
                    mode="single",
                    tasks=[
                        SubAgentTaskDAO(
                            task_summary="Exercise child dispatch lifecycle",
                            task_id="t1",
                            prompt="x",
                            session_id="child-1",
                        )
                    ],
                )
            )
            await asyncio.wait_for(failed_seen.wait(), timeout=2.0)
            assert len(pool._active_by_session_id) == 1
            await asyncio.wait_for(pool.abort_and_drain(), timeout=2.0)
            release_emit.set()
            result = await asyncio.wait_for(dispatch, timeout=2.0)

        assert result.results[0].status == "failed"
        spawn.assert_not_awaited()
        entry = pool.registry.get(session_id="child-1")
        assert entry is not None and entry.status == "failed"

    async def test_record_abort_outcomes_never_writes_terminal_state(self, tmp_path: Path) -> None:
        """A registry entry without a publishing wrapper is not independently terminalized."""
        pool, relayed = _bound_pool(tmp_path)
        execution_id = _register_child(
            pool=pool,
            task=SubAgentTaskDAO(task_summary="Exercise child dispatch lifecycle", task_id="t1", prompt="x"),
            session_id="child-1",
        )
        pool.registry.mark_running(session_id="child-1", execution_id=execution_id, pid=123, started_at=1.0)

        await pool._record_abort_outcomes()

        entry = pool.registry.get(session_id="child-1")
        assert entry is not None and (entry.status, entry.terminal_reason) == ("running", None)
        assert relayed == []
