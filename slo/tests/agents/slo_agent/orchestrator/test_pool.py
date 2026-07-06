"""Tests for ``SubAgentPool`` (sub-spec 01-sub-agents 01.d)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.slo_agent.orchestrator.dao import (
    SubAgentResultDAO,
    SubAgentTaskDAO,
)
from src.agents.slo_agent.orchestrator.pool import MAX_CONCURRENCY, MAX_PARALLEL_TASKS, SubAgentPool
from src.agents.slo_agent.events.stream import AgentStreamEventDAO


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
    )
    return pool, relayed


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
            SubAgentTaskDAO(task_id=f"t{i}", prompt="x")
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
            SubAgentTaskDAO(task_id="t1", prompt="x"),
        ]

        # Patch at the process level so _run_one still executes its full
        # lifecycle (including _emit_lifecycle calls).
        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _completed_result(self_proc._task.task_id)

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=_fake_process_run,
        ):
            await pool.dispatch(mode="single", tasks=tasks)

        kinds: list[str] = [e.kind for e in relayed]
        assert "sub_agent_spawned" in kinds
        assert "sub_agent_completed" in kinds

    async def test_failed_task_emits_sub_agent_failed_event(self) -> None:
        """A failed task emits ``sub_agent_failed`` instead of ``sub_agent_completed``."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _failed_result(self_proc._task.task_id)

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

        async def _fake_run_one(*, task: SubAgentTaskDAO) -> SubAgentResultDAO:
            received_prompts.append(task.prompt)
            return SubAgentResultDAO(
                task_id=task.task_id,
                session_id="s",
                status="completed",
                answer=f"result-of-{task.task_id}",
                exit_code=0,
            )

        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_id="t1", prompt="Do step 1."),
            SubAgentTaskDAO(task_id="t2", prompt="Based on: {previous}"),
        ]
        with patch.object(pool, "_run_one", side_effect=_fake_run_one):
            result = await pool.dispatch(mode="chain", tasks=tasks)

        assert result.all_completed is True
        assert "result-of-t1" in received_prompts[1]

    async def test_chain_stops_on_first_failure(self) -> None:
        """In chain mode, a failed step prevents subsequent steps from running."""
        pool, _ = _make_pool()
        run_count: list[int] = [0]

        async def _fake_run_one(*, task: SubAgentTaskDAO) -> SubAgentResultDAO:
            run_count[0] += 1
            return _failed_result(task.task_id)

        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_id="t1", prompt="Step 1."),
            SubAgentTaskDAO(task_id="t2", prompt="Step 2."),
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
            task_id="t1",
            prompt="x",
            session_id="explicit-child-id",
        )

        with patch(
            "src.agents.slo_agent.orchestrator.pool.FilesystemSessionHistoryStore"
        ) as MockStore:
            result: str = await pool._resolve_child_session_id(task=task)

        assert result == "explicit-child-id"
        MockStore.assert_not_called()

    async def test_resolves_resume_session_reference_via_store(self) -> None:
        """When ``task.resume_session_reference`` is set it is resolved via the history store."""
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t2",
            prompt="x",
            resume_session_reference="my-session-ref",
        )

        mock_store: AsyncMock = AsyncMock()
        mock_store.resolve_session_reference = AsyncMock(
            return_value="resolved-canonical-id"
        )

        with patch(
            "src.agents.slo_agent.orchestrator.pool.FilesystemSessionHistoryStore",
            return_value=mock_store,
        ):
            result: str = await pool._resolve_child_session_id(task=task)

        assert result == "resolved-canonical-id"
        mock_store.resolve_session_reference.assert_called_once_with(
            reference="my-session-ref"
        )

    async def test_falls_back_to_new_uuid_when_reference_unresolvable(self) -> None:
        """When the history store raises ``ValueError`` a fresh uuid4 is returned."""
        pool, _ = _make_pool()
        task: SubAgentTaskDAO = SubAgentTaskDAO(
            task_id="t3",
            prompt="x",
            resume_session_reference="missing-ref",
        )

        mock_store: AsyncMock = AsyncMock()
        mock_store.resolve_session_reference = AsyncMock(
            side_effect=ValueError("not found")
        )

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
        task: SubAgentTaskDAO = SubAgentTaskDAO(task_id="t4", prompt="x")

        with patch(
            "src.agents.slo_agent.orchestrator.pool.FilesystemSessionHistoryStore"
        ) as MockStore:
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
        task_a: SubAgentTaskDAO = SubAgentTaskDAO(task_id="ta", prompt="x")
        task_b: SubAgentTaskDAO = SubAgentTaskDAO(task_id="tb", prompt="x")

        id_a: str = await pool._resolve_child_session_id(task=task_a)
        id_b: str = await pool._resolve_child_session_id(task=task_b)

        assert id_a != id_b


class TestSubAgentPoolAbortedStatus:
    """Aborted child processes emit ``sub_agent_aborted``, not ``sub_agent_failed``."""

    async def test_aborted_task_emits_sub_agent_aborted_event(self) -> None:
        """A child exiting with status 'aborted' emits ``sub_agent_aborted``."""
        pool, relayed = _make_pool()
        tasks: list[SubAgentTaskDAO] = [
            SubAgentTaskDAO(task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return SubAgentResultDAO(
                task_id=self_proc._task.task_id,
                session_id="s",
                status="aborted",
                exit_code=2,
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
            SubAgentTaskDAO(task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return SubAgentResultDAO(
                task_id=self_proc._task.task_id,
                session_id="s",
                status="aborted",
                exit_code=2,
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
            SubAgentTaskDAO(task_id="t1", prompt="x"),
        ]

        async def _fake_process_run(self_proc) -> SubAgentResultDAO:
            return _failed_result(self_proc._task.task_id)

        with patch(
            "src.agents.slo_agent.orchestrator.pool.SubAgentProcess.run",
            new=_fake_process_run,
        ):
            await pool.dispatch(mode="single", tasks=tasks)

        kinds: list[str] = [e.kind for e in relayed]
        assert "sub_agent_failed" in kinds
        assert "sub_agent_aborted" not in kinds


class TestSubAgentPoolCancelAll:
    """``cancel_all()`` calls ``cancel()`` on every active process."""

    async def test_cancel_all_invokes_cancel_on_each_process(self) -> None:
        """``cancel_all()`` calls ``cancel()`` on every process in ``_active``."""
        pool, _ = _make_pool()
        mock_proc_1: AsyncMock = AsyncMock()
        mock_proc_2: AsyncMock = AsyncMock()
        pool._active = [mock_proc_1, mock_proc_2]

        await pool.cancel_all()

        mock_proc_1.cancel.assert_called_once()
        mock_proc_2.cancel.assert_called_once()

    async def test_cancel_all_tolerates_individual_cancel_failure(self) -> None:
        """``cancel_all()`` continues even when one process's ``cancel`` raises."""
        pool, _ = _make_pool()
        failing_proc: AsyncMock = AsyncMock()
        failing_proc.cancel = AsyncMock(side_effect=RuntimeError("cancel failed"))
        succeeding_proc: AsyncMock = AsyncMock()
        pool._active = [failing_proc, succeeding_proc]

        await pool.cancel_all()  # must not raise

        succeeding_proc.cancel.assert_called_once()
